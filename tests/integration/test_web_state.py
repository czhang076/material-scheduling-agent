"""Optional Node dev check against the installed web asset, including wheel mode."""

from importlib.resources import files
import os
from pathlib import Path
import shutil
import subprocess
import unittest


class WebStateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is an optional development verifier, not a runtime dependency")
    def test_real_controller_async_and_submission_regressions(self):
        source = files("material_scheduler.interfaces.web").joinpath("app.js")
        suite = Path(__file__).resolve().parents[1] / "web/state.test.cjs"
        result = subprocess.run([shutil.which("node"), "--test", str(suite)],
                                env=dict(os.environ, SCHEDULER_WEB_SOURCE=str(source)),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
