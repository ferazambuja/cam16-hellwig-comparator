#!/usr/bin/env python3
"""Optional differential against Colour 0.4.7.

The comparator has no runtime dependency on Colour. This test skips when the
package is absent and runs only against the exact version used as the public
numerical anchor. CI installs that version in an isolated verification job.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import unittest

from grid import (
    CASE_COUNT,
    reference_cases,
)


SCRIPT = Path(__file__).parents[1] / "cam16_compare.py"
SPEC = importlib.util.spec_from_file_location("cam16_compare_differential", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cam = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cam
SPEC.loader.exec_module(cam)

COLOUR_SPEC = importlib.util.find_spec("colour")
if COLOUR_SPEC is None:  # pragma: no cover - depends on the local environment
    COLOUR_VERSION = None
else:
    import colour
    from colour.appearance import (
        InductionFactors_CAM16,
        InductionFactors_Hellwig2022,
        XYZ_to_CAM16,
        XYZ_to_Hellwig2022,
    )

    COLOUR_VERSION = colour.__version__


RELATIVE_TOLERANCE = 1.0e-10
ABSOLUTE_TOLERANCE = 1.0e-10
HUE_ABSOLUTE_TOLERANCE_DEGREES = 1.0e-8
UNRESOLVED_CHROMA_LIMITS = {"C": 2.0e-8, "M": 2.0e-8, "s": 1.0e-3}


@unittest.skipUnless(
    COLOUR_VERSION == "0.4.7",
    "requires the pinned comparison oracle colour-science==0.4.7",
)
class ColourDifferentialTests(unittest.TestCase):
    def test_forward_correlates_match_or_are_achromatically_bounded(self):
        model_cases = 0
        unresolved_hues = 0

        for case, factors, discount in reference_cases():
            stimulus = case["XYZ"]
            white = case["XYZ_w"]
            L_A = case["L_A"]
            Y_b = case["Y_b"]
            surround = cam.SURROUNDS[case["surround"]]
            mine, diagnostics = cam.compare_models_with_diagnostics(
                stimulus,
                white,
                L_A,
                Y_b,
                surround,
                degree_of_adaptation_override=1.0 if discount else None,
            )
            references = {
                "cam16": XYZ_to_CAM16(
                    stimulus,
                    white,
                    L_A,
                    Y_b,
                    InductionFactors_CAM16(*factors),
                    discount_illuminant=discount,
                    compute_H=False,
                ),
                "hellwig2022": XYZ_to_Hellwig2022(
                    stimulus,
                    white,
                    L_A,
                    Y_b,
                    InductionFactors_Hellwig2022(*factors),
                    discount_illuminant=discount,
                    compute_H=False,
                ),
            }

            context = (
                f"XYZ={stimulus}, XYZ_w={white}, L_A={L_A}, Y_b={Y_b}, "
                f"surround={surround.name}, discount_illuminant={discount}"
            )
            for model, reference in references.items():
                model_cases += 1
                comparable = (
                    ("J", "Q", "C", "M", "s")
                    if diagnostics["hue_resolved"]
                    else ("J", "Q")
                )
                for correlate in comparable:
                    actual = mine[model][correlate]
                    expected = float(getattr(reference, correlate))
                    self.assertTrue(
                        math.isclose(
                            actual,
                            expected,
                            rel_tol=RELATIVE_TOLERANCE,
                            abs_tol=ABSOLUTE_TOLERANCE,
                        ),
                        f"{model}.{correlate} differs at {context}: "
                        f"actual={actual!r}, expected={expected!r}",
                    )

                if diagnostics["hue_resolved"]:
                    actual_hue = mine[model]["h"]
                    expected_hue = float(reference.h)
                    circular_difference = abs(
                        (actual_hue - expected_hue + 180.0) % 360.0 - 180.0
                    )
                    self.assertLessEqual(
                        circular_difference,
                        HUE_ABSOLUTE_TOLERANCE_DEGREES,
                        f"{model}.h differs at {context}: actual={actual_hue!r}, "
                        f"expected={expected_hue!r}",
                    )
                else:
                    # C, M, and especially sqrt-based s amplify different
                    # floating-point cancellation residues. They need to be
                    # negligible, not bitwise comparable between algorithms.
                    for correlate, limit in UNRESOLVED_CHROMA_LIMITS.items():
                        actual = abs(mine[model][correlate])
                        expected = abs(float(getattr(reference, correlate)))
                        self.assertLessEqual(
                            max(actual, expected),
                            limit,
                            f"unresolved {model}.{correlate} is not negligible "
                            f"at {context}: actual={actual!r}, "
                            f"reference={expected!r}",
                        )
                    unresolved_hues += 1

        self.assertEqual(model_cases, CASE_COUNT * 2)
        self.assertGreater(unresolved_hues, 0)


if __name__ == "__main__":
    unittest.main()
