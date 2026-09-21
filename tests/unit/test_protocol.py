"""Modbus 프레임·값 인코딩·저울 전문 파싱."""

from __future__ import annotations

import pytest

from twin.common.modbus import (
    CrcErr,
    ExceptionResponse,
    FrameErr,
    crc16,
    crc_ok,
    decode_value,
    encode_value,
    exception_pdu,
    parse_words_pdu,
    rtu_read_request,
    with_crc,
    words_pdu,
)
from twin.edge.collectors import parse_scale_line


def test_crc16_known_vector() -> None:
    # Modbus 표준 예: 01 03 00 00 00 0A → CRC C5 CD
    assert rtu_read_request(1, 3, 0, 10).hex(" ").upper() == "01 03 00 00 00 0A C5 CD"
    assert crc16(b"") == 0xFFFF


def test_crc_ok_detects_corruption() -> None:
    frame = with_crc(bytes([7]) + words_pdu(4, [253, 862]))
    assert crc_ok(frame)
    assert not crc_ok(frame[:-1] + bytes([frame[-1] ^ 0xFF]))
    assert issubclass(CrcErr, Exception)


@pytest.mark.parametrize(
    ("value", "typ", "scale", "words"),
    [
        (12.34, "uint16", 0.01, [1234]),
        (-21.5, "int16", 0.1, [0xFF29]),
        (70000, "uint32", 1, [1, 4464]),
        (0.0, "uint16", 1, [0]),
    ],
)
def test_encode_decode_roundtrip(value: float, typ: str, scale: float, words: list[int]) -> None:
    assert encode_value(value, typ, scale) == words
    assert decode_value(words, typ, scale) == pytest.approx(value)


def test_encode_clamps() -> None:
    assert encode_value(-5, "uint16", 1) == [0]
    assert encode_value(99999, "int16", 1) == [32767]


def test_parse_words_and_exceptions() -> None:
    assert parse_words_pdu(words_pdu(3, [1, 2, 3]), 3, 3) == [1, 2, 3]
    with pytest.raises(ExceptionResponse) as ei:
        parse_words_pdu(exception_pdu(3, 2), 3, 1)
    assert ei.value.code == 2
    with pytest.raises(FrameErr):
        parse_words_pdu(words_pdu(3, [1]), 3, 2)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ST,GS,+0010.250kg", ("ST", 10.25)),
        ("US,NT,-0000.100kg", ("US", -0.1)),
        ("S?,G#,+00", None),
        ("ST,GS,abc", None),
        ("", None),
    ],
)
def test_scale_line(line: str, expected: tuple[str, float] | None) -> None:
    assert parse_scale_line(line) == expected
