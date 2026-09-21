"""Edge Collector 트윈 (Mini PC T1 X300): 수집 → 정규화 → 필터 → 버퍼 → MES 전송 (spec 5장)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

import httpx

from twin.common.config import TwinConfig
from twin.common.util import get_logger, iso, now_kst
from twin.edge.collectors import DirectDriver, PlcReader, make_driver
from twin.edge.core import Buffer, NoiseFilter, Sample, to_raw_items
from twin.field.faults import FaultManager

log = get_logger("edge")

PRIORITY_URGENT = 0
PRIORITY_NORMAL = 1


class MesLinkDown(Exception):
    """Edge–MES 회선 장애 (고장 주입 mes_link_down)."""


class EdgeCollector:
    """Edge 전체. 설비로 쓰기 명령을 만드는 경로는 없다 (EDG-11)."""

    def __init__(self, cfg: TwinConfig, faults: FaultManager) -> None:
        self.cfg = cfg
        self.ecfg = cfg.runtime.edge
        self.faults = faults
        self.buffer = Buffer(Path(cfg.runtime.data_dir) / "edge_buffer.db", self.ecfg.id)
        self.filter = NoiseFilter()
        self.readers = {pid: PlcReader(pid, cfg, self._on_sample) for pid in cfg.plcs}
        self.drivers: dict[str, DirectDriver] = {
            e.code: make_driver(e, cfg, self._on_sample) for e in cfg.equipment if e.kind.startswith("edge_")
        }
        self.mes_url = f"http://{cfg.runtime.host}:{cfg.port('mes_http')}/api/if/sensor-raw"
        self.link_ok: bool | None = None
        self.last_send_ok: str | None = None
        self.last_error: str | None = None
        self.samples_in = 0
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._md_ng: dict[str, float] = {}
        self.started_at = time.monotonic()

    # ── 수집 콜백 ──
    def _on_sample(self, s: Sample) -> None:
        self.samples_in += 1
        s = self.filter.apply(s)
        if not s.values:
            return
        prio = self._priority(s)
        items = to_raw_items(s)
        self.buffer.enqueue(items, prio, buffered=self.link_ok is False)
        if prio == PRIORITY_URGENT:
            self._wake.set()

    def _priority(self, s: Sample) -> int:
        """금속검출 NG 증가 샘플은 대기열보다 먼저 보낸다 (EDG-10)."""
        if "ng_cnt" in s.values:
            prev = self._md_ng.get(s.equip.code)
            self._md_ng[s.equip.code] = s.values["ng_cnt"]
            if prev is not None and s.values["ng_cnt"] > prev:
                return PRIORITY_URGENT
        return PRIORITY_NORMAL

    # ── 전송 ──
    async def _sender(self) -> None:
        backoff = 1.0
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                batch = self.buffer.next_batch(self.ecfg.batch_max)
                if not batch:
                    self._wake.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._wake.wait(), self.ecfg.send_interval_ms / 1000)
                    continue
                items: list[dict[str, Any]] = []
                resent = 0
                for _rid, att, buffered, its in batch:
                    flag = "Y" if (att > 0 or buffered) else "N"
                    for it in its:
                        it["resend_yn"] = flag
                    resent += len(its) if flag == "Y" else 0
                    items.extend(its)
                try:
                    if self.faults.has("mes_link_down", "EDGE-MES"):
                        raise MesLinkDown("회선 장애 주입")
                    r = await client.post(self.mes_url, json={"edge_id": self.ecfg.id, "items": items})
                    r.raise_for_status()
                    accepted = set(r.json()["accepted"])
                    if not all(it["msg_id"] in accepted for it in items):
                        raise RuntimeError("MES가 일부 항목을 받지 않음")
                except Exception as exc:
                    if self.link_ok is not False:
                        log.warning("mes_link_down", equip="EDGE-MES", error=repr(exc))
                    self.link_ok = False
                    self.last_error = repr(exc)
                    self.buffer.mark_failed_all()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self.ecfg.backoff_max_s)
                    continue
                if self.link_ok is False:
                    log.info("mes_link_up", equip="EDGE-MES")
                self.link_ok = True
                self.last_send_ok = iso(now_kst())
                backoff = 1.0
                self.buffer.ack([b[0] for b in batch], len(items), resent)

    async def _purger(self) -> None:
        while True:
            n = self.buffer.purge(self.ecfg.retention_hours)
            if n:
                log.warning("buffer_purged", equip="EDGE", items=n)
            await asyncio.sleep(60)

    # ── 기동/정지 ──
    async def start(self) -> None:
        self._tasks = [asyncio.create_task(r.run()) for r in self.readers.values()]
        self._tasks += [asyncio.create_task(d.run()) for d in self.drivers.values()]
        self._tasks += [asyncio.create_task(self._sender()), asyncio.create_task(self._purger())]
        log.info("edge_started", equip="EDGE", readers=len(self.readers), drivers=len(self.drivers))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        for r in self.readers.values():
            await r.link.close()
        for d in self.drivers.values():
            await d.close()
        self.buffer.close()

    # ── 조회 ──
    def device_state(self, code: str) -> str:
        if code in self.drivers:
            return self.drivers[code].state()
        for r in self.readers.values():
            if code in r.dev:
                return r.device_state(code)
        return "INACTIVE"

    def latest_values(self, code: str) -> dict[str, float]:
        if code in self.drivers:
            return self.drivers[code].values
        for r in self.readers.values():
            if code in r.dev:
                vals: dict[str, float] = r.dev[code]["values"]
                return vals
        return {}

    def mes_link_state(self) -> str:
        return {True: "OK", False: "DOWN", None: "UNKNOWN"}[self.link_ok]

    def status(self) -> dict[str, Any]:
        return {
            "id": self.ecfg.id,
            "mes_link": self.mes_link_state(),
            "last_send_ok": self.last_send_ok,
            "last_error": self.last_error,
            "samples_in": self.samples_in,
            "filtered": dict(self.filter.filtered),
            "filtered_recent": list(self.filter.recent[-20:]),
            "buffer": self.buffer.stats(),
            "plcs": {
                pid: {
                    "state": r.plc_state(),
                    "slave_link": r.slave_link_state(),
                    "diag_words": r.diag_words,
                    "link": r.link_diag.summary(),
                }
                for pid, r in self.readers.items()
            },
        }
