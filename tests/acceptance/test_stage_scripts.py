"""Old entrypoints must fail safely before touching any historical evidence."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class StageScriptTests(unittest.TestCase):
    def test_historical_scripts_refuse_new_package_in_isolated_checkout(self):
        root = Path(__file__).resolve().parents[2]
        base = root / "var/stage-guard-tests"
        base.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=base) as temporary:
            copied = Path(temporary)
            for directory in ("scripts", "tests"):
                shutil.copytree(root / directory, copied / directory, ignore=shutil.ignore_patterns("__pycache__"))
            sentinel = copied / "examples/sentinel.json"
            sentinel.parent.mkdir()
            sentinel.write_text("preserve", encoding="utf-8")
            for name in ("run_m4_offline.py", "run_m4_real.py", "verify_m4.py", "verify_m5.py"):
                with self.subTest(script=name):
                    process = subprocess.run([sys.executable, str(copied / "scripts" / name)], cwd=copied,
                                             env=dict(os.environ, PYTHONUTF8="1"), capture_output=True,
                                             text=True, encoding="utf-8", timeout=10)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertIn("Historical stage script requires package", process.stdout + process.stderr)
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
                    self.assertEqual(list(sentinel.parent.iterdir()), [sentinel])
