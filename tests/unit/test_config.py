"""설정 로더: 기본 설정 검증과 오류 메시지 (파일·키 한 줄)."""

from __future__ import annotations

import pytest

from tests.conftest import CONFIG
from twin.common.config import ConfigError, load_config


def test_default_config_loads() -> None:
    cfg = load_config(CONFIG)
    assert len(cfg.equipment) == 22
    assert {e.kind for e in cfg.equipment} == {
        "bus",
        "plc_tcp",
        "edge_modbus_tcp",
        "edge_opcua",
        "edge_ascii",
    }
    assert cfg.block_base("SAL-01") == ("MASTER", 100)
    assert cfg.block_base("THD-01") == ("SLAVE", 100)
    assert cfg.equip("SAN-01").comm_type == "Ethernet(TCP/IP)"
    assert cfg.equip("SCALE-01").comm_type == "RS-232"
    assert all(r.basis in ("설계", "가정") for r in cfg.ccp)


def test_assumed_values_are_marked() -> None:
    cfg = load_config(CONFIG)
    for code in ("MD-01", "SCALE-01", "FILL-01", "STUFF-01", "SAL-01"):
        assert cfg.equip(code).assumed, f"{code}는 [가정] 표시가 있어야 함"


def test_overlapping_blocks_rejected() -> None:
    with pytest.raises(
        ConfigError, match=r"plc_map.yaml blocks.MASTER: D0105\(SAL-02\)가 D0100~D0109\(SAL-01\)와 겹침"
    ):
        load_config(CONFIG, {"plc_map": {"blocks": {"MASTER": {"SAL-02": 105}}}})


def test_block_overlapping_diag_rejected() -> None:
    with pytest.raises(ConfigError, match="진단영역"):
        load_config(CONFIG, {"plc_map": {"blocks": {"MASTER": {"MD-01": 895}}}})


def test_block_on_wrong_plc_rejected() -> None:
    with pytest.raises(ConfigError, match="1:1 위반|소속"):
        load_config(CONFIG, {"plc_map": {"blocks": {"SLAVE": {"SAL-01": 300}}}})


def test_duplicate_slave_rejected() -> None:
    with pytest.raises(ConfigError, match="slave 2가 SAL-02와 중복|중복"):
        load_config(CONFIG, {"equipment_patch": {"THD-07": {"via": {"slave": 2}}}})


def test_bad_register_format_points_to_key() -> None:
    with pytest.raises(ConfigError, match=r"^config: equipment.yaml equipment\[0\]"):
        load_config(
            CONFIG,
            {
                "equipment_patch": {
                    "SAL-01": {
                        "items": [
                            {
                                "key": "x",
                                "name": "x",
                                "reg": "IR40001",
                                "type": "uint16",
                                "unit": "X",
                                "data_type": "x",
                            }
                        ]
                    }
                }
            },
        )


def test_runtime_type_error_message() -> None:
    with pytest.raises(ConfigError, match=r"^config: runtime.yaml edge.batch_max"):
        load_config(CONFIG, {"runtime": {"edge": {"batch_max": "many"}}})
