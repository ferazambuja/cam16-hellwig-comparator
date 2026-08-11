#!/usr/bin/env python3
"""Execute the README's shell examples without invoking a shell."""

from __future__ import annotations

import difflib
from pathlib import Path
import re
import shlex
import subprocess
import sys
import unittest


ROOT = Path(__file__).parents[1]
README = ROOT / "README.md"
SCRIPT = ROOT / "cam16_compare.py"
SHELL_BLOCK = re.compile(r"^```sh\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
RESULT_BLOCK = re.compile(
    r"^```(?P<kind>sh|text)\s*\n(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)


def commands_from_markdown(markdown: str) -> list[list[str]]:
    """Return safe comparator commands from every fenced ``sh`` block."""

    blocks = SHELL_BLOCK.findall(markdown)
    if not blocks:
        raise AssertionError("README.md contains no fenced sh examples")

    commands = []
    for index, block in enumerate(blocks, start=1):
        logical_line = block.replace("\\\n", " ").strip()
        arguments = shlex.split(logical_line, posix=True)
        if arguments[:2] != ["python3", "cam16_compare.py"]:
            raise AssertionError(
                f"README sh block {index} is not a single cam16_compare.py "
                "invocation"
            )
        if any(
            argument == "--output" or argument.startswith("--output=")
            for argument in arguments
        ):
            raise AssertionError(
                f"README sh block {index} writes a file and is unsafe to "
                "execute as documentation"
            )
        if "--input-csv" in arguments:
            source = arguments[arguments.index("--input-csv") + 1]
            if source != "-" and not (ROOT / source).exists():
                raise AssertionError(
                    f"README sh block {index} reads {source!r}, which is not "
                    "in the repository. A reader copying it gets an error."
                )
        commands.append([sys.executable, str(SCRIPT), *arguments[2:]])
    return commands


def documented_commands() -> list[list[str]]:
    return commands_from_markdown(README.read_text(encoding="utf-8"))


def sample_output_cases(markdown: str) -> list[tuple[list[str], str]]:
    """Bind every result table to the documented command preceding it."""

    command = None
    cases = []
    for block in RESULT_BLOCK.finditer(markdown):
        kind = block.group("kind")
        body = block.group("body")
        if kind == "sh":
            command = commands_from_markdown(block.group(0))[0]
        elif body.lstrip().startswith("label"):
            if command is None:
                raise AssertionError(
                    "README result table has no preceding comparator command"
                )
            cases.append((command, body))
    return cases


def run_documented(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, check=False,
        timeout=15,
    )


class ReadmeExampleTests(unittest.TestCase):
    def test_every_shell_example_runs(self):
        commands = documented_commands()
        for index, command in enumerate(commands, start=1):
            with self.subTest(block=index):
                process = run_documented(command)
                self.assertEqual(process.returncode, 0, process.stderr)

    def test_documented_sample_output_matches_the_tool(self):
        # Executing the commands proves they still work; it says nothing about
        # the result pasted underneath them. That block is hand-copied, so it
        # goes stale on any change to units, version, or field wording while
        # every example still exits zero.
        markdown = README.read_text(encoding="utf-8")
        cases = sample_output_cases(markdown)
        self.assertTrue(cases, "README shows no sample output to check")

        for index, (command, table) in enumerate(cases, start=1):
            with self.subTest(block=index):
                process = run_documented(command)
                self.assertEqual(process.returncode, 0, process.stderr)
                produced = process.stdout.strip()
                if table.strip() == produced:
                    continue
                diff = "\n".join(
                    difflib.unified_diff(
                        table.strip().splitlines(),
                        produced.splitlines(),
                        "README",
                        "actual",
                        lineterm="",
                    )
                )
                self.fail(
                    f"README text block {index} does not match the output of "
                    f"its preceding documented command:\n{diff}"
                )

    def test_sample_output_is_bound_to_the_preceding_command(self):
        markdown = """\
```sh
python3 cam16_compare.py --xyz 1 2 3 --white 95 100 108 --la 20 --yb 20
```
```sh
python3 cam16_compare.py --xyz 4 5 6 --white 95 100 108 --la 20 --yb 20
```
```text
label result
```
"""
        cases = sample_output_cases(markdown)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0][0][3:6], ["4", "5", "6"])

    def test_sample_output_without_a_command_is_refused(self):
        markdown = "```text\nlabel result\n```\n"
        with self.assertRaisesRegex(AssertionError, "no preceding"):
            sample_output_cases(markdown)

    def test_unrelated_shell_command_is_refused_before_execution(self):
        with self.assertRaisesRegex(AssertionError, "not a single"):
            commands_from_markdown("```sh\necho not-the-comparator\n```\n")

    def test_output_writes_are_refused_before_execution(self):
        for spelling in ("--output result.json", "--output=result.json"):
            with self.subTest(spelling=spelling):
                markdown = (
                    "```sh\npython3 cam16_compare.py --xyz 1 2 3 "
                    f"{spelling}\n```\n"
                )
                with self.assertRaisesRegex(AssertionError, "unsafe"):
                    commands_from_markdown(markdown)

    def test_missing_input_file_is_refused_before_execution(self):
        markdown = (
            "```sh\npython3 cam16_compare.py --input-csv gone.csv "
            "--white 95.05 100 108.88 --la 318.31 --yb 20\n```\n"
        )
        with self.assertRaisesRegex(AssertionError, "not\n?\\s*in the repository"):
            commands_from_markdown(markdown)

    def test_the_shipped_example_batch_is_referenced(self):
        # The example file exists to make the batch section runnable. If no
        # documented command uses it, one of the two has drifted.
        readme = README.read_text(encoding="utf-8")
        self.assertIn("examples/samples.csv", readme)
        self.assertTrue((ROOT / "examples" / "samples.csv").exists())


if __name__ == "__main__":
    unittest.main()
