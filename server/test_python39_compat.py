"""Regression check for the minimum local Python runtime."""

import subprocess
import sys


def run() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import server.main"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    print("Python 3.9 compatibility test passed")


if __name__ == "__main__":
    run()
