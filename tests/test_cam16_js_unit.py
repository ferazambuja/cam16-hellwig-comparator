#!/usr/bin/env python3
"""Run the dependency-free browser module's native Node test suite."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "requires Node.js")
class BrowserModuleUnitTests(unittest.TestCase):
    def test_native_node_suite(self):
        completed = subprocess.run(
            [NODE, "--test", "tests/js/cam16_compare.test.mjs"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)


if __name__ == "__main__":
    unittest.main()
