"""AC-13 메모리 블록이 겹치게 설정 → 기동 거부, 겹친 주소 표시."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.conftest import CONFIG, ROOT

pytestmark = pytest.mark.acceptance


def test_ac13_overlap_refuses_startup(tmp_path: Path):
    cfg_dir = tmp_path / "config"
    shutil.copytree(CONFIG, cfg_dir)
    pm = yaml.safe_load((cfg_dir / "plc_map.yaml").read_text(encoding="utf-8"))
    pm["blocks"]["MASTER"]["TC-02"] = 205  # TC-01(D0200~D0209)과 겹침
    (cfg_dir / "plc_map.yaml").write_text(yaml.safe_dump(pm, allow_unicode=True), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "twin.supervisor", "--config", str(cfg_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    out = proc.stdout + proc.stderr
    assert "plc_map.yaml" in out and "D0205(TC-02)" in out and "D0200~D0209(TC-01)" in out
