"""Exercise real OS locks across processes on Windows and Linux."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from queme.services.file_lock import try_lock, unlock


LOCK_PROBE = """
import sys
from queme.services.file_lock import try_lock

with open(sys.argv[1], "a+") as lock_file:
    try:
        try_lock(lock_file)
    except BlockingIOError:
        sys.exit(2)
"""


class FileLockTests(unittest.TestCase):
    def probe(self, path):
        result = subprocess.run(
            [sys.executable, "-c", LOCK_PROBE, str(path)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=15,
        )
        self.assertIn(result.returncode, (0, 2), result.stderr)
        return result.returncode

    def test_exclusive_lock_blocks_another_process_until_unlocked(self):
        with tempfile.TemporaryDirectory(prefix="queme lock ") as directory:
            path = Path(directory) / "worker.lock"
            with path.open("a+") as lock_file:
                try_lock(lock_file)
                try:
                    self.assertEqual(self.probe(path), 2)
                finally:
                    unlock(lock_file)
                self.assertEqual(self.probe(path), 0)

    def test_closing_file_releases_lock_without_deleting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.lock"
            with path.open("a+") as lock_file:
                try_lock(lock_file)
            self.assertTrue(path.exists())
            self.assertEqual(self.probe(path), 0)

    def test_process_exit_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.lock"
            self.assertEqual(self.probe(path), 0)
            with path.open("a+") as lock_file:
                try_lock(lock_file)
                unlock(lock_file)
