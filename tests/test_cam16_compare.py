#!/usr/bin/env python3
"""Regression tests for the dependency-free CAM16/Hellwig comparator."""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "cam16_compare.py"
SPEC = importlib.util.spec_from_file_location("cam16_compare", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cam = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cam
SPEC.loader.exec_module(cam)

XYZ = (19.01, 20.00, 21.78)
WHITE = (95.05, 100.00, 108.88)


class ForwardModelTests(unittest.TestCase):
    def assertCorrelatesAlmostEqual(self, actual, expected, places=7):
        for name, value in expected.items():
            with self.subTest(correlate=name):
                self.assertAlmostEqual(actual[name], value, places=places)

    def test_standard_cam16_published_worked_example(self):
        result = cam.cam16_forward(XYZ, WHITE, 318.31, 20.0)
        self.assertCorrelatesAlmostEqual(
            result,
            {
                "J": 41.7312,
                "Q": 195.3717,
                "C": 0.1034,
                "M": 0.1074,
                "s": 2.3450,
                "h": 217.0680,
            },
            places=4,
        )

    def test_public_colour_047_hellwig_example(self):
        result = cam.hellwig2022_forward(XYZ, WHITE, 318.31, 20.0)
        self.assertCorrelatesAlmostEqual(
            result,
            {
                "J": 41.7312079,
                "Q": 55.8523227,
                "C": 0.0257636,
                "M": 0.0339890,
                "s": 0.0608551,
                "h": 217.0679598,
            },
            places=7,
        )

    def test_both_models_share_lightness_and_hue_but_not_other_correlates(self):
        for surround in (cam.AVERAGE, cam.DIM, cam.DARK):
            with self.subTest(surround=surround.name):
                result = cam.compare_models(
                    (45.0, 36.0, 12.0),
                    (95.047, 100.0, 108.883),
                    20.0,
                    35.0,
                    surround,
                )
                standard = result["cam16"]
                revised = result["hellwig2022"]
                self.assertAlmostEqual(standard["J"], revised["J"], places=12)
                self.assertAlmostEqual(standard["h"], revised["h"], places=12)
                for name in ("Q", "C", "M", "s"):
                    self.assertNotAlmostEqual(standard[name], revised[name], places=6)

    def test_explicit_domain100_normalization_scales_background_too(self):
        canonical = cam.compare_models(XYZ, WHITE, 318.31, 20.0)
        absolute_scale = cam.compare_models(
            tuple(2.0 * value for value in XYZ),
            tuple(2.0 * value for value in WHITE),
            318.31,
            40.0,
            normalize=True,
        )
        for model in canonical:
            for correlate in cam.CORRELATES:
                self.assertAlmostEqual(
                    canonical[model][correlate],
                    absolute_scale[model][correlate],
                    places=12,
                )

    def test_custom_surround_and_adaptation_override_are_supported(self):
        surround = cam.Surround(F=0.95, c=0.62, N_c=0.93)
        computed = cam.compare_models(XYZ, WHITE, 50.0, 20.0, surround)
        complete = cam.compare_models(
            XYZ,
            WHITE,
            50.0,
            20.0,
            surround,
            degree_of_adaptation_override=1.0,
        )
        self.assertNotAlmostEqual(
            computed["cam16"]["h"], complete["cam16"]["h"], places=10
        )
        self.assertAlmostEqual(
            complete["cam16"]["J"], complete["hellwig2022"]["J"], places=12
        )

    def test_hellwig_chroma_is_background_independent_for_fixed_other_inputs(self):
        low = cam.compare_models((45.0, 36.0, 12.0), WHITE, 20.0, 10.0)
        high = cam.compare_models((45.0, 36.0, 12.0), WHITE, 20.0, 60.0)
        self.assertAlmostEqual(
            low["hellwig2022"]["C"], high["hellwig2022"]["C"], places=12
        )
        self.assertNotAlmostEqual(low["cam16"]["C"], high["cam16"]["C"], places=6)

    def test_negative_xyz_and_black_are_refused_by_default(self):
        with self.assertRaisesRegex(ValueError, "negative component"):
            cam.cam16_forward((-0.01, 20.0, 21.78), WHITE, 318.31, 20.0)
        explored = cam.compare_models(
            (-0.01, 20.0, 21.78),
            WHITE,
            318.31,
            20.0,
            allow_negative_xyz=True,
        )
        self.assertGreater(explored["cam16"]["J"], 0.0)
        with self.assertRaisesRegex(cam.ModelDomainError, "all-zero"):
            cam.cam16_forward((0.0, 0.0, 0.0), WHITE, 318.31, 20.0)

    def test_invalid_viewing_conditions_are_refused(self):
        with self.assertRaisesRegex(ValueError, "Y_w = 100"):
            cam.compare_models(XYZ, (19.01, 20.0, 21.78), 20.0, 5.0)
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            cam.compare_models(
                XYZ,
                WHITE,
                20.0,
                20.0,
                degree_of_adaptation_override=1.1,
            )


class CommandLineTests(unittest.TestCase):
    def run_script(self, *arguments, input_text=None):
        return run_script(*arguments, input_text=input_text)

    def test_single_sample_json_is_structured_and_labelled(self):
        process = self.run_script(
            "--xyz",
            "19.01",
            "20",
            "21.78",
            "--white",
            "95.05",
            "100",
            "108.88",
            "--la",
            "318.31",
            "--yb",
            "20",
            "--format",
            "json",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(process.stdout)
        self.assertEqual(document["schema"], cam.SCHEMA)
        self.assertEqual(
            set(document["results"][0]["models"]), {"cam16", "hellwig2022"}
        )
        self.assertEqual(
            document["viewing_conditions"]["degree_of_adaptation_source"],
            "computed",
        )
        self.assertEqual(document["viewing_conditions"]["XYZ_w"], list(WHITE))
        self.assertEqual(
            document["viewing_conditions"]["XYZ_w_as_supplied"], list(WHITE)
        )

    def test_csv_batch_accepts_case_insensitive_columns_and_stdin(self):
        process = self.run_script(
            "--input-csv",
            "-",
            "--white",
            "95.05",
            "100",
            "108.88",
            "--la",
            "318.31",
            "--yb",
            "20",
            "--model",
            "hellwig2022",
            "--format",
            "csv",
            input_text=(
                "# instrument export preamble\n"
                "Label,x,y,z\nneutral,19.01,20,21.78\namber,45,36,12\n"
            ),
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = list(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual([row["label"] for row in rows], ["neutral", "amber"])
        self.assertTrue(all(row["model"] == "hellwig2022" for row in rows))
        self.assertTrue(
            all(
                row["interpretation_limit"] == cam.INTERPRETATION_LIMIT
                for row in rows
            )
        )
        self.assertTrue(all(row["surround"] == "average" for row in rows))
        self.assertTrue(all(float(row["Y_w"]) == 100.0 for row in rows))
        self.assertTrue(all(float(row["L_A_cd_m2"]) == 318.31 for row in rows))

    def test_normalized_json_output_reports_both_xyz_scales(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "absolute.csv"
            source.write_text("X,Y,Z\n38.02,40,43.56\n", encoding="utf-8")
            process = self.run_script(
                "--input-csv",
                str(source),
                "--white",
                "190.1",
                "200",
                "217.76",
                "--la",
                "318.31",
                "--yb",
                "40",
                "--normalize-domain100",
                "--model",
                "cam16",
                "--format",
                "json",
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(process.stdout)
        self.assertEqual(document["results"][0]["XYZ"], [19.01, 20.0, 21.78])
        self.assertEqual(
            document["results"][0]["XYZ_as_supplied"], [38.02, 40.0, 43.56]
        )
        self.assertEqual(
            document["viewing_conditions"]["XYZ_w_as_supplied"],
            [190.1, 200.0, 217.76],
        )
        self.assertEqual(document["viewing_conditions"]["XYZ_w"][1], 100.0)
        self.assertEqual(document["viewing_conditions"]["Y_b_as_supplied"], 40.0)
        self.assertEqual(document["viewing_conditions"]["Y_b"], 20.0)

    def test_partial_custom_surround_is_a_usage_error(self):
        process = self.run_script(
            "--xyz",
            "19.01",
            "20",
            "21.78",
            "--white",
            "95.05",
            "100",
            "108.88",
            "--la",
            "318.31",
            "--yb",
            "20",
            "--surround-f",
            "1",
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("must be supplied together", process.stderr)

    def test_ragged_csv_is_refused_instead_of_silently_shifted(self):
        process = self.run_script(
            "--input-csv",
            "-",
            "--white",
            "95.05",
            "100",
            "108.88",
            "--la",
            "318.31",
            "--yb",
            "20",
            input_text="X,Y,Z\n19.01,20,21.78,unexpected\n",
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("more fields than the header", process.stderr)


BASE_ARGUMENTS = (
    "--xyz", "19.01", "20", "21.78",
    "--white", "95.05", "100", "108.88",
    "--la", "318.31",
    "--yb", "20",
)


class InvocationResult:
    """The three attributes the command-line assertions read."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_script(*arguments, input_text=None):
    """Invoke the command line in process.

    Spawning an interpreter per assertion cost this suite roughly half a
    second each and dominated its wall time as the command-line coverage
    grew. `main()` resolves `sys.stdout`, `sys.stderr`, and `sys.stdin` at
    call time and returns an exit code, so capturing it directly gives the
    same assertions without the spawn. `argparse` exits through `SystemExit`
    for `--help`, `--version`, and argument errors, which is translated back
    into a return code here.

    `SubprocessSmokeTests` still runs the real file, because an in-process
    call cannot show that the script works as a program.
    """

    out, err = io.StringIO(), io.StringIO()
    original_stdin = sys.stdin
    if input_text is not None:
        sys.stdin = io.StringIO(input_text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cam.main(list(arguments))
            except SystemExit as exit_signal:
                code = exit_signal.code if isinstance(exit_signal.code, int) else 0
    finally:
        sys.stdin = original_stdin
    return InvocationResult(code, out.getvalue(), err.getvalue())


def run_script_as_subprocess(*arguments, input_text=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


class MissingConditionGuidanceTests(unittest.TestCase):
    """The first error a newcomer hits has to lead somewhere.

    Refusing to invent a viewing condition is correct, but argparse says only
    that the flags are missing. Someone who does not know what an
    adapting-field luminance is has nowhere to go from there, and the epilog
    that would explain it is printed by --help, never by an error.
    """

    def test_missing_viewing_conditions_offer_a_starting_point(self):
        process = run_script("--xyz", "19.01", "20", "21.78")
        self.assertEqual(process.returncode, 2)
        self.assertIn("usage:", process.stderr)
        self.assertIn("--white 95.05 100 108.88", process.stderr)
        self.assertIn("--la 318.31", process.stderr)
        self.assertIn("--yb 20", process.stderr)
        self.assertIn("--help", process.stderr)

    def test_the_guidance_explains_why_there_is_no_default(self):
        process = run_script("--xyz", "19.01", "20", "21.78")
        self.assertIn("no safe default", process.stderr)

    def test_unrelated_argument_errors_stay_terse(self):
        # A worked viewing condition is noise when the mistake was elsewhere.
        process = run_script(
            *BASE_ARGUMENTS, "--format", "postscript"
        )
        self.assertEqual(process.returncode, 2)
        self.assertNotIn("no safe default", process.stderr)

    def test_option_name_containing_white_does_not_trigger_guidance(self):
        process = run_script(*BASE_ARGUMENTS, "--whitepoint", "D65")
        self.assertEqual(process.returncode, 2)
        self.assertIn("unrecognized arguments", process.stderr)
        self.assertNotIn("no safe default", process.stderr)

    def test_surround_conflict_stays_terse(self):
        process = run_script(
            *BASE_ARGUMENTS,
            "--surround", "dark",
            "--surround-f", "1", "--surround-c", "0.69", "--surround-nc", "1",
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("conflicts with", process.stderr)
        self.assertNotIn("no safe default", process.stderr)


class SubprocessSmokeTests(unittest.TestCase):
    """The file has to work as a program, not only as an imported module."""

    def test_script_runs_and_reports_correlates(self):
        process = run_script_as_subprocess(*BASE_ARGUMENTS)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("cam16", process.stdout)
        self.assertIn("41.7312", process.stdout)

    def test_script_exits_two_on_a_bad_argument(self):
        process = run_script_as_subprocess("--xyz", "19.01", "20", "21.78")
        self.assertEqual(process.returncode, 2)
        self.assertIn("usage:", process.stderr)

    def test_program_name_does_not_follow_the_invocation_path(self):
        # Identity output exists to name the producer. Deriving it from
        # sys.argv[0] would make a vendored or wrapper-invoked copy claim a
        # different program, which is the one thing it must never do.
        renamed = Path(tempfile.mkdtemp()) / "renamed_tool.py"
        renamed.write_bytes(SCRIPT.read_bytes())
        process = subprocess.run(
            [sys.executable, str(renamed), "--version"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(
            process.stdout.strip(),
            f"cam16_compare.py {cam.IMPLEMENTATION_VERSION}",
        )


class StructuralDifferenceTests(unittest.TestCase):
    """Relations the two formulations are defined to differ by.

    These come from Appendix A of the 2022 paper and from the equation audit
    in ``reports/cam16-equation-audit.md``. Asserting correlate values alone
    would let one model be silently edited into the other as long as the
    published example still matched; asserting the relations would not.
    """

    def normalized_brightness(self, model):
        stimulus = cam.compare_models(
            (12.0, 10.0, 8.0), WHITE, 100.0, 20.0, model=model
        )[model]
        white = cam.compare_models(WHITE, WHITE, 100.0, 20.0, model=model)[model]
        return stimulus["Q"] / white["Q"], stimulus["J"] / 100.0

    def test_cam16_normalized_brightness_is_square_root_in_lightness(self):
        ratio, normalized_J = self.normalized_brightness("cam16")
        self.assertAlmostEqual(ratio, math.sqrt(normalized_J), places=12)

    def test_revised_normalized_brightness_is_linear_in_lightness(self):
        ratio, normalized_J = self.normalized_brightness("hellwig2022")
        self.assertAlmostEqual(ratio, normalized_J, places=12)

    def test_revised_colorfulness_carries_no_background_term(self):
        # The revision drops N_bb, N_cb, and the chroma denominator, so Y_b
        # cannot reach M at all. CAM16's M must still move.
        low = cam.compare_models((12.0, 10.0, 8.0), WHITE, 100.0, 5.0)
        high = cam.compare_models((12.0, 10.0, 8.0), WHITE, 100.0, 60.0)
        self.assertEqual(low["hellwig2022"]["M"], high["hellwig2022"]["M"])
        self.assertNotAlmostEqual(low["cam16"]["M"], high["cam16"]["M"], places=6)

    def test_revised_chroma_is_a_fixed_multiple_of_colorfulness(self):
        # C = 35 M / A_w, and A_w belongs to the viewing condition, so every
        # stimulus under one condition shares the ratio.
        first = cam.hellwig2022_forward((12.0, 10.0, 8.0), WHITE, 100.0, 20.0)
        second = cam.hellwig2022_forward((30.0, 40.0, 55.0), WHITE, 100.0, 20.0)
        self.assertAlmostEqual(
            first["C"] / first["M"], second["C"] / second["M"], places=12
        )

    def test_saturation_definitions_differ_by_a_square_root(self):
        both = cam.compare_models((12.0, 10.0, 8.0), WHITE, 100.0, 20.0)
        standard = both["cam16"]
        revised = both["hellwig2022"]
        self.assertAlmostEqual(
            standard["s"],
            100.0 * math.sqrt(standard["M"] / standard["Q"]),
            places=10,
        )
        self.assertAlmostEqual(
            revised["s"], 100.0 * revised["M"] / revised["Q"], places=10
        )

    def test_surround_table_matches_the_published_induction_factors(self):
        self.assertEqual(
            (cam.AVERAGE.F, cam.AVERAGE.c, cam.AVERAGE.N_c), (1.0, 0.69, 1.0)
        )
        self.assertEqual((cam.DIM.F, cam.DIM.c, cam.DIM.N_c), (0.9, 0.59, 0.9))
        self.assertEqual((cam.DARK.F, cam.DARK.c, cam.DARK.N_c), (0.8, 0.525, 0.8))

    def test_darker_surround_raises_lightness(self):
        # c falls from 0.69 to 0.525, so the exponent c*z falls and J rises.
        # This is what shows the surround argument reaching the exponent
        # instead of being accepted and discarded.
        average = cam.cam16_forward(
            (12.0, 10.0, 8.0), WHITE, 100.0, 20.0, cam.AVERAGE
        )
        dark = cam.cam16_forward((12.0, 10.0, 8.0), WHITE, 100.0, 20.0, cam.DARK)
        self.assertGreater(dark["J"], average["J"])


class RefusalTests(unittest.TestCase):
    def test_non_finite_input_is_refused(self):
        with self.assertRaises(ValueError):
            cam.cam16_forward((float("nan"), 20.0, 21.78), WHITE, 318.31, 20.0)

    def test_unknown_model_name_is_refused(self):
        with self.assertRaises(ValueError):
            cam.compare_models(XYZ, WHITE, 318.31, 20.0, model="ciecam02")

    def test_background_outside_the_adopted_white_is_refused(self):
        for background in (0.0, -1.0, 101.0):
            with self.subTest(Y_b=background):
                with self.assertRaises(ValueError):
                    cam.cam16_forward(XYZ, WHITE, 318.31, background)

    def test_non_positive_adapting_luminance_is_refused(self):
        with self.assertRaises(ValueError):
            cam.cam16_forward(XYZ, WHITE, 0.0, 20.0)

    def test_underflowing_background_is_refused_without_a_traceback(self):
        with self.assertRaisesRegex(cam.ModelDomainError, "background"):
            cam.cam16_forward(XYZ, WHITE, 318.31, 5e-324)

        process = run_script(
            "--xyz", "19.01", "20", "21.78",
            "--white", "95.05", "100", "108.88",
            "--la", "318.31", "--yb", "5e-324", "--format", "json",
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("numerical domain", process.stderr)
        self.assertNotIn("Traceback", process.stderr)

    def test_extreme_surround_overflow_is_refused_not_serialized(self):
        process = run_script(
            *BASE_ARGUMENTS,
            "--surround-f", "1", "--surround-c", "0.69",
            "--surround-nc", "1e308", "--format", "json",
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("non-finite correlates", process.stderr)
        self.assertNotIn("Infinity", process.stdout)
        self.assertNotIn("NaN", process.stdout)

        exponent_overflow = run_script(
            *BASE_ARGUMENTS,
            "--surround-f", "1", "--surround-c", "1e308",
            "--surround-nc", "1", "--format", "json",
        )
        self.assertEqual(exponent_overflow.returncode, 2)
        self.assertIn("numerical domain", exponent_overflow.stderr)
        self.assertNotIn("Traceback", exponent_overflow.stderr)

    def test_adaptation_degree_is_clamped_into_the_unit_interval(self):
        self.assertLessEqual(cam.degree_of_adaptation(1e6, cam.AVERAGE), 1.0)
        self.assertGreaterEqual(cam.degree_of_adaptation(1e-6, cam.DARK), 0.0)


class InterpretationLimitTests(unittest.TestCase):
    """Every serialized format has to carry what it is, and what it is not."""

    def test_table_output_states_the_interpretation_limit(self):
        process = run_script(*BASE_ARGUMENTS)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(cam.INTERPRETATION_LIMIT, process.stdout)
        self.assertIn("viewing conditions\n", process.stdout)
        self.assertIn("Domain-100 normalized false", process.stdout)
        self.assertIn("signed XYZ allowed    false", process.stdout)

    def test_csv_output_labels_every_row(self):
        # A column rather than a comment line, so the limit survives a
        # single row being lifted out of the file.
        process = run_script(*BASE_ARGUMENTS, "--format", "csv")
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = list(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(
                row["interpretation_limit"], cam.INTERPRETATION_LIMIT
            )

    def test_json_output_records_the_interpretation_limit(self):
        process = run_script(*BASE_ARGUMENTS, "--format", "json")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(
            json.loads(process.stdout)["interpretation_limit"],
            cam.INTERPRETATION_LIMIT,
        )


class OutputProvenanceTests(unittest.TestCase):
    def test_supplied_triple_survives_normalization(self):
        process = run_script(
            "--xyz", "190.1", "200", "217.8",
            "--white", "950.5", "1000", "1088.8",
            "--la", "318.31", "--yb", "200",
            "--normalize-domain100", "--format", "json",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        record = json.loads(process.stdout)["results"][0]
        # Normalization rewrites the stimulus before the model sees it. Both
        # forms are kept so the record still reads back to what was supplied.
        self.assertAlmostEqual(record["XYZ_as_supplied"][1], 200.0, places=9)
        self.assertAlmostEqual(record["XYZ"][1], 20.0, places=9)
        conditions = json.loads(process.stdout)["viewing_conditions"]
        self.assertAlmostEqual(conditions["XYZ_w_as_supplied"][1], 1000.0)
        self.assertAlmostEqual(conditions["XYZ_w"][1], 100.0)
        self.assertAlmostEqual(conditions["Y_b_as_supplied"], 200.0)
        self.assertAlmostEqual(conditions["Y_b"], 20.0)

    def test_csv_row_preserves_supplied_and_evaluated_conditions(self):
        process = run_script(
            "--xyz", "38.02", "40", "43.56",
            "--white", "190.1", "200", "217.76",
            "--la", "318.31", "--yb", "40",
            "--normalize-domain100", "--degree-of-adaptation", "1",
            "--format", "csv", "--model", "cam16",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        row = next(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual(float(row["Y_as_supplied"]), 40.0)
        self.assertEqual(float(row["Y"]), 20.0)
        self.assertEqual(float(row["Y_w_as_supplied"]), 200.0)
        self.assertEqual(float(row["Y_w"]), 100.0)
        self.assertEqual(float(row["Y_b_as_supplied"]), 40.0)
        self.assertEqual(float(row["Y_b"]), 20.0)
        self.assertEqual(float(row["degree_of_adaptation"]), 1.0)
        self.assertEqual(row["degree_of_adaptation_source"], "override")
        self.assertEqual(row["domain100_normalized"], "true")
        self.assertEqual(row["allow_negative_xyz"], "false")

    def test_declared_signed_input_is_recorded_in_the_output(self):
        # The flag's warning otherwise lives only in the invocation, which is
        # not what a later reader of the file has.
        process = run_script(
            "--xyz", "-1.0", "20", "21.78",
            "--white", "95.05", "100", "108.88",
            "--la", "318.31", "--yb", "20",
            "--allow-negative-xyz", "--format", "json",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        conditions = json.loads(process.stdout)["viewing_conditions"]
        self.assertTrue(conditions["allow_negative_xyz"])

        csv_process = run_script(
            "--xyz", "-1.0", "20", "21.78",
            "--white", "95.05", "100", "108.88",
            "--la", "318.31", "--yb", "20",
            "--allow-negative-xyz", "--format", "csv", "--model", "cam16",
        )
        self.assertEqual(csv_process.returncode, 0, csv_process.stderr)
        row = next(csv.DictReader(io.StringIO(csv_process.stdout)))
        self.assertEqual(row["allow_negative_xyz"], "true")

    def test_unsigned_unnormalized_input_is_recorded_as_such(self):
        process = run_script(*BASE_ARGUMENTS, "--format", "json")
        self.assertEqual(process.returncode, 0, process.stderr)
        conditions = json.loads(process.stdout)["viewing_conditions"]
        self.assertFalse(conditions["allow_negative_xyz"])
        self.assertFalse(conditions["domain100_normalized"])


class SurroundConflictTests(unittest.TestCase):
    def test_named_and_custom_surround_together_are_refused(self):
        # Two viewing conditions were supplied and only one can be used.
        # Preferring either silently is the failure this tool exists to stop.
        process = run_script(
            *BASE_ARGUMENTS,
            "--surround", "dark",
            "--surround-f", "1", "--surround-c", "0.69", "--surround-nc", "1",
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("conflicts with", process.stderr)

    def test_custom_surround_alone_is_accepted(self):
        process = run_script(
            *BASE_ARGUMENTS, "--format", "json",
            "--surround-f", "0.9", "--surround-c", "0.59", "--surround-nc", "0.9",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(process.stdout)
        self.assertEqual(
            document["viewing_conditions"]["surround"]["name"], "custom"
        )

    def test_named_surround_alone_is_accepted(self):
        process = run_script(
            *BASE_ARGUMENTS, "--surround", "dim", "--format", "json"
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(process.stdout)
        self.assertEqual(document["viewing_conditions"]["surround"]["name"], "dim")


class CsvReaderTests(unittest.TestCase):
    def test_commented_preamble_is_skipped(self):
        process = run_script(
            "--input-csv", "-",
            "--white", "95.05", "100", "108.88",
            "--la", "318.31", "--yb", "20",
            "--model", "cam16", "--format", "csv",
            input_text=(
                "# instrument export preamble the reader must skip\n"
                "label,X,Y,Z\n"
                "grey,19.01,20.00,21.78\n"
                "\n"
                "warm,45.00,36.00,12.00\n"
            ),
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = list(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual([row["label"] for row in rows], ["grey", "warm"])

    def test_hash_label_after_header_is_data_not_a_comment(self):
        process = run_script(
            "--input-csv", "-",
            "--white", "100", "100", "100",
            "--la", "100", "--yb", "20",
            "--model", "cam16", "--format", "csv",
            input_text="label,X,Y,Z\n#neutral,33,33,33\n",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        row = next(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual(row["label"], "#neutral")

    def test_utf8_bom_is_accepted_on_standard_input(self):
        process = run_script(
            "--input-csv", "-",
            "--white", "95.05", "100", "108.88",
            "--la", "318.31", "--yb", "20",
            "--model", "cam16", "--format", "csv",
            input_text="\ufefflabel,X,Y,Z\nneutral,19.01,20,21.78\n",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        row = next(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual(row["label"], "neutral")

    def test_bad_row_names_the_file_line_without_argument_usage(self):
        # The line number has to be findable in the file, and a usage block
        # printed above it buries the only useful part of the message.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "samples.csv"
            source.write_text(
                "# preamble\nX,Y,Z\n19.01,20,21.78\n19.01,not-a-number,21.78\n",
                encoding="utf-8",
            )
            process = run_script(
                "--input-csv", str(source),
                "--white", "95.05", "100", "108.88",
                "--la", "318.31", "--yb", "20",
            )
        self.assertEqual(process.returncode, 2)
        self.assertIn("row 4", process.stderr)
        self.assertNotIn("usage:", process.stderr)

    def test_missing_viewing_condition_is_an_argument_error(self):
        process = run_script("--xyz", "19.01", "20", "21.78")
        self.assertEqual(process.returncode, 2)
        self.assertIn("usage:", process.stderr)


class HueResolutionTests(unittest.TestCase):
    """An achromatic stimulus has no hue, and the output has to say so.

    `a` and `b` are formed by near-total cancellation among three nearly equal
    adapted responses, so an exactly achromatic stimulus leaves residue near
    machine epsilon instead of zero and `atan2` turns that residue into a
    confident-looking angle. Two correct implementations of these equations
    disagree by up to 171 degrees there, each reporting its own rounding.
    """

    NEUTRAL = (33.0, 33.0, 33.0)
    EQUAL_ENERGY = (100.0, 100.0, 100.0)

    def test_exact_neutral_is_reported_as_unresolved(self):
        _, diagnostics = cam.compare_models_with_diagnostics(
            self.NEUTRAL, self.EQUAL_ENERGY, 100.0, 20.0
        )
        self.assertFalse(diagnostics["hue_resolved"])
        self.assertLess(diagnostics["opponent_magnitude_ratio"], 1e-15)

    def test_faint_but_real_chroma_is_resolved(self):
        # One channel perturbed in its third decimal is six orders above the
        # cancellation residue, so the threshold must not swallow it.
        _, diagnostics = cam.compare_models_with_diagnostics(
            (33.0, 33.0, 33.001), self.EQUAL_ENERGY, 100.0, 20.0
        )
        self.assertTrue(diagnostics["hue_resolved"])

    def test_ordinary_chromatic_stimulus_is_resolved(self):
        _, diagnostics = cam.compare_models_with_diagnostics(
            (45.0, 36.0, 12.0), WHITE, 100.0, 20.0
        )
        self.assertTrue(diagnostics["hue_resolved"])

    def test_adopted_white_under_incomplete_adaptation_is_resolved(self):
        # With D < 1 the adopted white keeps a small genuine chroma. That is
        # model behavior, not residue, and must not be flagged.
        _, diagnostics = cam.compare_models_with_diagnostics(
            WHITE, WHITE, 318.31, 20.0
        )
        self.assertTrue(diagnostics["hue_resolved"])

    def test_near_complete_adaptation_does_not_overstate_hue_precision(self):
        # The model's D is slightly below one here, so the opponent vector is
        # mathematically non-zero. It is nevertheless too small for supported
        # runtimes to reproduce its direction at the precision the table shows.
        _, diagnostics = cam.compare_models_with_diagnostics(
            WHITE, WHITE, 2000.0, 20.0
        )
        self.assertFalse(diagnostics["hue_resolved"])
        self.assertGreater(diagnostics["opponent_magnitude_ratio"], 1e-13)

        process = run_script(
            "--xyz", *(str(value) for value in WHITE),
            "--white", *(str(value) for value in WHITE),
            "--la", "2000", "--yb", "20",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("n/a", process.stdout)
        self.assertIn(
            "too close to floating-point cancellation",
            " ".join(process.stdout.split()),
        )

    def test_diagnostics_do_not_change_the_correlates(self):
        models, _ = cam.compare_models_with_diagnostics(XYZ, WHITE, 318.31, 20.0)
        self.assertEqual(models, cam.compare_models(XYZ, WHITE, 318.31, 20.0))

    def test_table_names_the_unresolved_sample(self):
        process = run_script(
            "--xyz", "33", "33", "33",
            "--white", "100", "100", "100",
            "--la", "100", "--yb", "20",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("hue not resolved for", process.stdout)

    def test_table_stays_quiet_for_a_resolved_sample(self):
        process = run_script(*BASE_ARGUMENTS)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("hue not resolved", process.stdout)

    def test_csv_carries_the_flag_on_every_row(self):
        process = run_script(
            "--xyz", "33", "33", "33",
            "--white", "100", "100", "100",
            "--la", "100", "--yb", "20", "--format", "csv",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = list(csv.DictReader(io.StringIO(process.stdout)))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["hue_resolved"], "false")

    def test_json_records_the_shared_diagnostic_once_per_sample(self):
        process = run_script(*BASE_ARGUMENTS, "--format", "json")
        self.assertEqual(process.returncode, 0, process.stderr)
        record = json.loads(process.stdout)["results"][0]
        # Both models derive h from the same a and b, so the diagnostic sits
        # beside the models rather than inside either one.
        self.assertTrue(record["hue_diagnostics"]["hue_resolved"])
        self.assertNotIn("hue_resolved", record["models"]["cam16"])


class HelpTextTests(unittest.TestCase):
    def test_every_user_option_has_help_text(self):
        missing = []
        for action in cam._parser()._actions:
            if not action.option_strings or "--help" in action.option_strings:
                continue
            if not isinstance(action.help, str) or not action.help.strip():
                missing.extend(action.option_strings)
        self.assertEqual(missing, [])

    def test_defaults_are_stated_for_optional_choices(self):
        process = run_script("--help")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("default: both", process.stdout)
        self.assertIn("default: table", process.stdout)

    def test_help_carries_a_complete_runnable_example(self):
        process = run_script("--help")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("example:", process.stdout)
        self.assertIn("python3 cam16_compare.py --xyz", process.stdout)
        for fragment in ("--white", "--la", "--yb"):
            self.assertIn(fragment, process.stdout)

    def test_help_states_that_conditions_apply_to_the_whole_batch(self):
        process = run_script("--help")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("every sample in a CSV batch", process.stdout)

    def test_help_fits_eighty_columns(self):
        process = run_script("--help")
        self.assertEqual(process.returncode, 0, process.stderr)
        for line in process.stdout.splitlines():
            with self.subTest(line=line):
                self.assertLessEqual(len(line), 80)

    def test_version_is_available_without_model_inputs(self):
        process = run_script("--version")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(
            process.stdout.strip(),
            f"cam16_compare.py {cam.IMPLEMENTATION_VERSION}",
        )


class TableGeometryTests(unittest.TestCase):
    def assertFitsTerminal(self, output):
        for line in output.splitlines():
            with self.subTest(line=line):
                if line.startswith("sample-1"):
                    # Labels are caller-controlled; the fixed part still fits.
                    self.assertLessEqual(len(line) - len("sample-1"), 72)
                else:
                    self.assertLessEqual(len(line), 80)

    def test_standard_table_fits_eighty_columns(self):
        process = run_script(*BASE_ARGUMENTS)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFitsTerminal(process.stdout)

    def test_unresolved_hue_warning_also_fits_eighty_columns(self):
        process = run_script(
            "--xyz", "33", "33", "33",
            "--white", "100", "100", "100",
            "--la", "100", "--yb", "20",
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("hue not resolved", process.stdout)
        self.assertFitsTerminal(process.stdout)

    def test_condition_values_and_precision_note_are_present(self):
        process = run_script(*BASE_ARGUMENTS)
        self.assertEqual(process.returncode, 0, process.stderr)
        for fragment in (
            "95.05",
            "318.31",
            "average",
            "computed",
            "6 significant digits",
        ):
            self.assertIn(fragment, process.stdout)

    def test_full_precision_survives_in_csv(self):
        process = run_script(*BASE_ARGUMENTS, "--format", "csv")
        self.assertEqual(process.returncode, 0, process.stderr)
        row = next(csv.DictReader(io.StringIO(process.stdout)))
        expected = cam.cam16_forward(XYZ, WHITE, 318.31, 20.0)["J"]
        self.assertEqual(float(row["J"]), expected)


class RowIdentityTests(unittest.TestCase):
    def test_table_names_its_version_without_machine_schema(self):
        process = run_script(*BASE_ARGUMENTS)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(cam.IMPLEMENTATION_VERSION, process.stdout)
        self.assertNotIn(cam.SCHEMA, process.stdout)

    def test_csv_row_names_its_schema_and_version(self):
        process = run_script(*BASE_ARGUMENTS, "--format", "csv")
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = list(csv.DictReader(io.StringIO(process.stdout)))
        for row in rows:
            self.assertEqual(row["schema"], cam.SCHEMA)
            self.assertEqual(
                row["implementation_version"], cam.IMPLEMENTATION_VERSION
            )

    def test_json_names_its_schema_and_version(self):
        process = run_script(*BASE_ARGUMENTS, "--format", "json")
        self.assertEqual(process.returncode, 0, process.stderr)
        document = json.loads(process.stdout)
        self.assertEqual(document["schema"], cam.SCHEMA)
        self.assertEqual(
            document["implementation_version"], cam.IMPLEMENTATION_VERSION
        )

    def test_version_is_a_three_part_number(self):
        self.assertRegex(cam.IMPLEMENTATION_VERSION, r"^\d+\.\d+\.\d+$")


class WarningWrappingTests(unittest.TestCase):
    """The unresolved-hue line exists to name samples, so names must survive."""

    LABELS = (
        "grey-patch-01",
        "grey-patch-02",
        "very-long-neutral-sample-name-three",
        "very-long-neutral-sample-name-four",
    )

    def unresolved_batch(self):
        rows = "\n".join(
            f"{label},{10 * (index + 1)},{10 * (index + 1)},{10 * (index + 1)}"
            for index, label in enumerate(self.LABELS)
        )
        return run_script(
            "--input-csv", "-",
            "--white", "100", "100", "100",
            "--la", "100", "--yb", "20", "--model", "cam16",
            input_text=f"label,X,Y,Z\n{rows}\n",
        )

    def test_every_label_survives_the_wrap_intact(self):
        process = self.unresolved_batch()
        self.assertEqual(process.returncode, 0, process.stderr)
        start = process.stdout.index("hue not resolved for:")
        warning = process.stdout[start:]
        for label in self.LABELS:
            with self.subTest(label=label):
                # A hyphen-split label would not be found here, which is
                # exactly the failure a reader searching the output would hit.
                self.assertIn(label, warning)

    def test_wrapped_warning_still_fits_eighty_columns(self):
        process = self.unresolved_batch()
        start = process.stdout.index("hue not resolved for:")
        for line in process.stdout[start:].splitlines():
            with self.subTest(line=line):
                self.assertLessEqual(len(line), 80)


class TerminalLabelTests(unittest.TestCase):
    def test_table_escapes_newlines_and_terminal_controls_in_labels(self):
        process = run_script(
            "--input-csv", "-",
            "--white", "95.05", "100", "108.88",
            "--la", "318.31", "--yb", "20",
            "--model", "cam16",
            input_text=(
                "label,X,Y,Z\n"
                '"line\nbreak",19.01,20,21.78\n'
                '"ansi\x1b[31mred",45,36,12\n'
            ),
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(r"line\nbreak", process.stdout)
        self.assertIn(r"ansi\x1b[31mred", process.stdout)
        self.assertNotIn("\x1b", process.stdout)
        self.assertNotIn("\nline\n", process.stdout)


if __name__ == "__main__":
    unittest.main()
