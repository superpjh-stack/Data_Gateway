"""Edge 수집기: PLC D영역 리더와 직결 장비 드라이버(Modbus TCP, OPC-UA, RS-232 ASCII)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from twin.common.config import Equip, TwinConfig
from twin.common.modbus import ModbusError, decode_value
from twin.common.util import STATUS_DOWN, STATUS_NAMES, STATUS_OK, Diag, get_logger, now_kst
from twin.edge.core import Sample
from twin.plc.link import ModbusTcpLink

log = get_logger("edge")
Emit = Callable[[Sample], None]


class PlcReader:
    """PLC 한 대의 D영역을 블록 단위로 읽어, 갱신카운터가 바뀐 장비만 샘플로 만든다 (EDG-01, 05)."""

    def __init__(self, plc_id: str, cfg: TwinConfig, emit: Emit) -> None:
        self.id = plc_id
        self.cfg = cfg
        self.emit = emit
        self.link = ModbusTcpLink(cfg.runtime.host, cfg.port(f"plc_{plc_id}"))
        self.blocks = cfg.plc_map.blocks.get(plc_id, {})
        self.equips = {code: cfg.equip(code) for code in self.blocks}
        self.ranges = self._ranges()
        self.poll_s = cfg.runtime.edge.plc_poll_ms / 1000
        self.timeout = cfg.runtime.edge.plc_timeout_ms / 1000
        self.stale_factor = cfg.runtime.edge.stale_factor
        self.link_ok = False
        self.link_diag = Diag(delay_ms=200)
        self.heartbeat: int | None = None
        self.hb_changed = 0.0
        self.slave_mirror: int | None = None
        self.mirror_changed = 0.0
        self.diag_words: list[int] = []
        self.dev: dict[str, dict[str, Any]] = {
            c: {"counter": None, "changed": 0.0, "plc_status": STATUS_DOWN, "fails": 0, "values": {}}
            for c in self.blocks
        }

    def _ranges(self) -> list[tuple[int, int]]:
        bw = self.cfg.plc_map.block_words
        spans = sorted((b, b + bw) for b in self.blocks.values())
        spans.append((self.cfg.plc_map.diag_base, self.cfg.plc_map.diag_base + 6))
        merged: list[list[int]] = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] and b - merged[-1][0] <= 125:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return [(a, b - a) for a, b in merged]

    async def run(self) -> None:
        while True:
            t0 = time.monotonic()
            try:
                await self.poll()
            except Exception as exc:
                log.error("plc_reader_crash", equip=self.id, error=repr(exc))
            await asyncio.sleep(max(0.05, self.poll_s - (time.monotonic() - t0)))

    async def poll(self) -> None:
        mem: dict[int, int] = {}
        try:
            for addr, count in self.ranges:
                res = await self.link.read(1, 3, addr, count, self.timeout)
                self.link_diag.attempt(True, res.rtt_ms, None)
                for i, w in enumerate(res.words):
                    mem[addr + i] = w
            self.link_diag.poll(True)
            self.link_ok = True
        except ModbusError as exc:
            self.link_diag.attempt(False, None, exc.kind)
            self.link_diag.poll(False)
            self.link_ok = False
            return
        now = time.monotonic()
        d = self.cfg.plc_map.diag_base
        self.diag_words = [mem.get(d + i, 0) for i in range(6)]
        if self.heartbeat != mem.get(d):
            self.heartbeat, self.hb_changed = mem.get(d), now
        if self.id == "MASTER" and self.slave_mirror != mem.get(d + 2):
            self.slave_mirror, self.mirror_changed = mem.get(d + 2), now
        for code, base in self.blocks.items():
            self._update_device(code, base, mem, now)

    def _update_device(self, code: str, base: int, mem: dict[int, int], now: float) -> None:
        e = self.equips[code]
        st = self.dev[code]
        st["plc_status"], st["fails"] = mem[base], mem[base + 1]
        counter = mem[base + 8]
        if counter == 0 or counter == st["counter"]:
            return
        st["counter"], st["changed"] = counter, now
        words = [mem[base + 2 + i] for i in range(e.value_words)]
        values, tags, off = {}, {}, 0
        for it in e.items:
            values[it.key] = decode_value(words[off : off + it.words], it.type, it.scale)
            tags[it.key] = f"{self.id}.D{base + 2 + off:04d}"
            off += it.words
        st["values"] = values
        self.emit(Sample(e, now_kst(), values, tags))

    # ── 상태 ──
    def plc_state(self) -> str:
        """OK / DOWN — 읽기 실패 또는 하트비트 3 s 불변."""
        if not self.link_ok or time.monotonic() - self.hb_changed > 3.0:
            return "DOWN"
        return "OK"

    def slave_link_state(self) -> str | None:
        if self.id != "MASTER":
            return None
        if not self.link_ok:
            return "UNKNOWN"
        return "OK" if time.monotonic() - self.mirror_changed <= 3.0 else "DOWN"

    def device_state(self, code: str) -> str:
        """PLC가 판정한 상태 + Edge의 STALE 판정."""
        st = self.dev[code]
        e = self.equips[code]
        if self.plc_state() == "DOWN":
            return "STALE"
        stale_s = max(e.poll_ms / 1000, self.poll_s) * self.stale_factor + 1.0
        if (
            st["counter"] is not None
            and time.monotonic() - st["changed"] > stale_s
            and st["plc_status"] == STATUS_OK
        ):
            return "STALE"
        return STATUS_NAMES.get(st["plc_status"], "DOWN")


class DirectDriver:
    """Edge 직결 장비 공통: 주기 폴링, 진단, 샘플 발행."""

    def __init__(self, equip: Equip, cfg: TwinConfig, emit: Emit) -> None:
        self.equip = equip
        self.cfg = cfg
        self.emit = emit
        self.diag = Diag(delay_ms=equip.effective_delay_ms())
        self.host = cfg.runtime.host
        assert equip.via.link
        self.port = cfg.port(equip.via.link)
        self.values: dict[str, float] = {}

    async def run(self) -> None:
        period = self.equip.poll_ms / 1000
        while True:
            t0 = time.monotonic()
            try:
                await self.poll()
            except Exception as exc:
                log.error("driver_crash", equip=self.equip.code, error=repr(exc))
            await asyncio.sleep(max(0.05, period - (time.monotonic() - t0)))

    async def poll(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    def state(self) -> str:
        return STATUS_NAMES[self.diag.status()]

    def _emit(self, values: dict[str, float], tags: dict[str, str]) -> None:
        self.values = values
        self.emit(Sample(self.equip, now_kst(), values, tags))


class ModbusTcpDriver(DirectDriver):
    """충진기·속넣기기계 (Modbus TCP) [가정]."""

    def __init__(self, equip: Equip, cfg: TwinConfig, emit: Emit) -> None:
        super().__init__(equip, cfg, emit)
        self.link = ModbusTcpLink(self.host, self.port)

    async def poll(self) -> None:
        by_fc: dict[int, tuple[int, int]] = {}
        for it in self.equip.items:
            a, b = by_fc.get(it.fc, (it.address, it.address + it.words))
            by_fc[it.fc] = (min(a, it.address), max(b, it.address + it.words))
        words: dict[tuple[int, int], int] = {}
        for fc, (a, b) in by_fc.items():
            res = None
            for _ in range(2):
                try:
                    res = await self.link.read(self.equip.via.unit, fc, a, b - a, 0.5)
                    self.diag.attempt(True, res.rtt_ms, None)
                    self.diag.add_frame(res.tx, res.rx, "OK", round(res.rtt_ms, 1))
                    break
                except ModbusError as exc:
                    self.diag.attempt(False, None, exc.kind)
                    self.diag.add_frame(
                        self.link.last_tx, self.link.last_rx or "(응답 없음)", exc.kind.upper(), None
                    )
            if res is None:
                self.diag.poll(False)
                return
            for i, w in enumerate(res.words):
                words[(fc, a + i)] = w
        self.diag.poll(True)
        values, tags = {}, {}
        for it in self.equip.items:
            ws = [words[(it.fc, it.address + i)] for i in range(it.words)]
            values[it.key] = decode_value(ws, it.type, it.scale)
            tags[it.key] = f"{self.equip.code}.{it.reg}"
        self._emit(values, tags)

    async def close(self) -> None:
        await self.link.close()


class AsciiScaleDriver(DirectDriver):
    """중량 저울 (RS-232 ASCII 요청/응답) [가정]. 안정(ST) 값만 채택."""

    def __init__(self, equip: Equip, cfg: TwinConfig, emit: Emit) -> None:
        super().__init__(equip, cfg, emit)
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None
        self.unstable = 0

    async def _conn(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._w is None or self._w.is_closing():
            self._r, self._w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 1.0)
        assert self._r is not None and self._w is not None
        return self._r, self._w

    async def poll(self) -> None:
        t0 = time.monotonic()
        line = b""
        try:
            r, w = await self._conn()
            w.write(b"Q\r\n")
            await w.drain()
            line = await asyncio.wait_for(r.readline(), 0.5)
            if not line:
                raise ConnectionError("closed")
        except (TimeoutError, OSError, ConnectionError):
            await self.close()
            self.diag.attempt(False, None, "timeout")
            self.diag.add_frame("Q\\r\\n", "(응답 없음)", "TIMEOUT", None)
            self.diag.poll(False)
            return
        rtt = (time.monotonic() - t0) * 1000
        text = line.decode("ascii", "replace").strip()
        parsed = parse_scale_line(text)
        if parsed is None:
            self.diag.attempt(False, None, "frame")
            self.diag.add_frame("Q\\r\\n", text, "FRAME", round(rtt, 1))
            self.diag.poll(False)
            return
        state, weight = parsed
        self.diag.attempt(True, rtt, None)
        self.diag.add_frame("Q\\r\\n", text, "OK" if state == "ST" else "UNSTABLE", round(rtt, 1))
        self.diag.poll(True)
        if state != "ST":
            self.unstable += 1
            return
        self._emit({"weight": weight}, {"weight": f"SERIAL.{self.equip.code}"})

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
        self._w = None


def parse_scale_line(text: str) -> tuple[str, float] | None:
    """'ST,GS,+0010.250kg' → ('ST', 10.25). 형식이 틀리면 None."""
    parts = text.split(",")
    if len(parts) != 3 or parts[0] not in ("ST", "US", "OL") or parts[1] not in ("GS", "NT"):
        return None
    num = parts[2].removesuffix("kg")
    try:
        return parts[0], float(num)
    except ValueError:
        return None


class OpcUaDriver(DirectDriver):
    """아이스박스자동포장기 KF 100 (OPC-UA). 구독으로 변화를 받고 poll_ms마다 전체 값을 읽는다."""

    def __init__(self, equip: Equip, cfg: TwinConfig, emit: Emit) -> None:
        super().__init__(equip, cfg, emit)
        self.url = f"opc.tcp://{self.host}:{self.port}/"
        self.client: Any = None
        self.nodes: dict[str, Any] = {}
        self.sub: Any = None
        self._changed = asyncio.Event()
        for name in (
            "asyncua",
            "asyncua.client",
            "asyncua.common",
            "asyncua.client.ua_client",
            "asyncua.uaprotocol",
        ):
            logging.getLogger(name).setLevel(logging.CRITICAL)

    async def _connect(self) -> None:
        from asyncua.client.client import Client

        client = Client(self.url, timeout=2)
        await asyncio.wait_for(client.connect(), 3)
        self.client = client
        self.nodes = {it.key: client.get_node(it.node) for it in self.equip.items if it.node}
        handler = _SubHandler(self._changed)
        self.sub = await client.create_subscription(200, handler)
        await self.sub.subscribe_data_change([self.nodes["pack_count"], self.nodes["running"]])

    async def run(self) -> None:
        period = self.equip.poll_ms / 1000
        while True:
            if self.client is None:
                try:
                    await self._connect()
                except Exception:
                    self.diag.attempt(False, None, "timeout")
                    self.diag.add_frame("CONNECT " + self.url, "(연결 실패)", "TIMEOUT", None)
                    self.diag.poll(False)
                    await self.close()
                    await asyncio.sleep(2.0)
                    continue
            try:
                await self.poll()
            except Exception:
                self.diag.attempt(False, None, "timeout")
                self.diag.poll(False)
                await self.close()
                continue
            self._changed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), period)

    async def poll(self) -> None:
        t0 = time.monotonic()
        values = {}
        for it in self.equip.items:
            v = await asyncio.wait_for(self.nodes[it.key].read_value(), 1.5)
            values[it.key] = float(v)
        rtt = (time.monotonic() - t0) * 1000
        self.diag.attempt(True, rtt, None)
        self.diag.add_frame(
            "Read " + ",".join(it.node or "" for it in self.equip.items),
            ", ".join(f"{k}={v:g}" for k, v in values.items()),
            "OK",
            round(rtt, 1),
        )
        self.diag.poll(True)
        self._emit(values, {it.key: f"OPCUA.{it.node}" for it in self.equip.items})

    async def close(self) -> None:
        if self.client is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.client.disconnect(), 1)
        self.client = None


class _SubHandler:
    def __init__(self, ev: asyncio.Event) -> None:
        self.ev = ev

    def datachange_notification(self, node: Any, val: Any, data: Any) -> None:
        self.ev.set()


def make_driver(e: Equip, cfg: TwinConfig, emit: Emit) -> DirectDriver:
    kinds: dict[str, type[DirectDriver]] = {
        "edge_modbus_tcp": ModbusTcpDriver,
        "edge_ascii": AsciiScaleDriver,
        "edge_opcua": OpcUaDriver,
    }
    return kinds[e.kind](e, cfg, emit)
