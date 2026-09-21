"""통신 링크 클라이언트: RS-485(RTU) 링크 추상화와 Modbus TCP 클라이언트.

설정의 endpoint가 'tcp://host:port'이거나 link 포트면 TcpRtuLink(sim), '/dev/...'면 SerialPortLink(실장비).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import time
from typing import Protocol

from twin.common.modbus import (
    CrcErr,
    FrameErr,
    ModbusError,
    TimeoutErr,
    crc_ok,
    mbap,
    parse_words_pdu,
    read_mbap,
    read_pdu,
    read_rtu_frame,
    rtu_read_request,
)


class ReadResult:
    """읽기 1회 결과 (재시도 전 한 요청)."""

    __slots__ = ("words", "tx", "rx", "rtt_ms")

    def __init__(self, words: list[int], tx: bytes, rx: bytes, rtt_ms: float) -> None:
        self.words, self.tx, self.rx, self.rtt_ms = words, tx, rx, rtt_ms


class ReadLink(Protocol):
    async def read(self, unit: int, fc: int, addr: int, count: int, timeout: float) -> ReadResult: ...

    async def close(self) -> None: ...


class _StreamLink:
    """TCP 스트림 공통: 필요할 때 연결하고, 오류가 나면 끊어서 늦은 응답이 섞이지 않게 한다."""

    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()  # 반이중: 링크당 요청 1개
        self.last_tx = b""
        self.last_rx = b""

    async def _ensure(self, timeout: float) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._r is None or self._w is None or self._w.is_closing():
            try:
                self._r, self._w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout)
            except (TimeoutError, OSError) as exc:
                raise TimeoutErr(f"연결 실패 {self.host}:{self.port}") from exc
        return self._r, self._w

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
            with contextlib.suppress(Exception):
                await self._w.wait_closed()
        self._r = self._w = None


class TcpRtuLink(_StreamLink):
    """RTU 프레임을 그대로 싣는 TCP 링크 (socat 없는 환경의 가상 RS-485, D-003)."""

    async def read(self, unit: int, fc: int, addr: int, count: int, timeout: float) -> ReadResult:
        async with self._lock:
            req = rtu_read_request(unit, fc, addr, count)
            self.last_tx, self.last_rx = req, b""
            t0 = time.monotonic()
            r, w = await self._ensure(timeout)
            try:
                w.write(req)
                await w.drain()
                resp = await asyncio.wait_for(read_rtu_frame(r, request=False), timeout)
            except (TimeoutError, asyncio.IncompleteReadError, ConnectionError) as exc:
                await self.close()
                raise TimeoutErr("응답 없음") from exc
            self.last_rx = resp
            rtt = (time.monotonic() - t0) * 1000
            if not crc_ok(resp):
                await self.close()
                raise CrcErr(f"CRC 불일치 {resp.hex()}")
            if resp[0] != unit:
                await self.close()
                raise FrameErr(f"slave 주소 불일치 {resp[0]} != {unit}")
            return ReadResult(parse_words_pdu(resp[1:-2], fc, count), req, resp, rtt)


class ModbusTcpLink(_StreamLink):
    """Modbus TCP(MBAP) 읽기 클라이언트."""

    _tids = itertools.count(1)

    async def read(self, unit: int, fc: int, addr: int, count: int, timeout: float) -> ReadResult:
        async with self._lock:
            tid = next(self._tids) & 0xFFFF
            req = mbap(tid, unit, read_pdu(fc, addr, count))
            self.last_tx, self.last_rx = req, b""
            t0 = time.monotonic()
            r, w = await self._ensure(timeout)
            try:
                w.write(req)
                await w.drain()
                rtid, _unit, pdu = await asyncio.wait_for(read_mbap(r), timeout)
            except (TimeoutError, asyncio.IncompleteReadError, ConnectionError) as exc:
                await self.close()
                raise TimeoutErr("응답 없음") from exc
            except FrameErr:
                await self.close()
                raise
            rtt = (time.monotonic() - t0) * 1000
            self.last_rx = pdu
            if rtid != tid:
                await self.close()
                raise FrameErr(f"트랜잭션 ID 불일치 {rtid} != {tid}")
            try:
                words = parse_words_pdu(pdu, fc, count)
            except FrameErr:
                await self.close()
                raise
            return ReadResult(words, req, pdu, rtt)


class SerialPortLink:
    """실장비용 직렬 포트 링크 (pyserial-asyncio). hybrid/live 모드에서 쓴다."""

    def __init__(self, path: str, baud: int) -> None:
        self.path, self.baud = path, baud
        self._inner: TcpRtuLink | None = None
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def read(self, unit: int, fc: int, addr: int, count: int, timeout: float) -> ReadResult:
        import serial_asyncio  # 실장비에서만 필요

        async with self._lock:
            if self._w is None:
                self._r, self._w = await serial_asyncio.open_serial_connection(url=self.path, baudrate=self.baud)
            assert self._r is not None
            req = rtu_read_request(unit, fc, addr, count)
            t0 = time.monotonic()
            self._w.write(req)
            try:
                resp = await asyncio.wait_for(read_rtu_frame(self._r, request=False), timeout)
            except TimeoutError as exc:
                raise TimeoutErr("응답 없음") from exc
            if not crc_ok(resp):
                raise CrcErr(resp.hex())
            return ReadResult(parse_words_pdu(resp[1:-2], fc, count), req, resp, (time.monotonic() - t0) * 1000)

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
        self._w = None


def make_rtu_link(host: str, port: int | None, endpoint: str | None, baud: int) -> ReadLink:
    """설정에 따라 가상/실장비 링크를 고른다."""
    if endpoint and endpoint.startswith("/dev/"):
        return SerialPortLink(endpoint, baud)
    if endpoint and endpoint.startswith("tcp://"):
        h, p = endpoint[6:].rsplit(":", 1)
        return TcpRtuLink(h, int(p))
    assert port is not None
    return TcpRtuLink(host, port)


__all__ = ["ModbusError", "ModbusTcpLink", "ReadLink", "ReadResult", "TcpRtuLink", "make_rtu_link"]
