#!/usr/bin/env python3
"""Cross-language contract and numerical differential for the browser port."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from grid import CASE_COUNT, boundary_cases, cases


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "cam16_compare.py"
NODE = shutil.which("node")
SPEC = importlib.util.spec_from_file_location("cam16_compare_js_parity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cam = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cam
SPEC.loader.exec_module(cam)

# The largest resolved-chroma difference on this grid is 5.43e-12 relative.
# It comes from libm/V8 rounding amplified by a small opponent vector; 1e-11
# keeps a measured margin without treating achromatic cancellation as signal.
RELATIVE_TOLERANCE = 1.0e-11
# Absolute tolerance governs diagnostics near zero; resolved model correlates
# remain subject to the relative comparison below.
ABSOLUTE_TOLERANCE = 2.0e-12
HUE_ABSOLUTE_TOLERANCE_DEGREES = 1.0e-9
UNRESOLVED_CHROMA_LIMITS = {"C": 2.0e-8, "M": 2.0e-8, "s": 1.0e-3}

# Immediately above the cutoff the two implementations are measurably looser:
# up to 1.53e-8 relative and 2.18e-7 degrees on the supported local runtimes.
# These bounds cover that measured variation while remaining tighter than the
# six-significant-digit display for the pinned cases. They apply only here.
BOUNDARY_RELATIVE_TOLERANCE = 1.0e-7
BOUNDARY_HUE_TOLERANCE_DEGREES = 1.0e-6


def six_significant_digits(value: float) -> float:
    """Return the numeric value represented by the readable table."""

    return float(f"{value:.6g}")


def run_javascript(request: dict[str, object]) -> object:
    assert NODE is not None
    completed = subprocess.run(
        [NODE, "tests/js/evaluate_cases.mjs"],
        cwd=ROOT,
        input=json.dumps(request, allow_nan=False),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


def python_evaluate(case: dict[str, object]) -> dict[str, object]:
    surround = cam.SURROUNDS[str(case["surround"])]
    models, diagnostics = cam.compare_models_with_diagnostics(
        case["XYZ"],
        case["XYZ_w"],
        float(case["L_A"]),
        float(case["Y_b"]),
        surround,
        degree_of_adaptation_override=case["degree_of_adaptation_override"],
    )
    return {"models": models, "hue_diagnostics": diagnostics}


@unittest.skipUnless(NODE, "requires Node.js")
class BrowserParityTests(unittest.TestCase):
    def test_public_constants_and_surrounds_match_the_python_authority(self):
        metadata = run_javascript({"action": "metadata"})
        assert isinstance(metadata, dict)
        self.assertEqual(metadata["BROWSER_API_VERSION"], "cam16-browser-api-v1")
        self.assertEqual(metadata["IMPLEMENTATION_VERSION"], cam.IMPLEMENTATION_VERSION)
        self.assertEqual(metadata["INTERPRETATION_LIMIT"], cam.INTERPRETATION_LIMIT)
        self.assertEqual(metadata["OPPONENT_NOISE_RATIO"], cam.OPPONENT_NOISE_RATIO)
        for name, surround in cam.SURROUNDS.items():
            self.assertEqual(
                metadata["surrounds"][name],
                {"F": surround.F, "c": surround.c, "N_c": surround.N_c, "name": name},
            )

    def test_all_grid_correlates_and_hue_decisions_match(self):
        declared_cases = list(cases())
        self.assertEqual(len(declared_cases), CASE_COUNT)
        javascript = run_javascript({"action": "evaluate", "cases": declared_cases})
        assert isinstance(javascript, list)
        self.assertEqual(len(javascript), CASE_COUNT)

        resolved_ratios: list[float] = []
        unresolved_ratios: list[float] = []
        for index, (case, js_result) in enumerate(zip(declared_cases, javascript)):
            context = f"case {index}: {case}"
            self.assertTrue(js_result["ok"], f"JavaScript refused {context}: {js_result}")
            expected = python_evaluate(case)
            actual = js_result["value"]
            expected_diagnostics = expected["hue_diagnostics"]
            actual_diagnostics = actual["hue_diagnostics"]
            self.assertEqual(
                actual_diagnostics["hue_resolved"],
                expected_diagnostics["hue_resolved"],
                context,
            )
            ratio = float(expected_diagnostics["opponent_magnitude_ratio"])
            if expected_diagnostics["hue_resolved"]:
                resolved_ratios.append(ratio)
            else:
                unresolved_ratios.append(ratio)
            for diagnostic in ("opponent_magnitude", "opponent_magnitude_ratio"):
                self.assertTrue(
                    math.isclose(
                        actual_diagnostics[diagnostic],
                        expected_diagnostics[diagnostic],
                        rel_tol=RELATIVE_TOLERANCE,
                        abs_tol=ABSOLUTE_TOLERANCE,
                    ),
                    f"{diagnostic} differs at {context}",
                )

            for model in ("cam16", "hellwig2022"):
                comparable = (
                    ("J", "Q", "C", "M", "s")
                    if expected_diagnostics["hue_resolved"]
                    else ("J", "Q")
                )
                for correlate in comparable:
                    mine = actual["models"][model][correlate]
                    theirs = expected["models"][model][correlate]
                    self.assertTrue(
                        math.isclose(
                            mine,
                            theirs,
                            rel_tol=RELATIVE_TOLERANCE,
                            abs_tol=ABSOLUTE_TOLERANCE,
                        ),
                        f"{model}.{correlate} differs at {context}: "
                        f"actual={mine!r}, expected={theirs!r}",
                    )
                if expected_diagnostics["hue_resolved"]:
                    circular_difference = abs(
                        (
                            actual["models"][model]["h"]
                            - expected["models"][model]["h"]
                            + 180.0
                        )
                        % 360.0
                        - 180.0
                    )
                    self.assertLessEqual(
                        circular_difference,
                        HUE_ABSOLUTE_TOLERANCE_DEGREES,
                        f"{model}.h differs at {context}",
                    )
                else:
                    for correlate, limit in UNRESOLVED_CHROMA_LIMITS.items():
                        self.assertLessEqual(
                            max(
                                abs(actual["models"][model][correlate]),
                                abs(expected["models"][model][correlate]),
                            ),
                            limit,
                            f"unresolved {model}.{correlate} at {context}",
                        )

        self.assertTrue(resolved_ratios)
        self.assertTrue(unresolved_ratios)

        # The declared portability grid deliberately leaves a measured gap on
        # both sides of the numerical-resolution boundary. This prevents a
        # runtime's last-bit rounding from changing whether the public result
        # prints a hue at all.
        self.assertGreater(
            min(resolved_ratios),
            cam.OPPONENT_NOISE_RATIO * 1000.0,
        )
        self.assertLess(
            max(unresolved_ratios),
            cam.OPPONENT_NOISE_RATIO / 1000.0,
        )

    def test_agreement_just_above_the_hue_resolution_cutoff(self):
        # The broad grid cannot characterize the boundary because it is
        # deliberately required to stay clear of it. Agreement in this narrow
        # band is non-monotonic at the last bits, so this test checks the actual
        # contract: both implementations make the same hue-resolution decision,
        # stay within explicit raw-value bounds, and show the same six digits.
        declared = list(boundary_cases())
        results = run_javascript(
            {"action": "evaluate", "cases": [case for case, _ in declared]}
        )
        assert isinstance(results, list)

        for (case, target_ratio), js_result in zip(declared, results):
            with self.subTest(target_ratio=target_ratio):
                self.assertTrue(js_result["ok"], js_result)
                expected = python_evaluate(case)
                actual = js_result["value"]

                # The offsets are pinned inputs; confirm they still land where
                # they were bisected before drawing conclusions from them.
                self.assertAlmostEqual(
                    float(expected["hue_diagnostics"]["opponent_magnitude_ratio"]),
                    target_ratio,
                    delta=target_ratio * 1.0e-3,
                )
                self.assertTrue(expected["hue_diagnostics"]["hue_resolved"])
                self.assertEqual(
                    actual["hue_diagnostics"]["hue_resolved"],
                    expected["hue_diagnostics"]["hue_resolved"],
                )
                self.assertTrue(
                    math.isclose(
                        float(actual["hue_diagnostics"][
                            "opponent_magnitude_ratio"
                        ]),
                        float(expected["hue_diagnostics"][
                            "opponent_magnitude_ratio"
                        ]),
                        rel_tol=BOUNDARY_RELATIVE_TOLERANCE,
                        abs_tol=0.0,
                    )
                )

                # Loose on purpose. Tightening this to the grid tolerance
                # would not make the tool more correct; it would only delete
                # the coverage again.
                for model in ("cam16", "hellwig2022"):
                    for correlate in ("J", "Q", "C", "M", "s"):
                        actual_value = actual["models"][model][correlate]
                        expected_value = expected["models"][model][correlate]
                        self.assertTrue(
                            math.isclose(
                                actual_value,
                                expected_value,
                                rel_tol=BOUNDARY_RELATIVE_TOLERANCE,
                                abs_tol=ABSOLUTE_TOLERANCE,
                            ),
                            f"{model}.{correlate} at ratio {target_ratio:.1e}",
                        )
                        self.assertEqual(
                            six_significant_digits(actual_value),
                            six_significant_digits(expected_value),
                            f"displayed {model}.{correlate} at ratio "
                            f"{target_ratio:.1e}",
                        )
                    actual_hue = actual["models"][model]["h"]
                    expected_hue = expected["models"][model]["h"]
                    circular_difference = abs(
                        (actual_hue - expected_hue + 180.0) % 360.0 - 180.0
                    )
                    self.assertLessEqual(
                        circular_difference,
                        BOUNDARY_HUE_TOLERANCE_DEGREES,
                        f"{model}.h at ratio {target_ratio:.1e}",
                    )
                    self.assertEqual(
                        six_significant_digits(actual_hue),
                        six_significant_digits(expected_hue),
                        f"displayed {model}.h at ratio {target_ratio:.1e}",
                    )

    def test_refusal_classes_cover_common_user_and_numerical_failures(self):
        refusal_cases = [
            {
                "XYZ": [0.0, 0.0, 0.0],
                "XYZ_w": [95.047, 100.0, 108.883],
                "L_A": 20.0,
                "Y_b": 20.0,
            },
            {
                "XYZ": [1.0, -2.0, 3.0],
                "XYZ_w": [95.047, 100.0, 108.883],
                "L_A": 20.0,
                "Y_b": 20.0,
            },
            {
                "XYZ": [19.01, 20.0, 21.78],
                "XYZ_w": [95.047, 50.0, 108.883],
                "L_A": 20.0,
                "Y_b": 20.0,
            },
            {
                "XYZ": [19.01, 20.0, 21.78],
                "XYZ_w": [95.047, 100.0, 108.883],
                "L_A": 20.0,
                "Y_b": 1.0e-320,
            },
        ]
        results = run_javascript({"action": "evaluate", "cases": refusal_cases})
        assert isinstance(results, list)
        self.assertEqual([item["ok"] for item in results], [False] * 4)
        self.assertEqual(results[0]["error"]["name"], "ModelDomainError")
        self.assertEqual(
            results[0]["error"]["message"],
            "all-zero XYZ has undefined chromatic correlates; no hue or saturation is reported",
        )
        self.assertEqual(results[1]["error"]["name"], "RangeError")
        self.assertIn("negative component", results[1]["error"]["message"])
        self.assertEqual(results[2]["error"]["name"], "RangeError")
        self.assertIn("Domain-100", results[2]["error"]["message"])
        self.assertEqual(results[3]["error"]["name"], "ModelDomainError")
        self.assertIn("background induction factor", results[3]["error"]["message"])


if __name__ == "__main__":
    unittest.main()
