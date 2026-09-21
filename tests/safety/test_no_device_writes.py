"""안전: 코드베이스에 설비 쓰기(Write) 경로가 없어야 한다 (spec 12장, metaprompt 규칙 1)."""

import re

import pytest

from tests.conftest import ROOT

pytestmark = pytest.mark.safety
SRC = ROOT / "src" / "twin"
FORBIDDEN = re.compile(r"\b(write_register|write_registers|write_coil|write_coils)\s*\(")
# OPC-UA write_value는 필드 시뮬레이터가 자기 노드 값을 갱신할 때만 허용
ALLOW_WRITE_VALUE = {SRC / "field" / "servers" / "servers.py"}


def test_no_modbus_write_calls():
    hits = [
        f"{p.relative_to(ROOT)}:{i}"
        for p in SRC.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if FORBIDDEN.search(line)
    ]
    assert hits == []


def test_opcua_write_only_in_field_simulator():
    hits = [p for p in SRC.rglob("*.py") if "write_value(" in p.read_text(encoding="utf-8")]
    assert set(hits) <= ALLOW_WRITE_VALUE


def test_edge_and_plc_only_build_read_requests():
    # 요청 프레임은 read_pdu/rtu_read_request로만 만든다 (FC 03/04)
    for sub in ("edge", "plc"):
        for p in (SRC / sub).rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            assert "FC 05" not in text and not re.search(r"read_pdu\(\s*(5|6|15|16)\b", text), p
