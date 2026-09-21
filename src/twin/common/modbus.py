"""Modbus RTU / TCP 최소 구현 (D-002). FC 03·04 읽기와 예외 응답만 다룬다."""

from __future__ import annotations

import asyncio
import struct

READ_FCS = (3, 4)
EXC_ILLEGAL_FUNCTION = 1
EXC_ILLEGAL_ADDRESS = 2


class ModbusError(Exception):
    """통신 오류의 공통 부모. kind는 진단 분류명이다."""

    kind = "error"


class TimeoutErr(ModbusError):
    kind = "timeout"


class CrcErr(ModbusError):
    kind = "crc"


class FrameErr(ModbusError):
    kind = "frame"


class ExceptionResponse(ModbusError):
    kind = "exception"

    def __init__(self, code: int) -> None:
        super().__init__(f"Modbus 예외 응답 {code:#04x}")
        self.code = code


def crc16(data: bytes) -> int:
    """Modbus CRC16 (다항식 0xA001)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    return frame + struct.pack("<H", crc16(frame))


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and struct.unpack("<H", frame[-2:])[0] == crc16(frame[:-2])


def read_pdu(fc: int, addr: int, count: int) -> bytes:
    return struct.pack(">BHH", fc, addr, count)


def rtu_read_request(unit: int, fc: int, addr: int, count: int) -> bytes:
    return with_crc(bytes([unit]) + read_pdu(fc, addr, count))


def words_pdu(fc: int, words: list[int]) -> bytes:
    return struct.pack(f">BB{len(words)}H", fc, len(words) * 2, *[w & 0xFFFF for w in words])


def exception_pdu(fc: int, code: int) -> bytes:
    return bytes([fc | 0x80, code])


def parse_words_pdu(pdu: bytes, fc: int, count: int) -> list[int]:
    """응답 PDU(기능코드부터)를 워드 목록으로 바꾼다."""
    if not pdu:
        raise FrameErr("빈 PDU")
    if pdu[0] == fc | 0x80:
        raise ExceptionResponse(pdu[1] if len(pdu) > 1 else 0)
    if pdu[0] != fc or len(pdu) < 2 or pdu[1] != count * 2 or len(pdu) != 2 + count * 2:
        raise FrameErr(f"응답 형식 오류 {pdu.hex()}")
    return list(struct.unpack(f">{count}H", pdu[2:]))


async def read_rtu_frame(reader: asyncio.StreamReader, *, request: bool) -> bytes:
    """스트림에서 RTU 프레임 하나를 길이 규칙대로 읽는다(요청/응답 구분)."""
    head = await reader.readexactly(2)
    fc = head[1]
    if request:
        if fc in (1, 2, 3, 4, 5, 6):
            rest = await reader.readexactly(6)
        elif fc in (15, 16):
            mid = await reader.readexactly(5)
            rest = mid + await reader.readexactly(mid[4] + 2)
        else:
            raise FrameErr(f"지원하지 않는 기능코드 {fc}")
    elif fc & 0x80:
        rest = await reader.readexactly(3)
    else:
        n = await reader.readexactly(1)
        rest = n + await reader.readexactly(n[0] + 2)
    return head + rest


def mbap(tid: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", tid & 0xFFFF, 0, len(pdu) + 1, unit) + pdu


async def read_mbap(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    """MBAP 프레임 하나를 읽어 (tid, unit, pdu)를 돌려준다."""
    head = await reader.readexactly(7)
    tid, pid, length, unit = struct.unpack(">HHHB", head)
    if pid != 0 or length < 2 or length > 260:
        raise FrameErr(f"MBAP 헤더 오류 {head.hex()}")
    pdu = await reader.readexactly(length - 1)
    return tid, unit, pdu


def encode_value(value: float, typ: str, scale: float) -> list[int]:
    """공학값을 레지스터 워드로 바꾼다 (uint32는 상위 워드 먼저)."""
    raw = int(round(value / scale)) if scale else int(value)
    if typ == "int16":
        raw = max(-32768, min(32767, raw))
        return [raw & 0xFFFF]
    if typ == "uint16":
        return [max(0, min(0xFFFF, raw))]
    if typ == "uint32":
        raw = max(0, min(0xFFFFFFFF, raw))
        return [(raw >> 16) & 0xFFFF, raw & 0xFFFF]
    raise ValueError(f"레지스터로 표현할 수 없는 형식 {typ}")


def decode_value(words: list[int], typ: str, scale: float) -> float:
    """레지스터 워드를 공학값으로 바꾼다."""
    if typ == "int16":
        raw = words[0] - 0x10000 if words[0] & 0x8000 else words[0]
    elif typ == "uint16":
        raw = words[0]
    elif typ == "uint32":
        raw = (words[0] << 16) | words[1]
    else:
        raise ValueError(f"레지스터로 표현할 수 없는 형식 {typ}")
    return round(raw * scale, 6)
