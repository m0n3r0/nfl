"""Browser-level regression gates for the Yahoo CDP driver.

These tests are opt-in locally because they require a Chromium process exposing
CDP on 127.0.0.1:9222. CI starts an isolated headless browser and enables them
with RUN_CDP_BROWSER_TESTS=1; neither harness opens or modifies a Yahoo page.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUN_CDP = os.environ.get("RUN_CDP_BROWSER_TESTS") == "1"


@pytest.mark.cdp
@pytest.mark.skipif(not RUN_CDP, reason="requires an isolated Chromium CDP process")
@pytest.mark.parametrize("script", ["test_driver_cdp.py", "mock_draft_run.py"])
def test_cdp_harness(script, tmp_path):
    env = os.environ.copy()
    env.update({
        "DRAFT_DRIVER": str(ROOT / "driver" / "draft_driver.py"),
        "FD_DRAFT_LOG": str(tmp_path / "draft_log.txt"),
        "MOCK_LOG": str(tmp_path / "mock_draft_log.txt"),
    })
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, (
        f"{script} failed with exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
