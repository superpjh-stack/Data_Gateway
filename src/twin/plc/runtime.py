"""PLC 트윈 (LS산전 XBC-DN32H Master/Slave): 버스 스캔 → D영역 기록 → Modbus TCP로 공개.

제어 로직은 없다. 외부 Write 요청은 거부하고 기록한다 (spec PLC-07, AC-12).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any

from twin.common.config import Equip, TwinConfig
from twin.common.modbus import (
    EXC_ILLEGAL_ADDRESS,
    EXC_ILLEGAL_FUNCTION,
    READ_FCS,
    ModbusError,
    exception_pdu,
    mbap,
    read_mbap,
    words_pdu,
)
from twin.common.util import STATUS_DOWN, STATUS_OK, Diag, get_logger, iso, now_kst
from twin.field.faults import FaultManager
from twin.plc.link import ModbusTcpLink, ReadLink, make_rtu_link

log = get_logger("plc")

MEM_WORDS = 2000
FC_NAMES = {5: "Write Single Coil", 6: "Write Single Register", 15: "Write Multiple Coils",
            16: "Write Multiple Registers"}


class PlcMemory:
    """D영역 워드 메모리."""

    def __init__(self, size: int = MEM_WORDS) -> None:
        self.words = [0] * size
        self.changed_at = [0.0] * size

    def write(self, addr: int, values: list[int]) -> None:
        now = time.monotonic()
        for i, v in enumerate(values):
            v &= 0xFFFF
            if self.words[addr + i] != v:
                self.words[addr + i] = v
                self.changed_at[addr + i] = now

    def read(self, addr: int, count: int) -> list[int]:
        return self.words[addr : addr + count]


@dataclass
class Point:
    """스캔 대상 장비 1대."""

    equip: Equip
    base: int
    link: ReadLink
    unit: int
    timeout: float
    retries: int
    diag: Diag
    next_due: float = 0.0


def _read_groups(e: Equip) -> list[tuple[int, int, int]]:
    """(fc, 시작주소, 워드수) — 같은 FC는 한 번에 읽는다."""
    groups: dict[int, tuple[int, int]] = {}
    for it in e.items:
        lo, hi = it.address, it.address + it.words
        if it.fc in groups:
            a, b = groups[it.fc]
            groups[it.fc] = (min(a, lo), max(b, hi))
        else:
            groups[it.fc] = (lo, hi)
    return [(fc, a, b - a) for fc, (a, b) in sorted(groups.items())]


def _pack_values(e: Equip, reads: dict[int, tuple[int, list[int]]]) -> list[int]:
    """설정 순서대로 값 워드를 모은다 (블록 +2부터)."""
    out: list[int] = []
    for it in e.items:
        start, words = reads[it.fc]
        off = it.address - start
        out.extend(words[off : off + it.words])
    return out


class BusScanner:
    """버스(또는 Ethernet 장비 묶음) 하나를 순차 폴링한다."""

    def __init__(self, name: str, points: list[Point], memory: PlcMemory) -> None:
        self.name = name
        self.points = points
        self.memory = memory
        self.last_scan_ms = 0.0

    async def run(self) -> None:
        while True:
            now = time.monotonic()
            due = [p for p in self.points if p.next_due <= now]
            t0 = time.monotonic()
            for p in due:
                p.next_due = max(p.next_due + p.equip.poll_ms / 1000, time.monotonic())
                try:
                    await self.poll(p)
                except Exception as exc:  # 한 장비 오류가 버스 전체를 멈추지 않게
                    log.error("poll_crash", equip=p.equip.code, error=repr(exc))
            if due:
                self.last_scan_ms = (time.monotonic() - t0) * 1000
            nxt = min((p.next_due for p in self.points), default=now + 1)
            await asyncio.sleep(max(0.01, min(0.2, nxt - time.monotonic())))

    async def poll(self, p: Point) -> None:
        reads: dict[int, tuple[int, list[int]]] = {}
        for fc, addr, count in _read_groups(p.equip):
            res = None
            for _attempt in range(1 + p.retries):
                try:
                    res = await p.link.read(p.unit, fc, addr, count, p.timeout)
                    p.diag.attempt(True, res.rtt_ms, None)
                    p.diag.add_frame(res.tx, res.rx, "OK", round(res.rtt_ms, 1))
                    break
                except ModbusError as exc:
                    p.diag.attempt(False, None, exc.kind)
                    tx = getattr(p.link, "last_tx", b"")
                    rx = getattr(p.link, "last_rx", b"")
                    p.diag.add_frame(tx, rx or "(응답 없음)", exc.kind.upper(), None)
            if res is None:
                p.diag.poll(False)
                self._write_status(p)
                return
            reads[fc] = (addr, res.words)
        p.diag.poll(True)
        values = _pack_values(p.equip, reads)
        self.memory.write(p.base + 2, values)
        self._write_status(p)
        self.memory.write(p.base + 8, [p.diag.counter])

    def _write_status(self, p: Point) -> None:
        self.memory.write(p.base, [p.diag.status(), min(p.diag.consecutive_fail, 0xFFFF)])


class PlcRuntime:
    """PLC 한 대: 스캐너들, D영역, Modbus TCP 서버, 하트비트, (Master) Slave 미러."""

    def __init__(self, plc_id: str, cfg: TwinConfig, faults: FaultManager) -> None:
        self.id = plc_id
        self.cfg = cfg
        self.faults = faults
        self.memory = PlcMemory()
        self.diag_base = cfg.plc_map.diag_base
        self.port = cfg.port(f"plc_{plc_id}")
        self.host = cfg.runtime.host
        self.scanners: list[BusScanner] = []
        self.points: dict[str, Point] = {}
        self.bus_of: dict[str, str] = {}
        self.write_rejections: list[dict[str, Any]] = []
        self._server: asyncio.base_events.Server | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._conns: set[asyncio.StreamWriter] = set()
        self.running = False
        self.slave_link_ok = False
        self._last_slave_hb: int | None = None
        self._slave_hb_changed = 0.0
        self._build()

    def _build(self) -> None:
        cfg, blocks = self.cfg, self.cfg.plc_map.blocks.get(self.id, {})
        host = cfg.runtime.host
        for bid, bus in cfg.buses.items():
            if bus.plc != self.id:
                continue
            link = make_rtu_link(host, cfg.runtime.ports.get(bus.link), bus.endpoint, bus.baud)
            pts = []
            for e in cfg.equipment:
                if e.via.bus == bid:
                    assert e.via.slave is not None
                    p = Point(e, blocks[e.code], link, e.via.slave, bus.timeout_ms / 1000, bus.retries,
                              Diag(delay_ms=e.effective_delay_ms()))
                    pts.append(p)
                    self.points[e.code] = p
                    self.bus_of[e.code] = bid
            self.scanners.append(BusScanner(bid, pts, self.memory))
        eth = []
        for e in cfg.equipment:
            if e.kind == "plc_tcp" and e.via.plc_tcp == self.id:
                assert e.via.link
                link2 = ModbusTcpLink(host, cfg.port(e.via.link))
                p = Point(e, blocks[e.code], link2, e.via.unit, 0.5, 1, Diag(delay_ms=e.effective_delay_ms()))
                eth.append(p)
                self.points[e.code] = p
                self.bus_of[e.code] = "ETH"
        if eth:
            self.scanners.append(BusScanner("ETH", eth, self.memory))

    # ── 기동/정지 ──
    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_conn, self.host, self.port, reuse_address=True)
        self._tasks = [asyncio.create_task(s.run()) for s in self.scanners]
        self._tasks.append(asyncio.create_task(self._heartbeat()))
        if self.id == "MASTER" and "SLAVE" in self.cfg.plcs:
            self._tasks.append(asyncio.create_task(self._slave_mirror()))
        self.running = True
        log.info("plc_started", equip=self.id, port=self.port, points=len(self.points))

    async def stop(self) -> None:
        self.running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        if self._server is not None:
            self._server.close()
            for w in list(self._conns):
                w.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)
            self._server = None
        for p in self.points.values():
            await p.link.close()
        log.warning("plc_stopped", equip=self.id)

    # ── 진단 영역 ──
    async def _heartbeat(self) -> None:
        d = self.diag_base
        hb = self.memory.read(d, 1)[0]
        while True:
            hb = (hb + 1) & 0xFFFF
            bits = 0
            for i, s in enumerate(self.scanners[:3]):
                if any(p.diag.status() != STATUS_OK for p in s.points):
                    bits |= 1 << i
            ok = sum(1 for p in self.points.values() if p.diag.status() == STATUS_OK)
            scan = int(max((s.last_scan_ms for s in self.scanners), default=0))
            self.memory.write(d, [hb, bits])
            self.memory.write(d + 3, [min(scan, 0xFFFF), ok])
            await asyncio.sleep(1.0)

    async def _slave_mirror(self) -> None:
        """Master가 Slave 하트비트(D0900)를 1 s마다 읽어 D0902에 미러링한다."""
        link = ModbusTcpLink(self.host, self.cfg.port("plc_SLAVE"))
        d = self.diag_base
        while True:
            ok = False
            if not self.faults.has("master_slave_link_down", "MASTER-SLAVE"):
                try:
                    res = await link.read(1, 3, d, 1, 0.5)
                    self.memory.write(d + 2, res.words)
                    ok = True
                except ModbusError:
                    await link.close()
            self.slave_link_ok = ok
            self.memory.write(d + 5, [STATUS_OK if ok else STATUS_DOWN])
            await asyncio.sleep(1.0)

    # ── Modbus TCP 서버 (FC03/04만) ──
    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._conns.add(writer)
        peer = writer.get_extra_info("peername")
        try:
            while True:
                tid, unit, pdu = await read_mbap(reader)
                writer.write(mbap(tid, unit, self._handle(pdu, peer)))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ModbusError, asyncio.CancelledError):
            pass
        finally:
            self._conns.discard(writer)
            writer.close()

    def _handle(self, pdu: bytes, peer: Any) -> bytes:
        fc = pdu[0]
        if fc not in READ_FCS:
            rec = {"ts": iso(now_kst()), "fc": fc, "name": FC_NAMES.get(fc, "?"), "peer": str(peer),
                   "pdu": pdu.hex(" ").upper()}
            self.write_rejections.append(rec)
            log.warning("write_rejected", equip=self.id, fc=fc, peer=str(peer))
            return exception_pdu(fc, EXC_ILLEGAL_FUNCTION)
        if len(pdu) != 5:
            return exception_pdu(fc, EXC_ILLEGAL_FUNCTION)
        addr, count = int.from_bytes(pdu[1:3], "big"), int.from_bytes(pdu[3:5], "big")
        if count < 1 or count > 125 or addr + count > MEM_WORDS:
            return exception_pdu(fc, EXC_ILLEGAL_ADDRESS)
        return words_pdu(fc, self.memory.read(addr, count))

    # ── 조회 ──
    def diag_snapshot(self) -> dict[str, Any]:
        d = self.diag_base
        return {
            "id": self.id,
            "running": self.running,
            "heartbeat": self.memory.words[d],
            "bus_bits": self.memory.words[d + 1],
            "slave_hb_mirror": self.memory.words[d + 2] if self.id == "MASTER" else None,
            "scan_ms": self.memory.words[d + 3],
            "ok_count": self.memory.words[d + 4],
            "slave_link": ("OK" if self.slave_link_ok else "DOWN") if self.id == "MASTER" else None,
            "write_rejections": len(self.write_rejections),
        }
