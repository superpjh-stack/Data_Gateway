"""WebSocket 허브: 값 메시지는 장비별로 합쳐서(초당 5건 이하), 나머지는 즉시 내보낸다."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from twin.common.util import get_logger, iso, now_kst

if TYPE_CHECKING:
    from twin.supervisor import Twin

log = get_logger("api")


class WsHub:
    def __init__(self, flush_s: float) -> None:
        self.flush_s = flush_s
        self.clients: set[WebSocket] = set()
        self._pending_values: dict[str, dict[str, Any]] = {}
        self._queue: list[dict[str, Any]] = []
        self._mem_prev: dict[str, list[int]] = {}
        self._status_prev: dict[str, str] = {}
        self.sent = 0

    def publish(self, msg: dict[str, Any]) -> None:
        """이벤트 루프 안에서 호출된다. 값은 장비별 마지막 것만 남긴다."""
        if msg.get("type") == "value":
            code = msg["equip"]
            prev = self._pending_values.get(code)
            if prev is not None:
                msg = {**msg, "values": {**prev["values"], **msg["values"]}}
            self._pending_values[code] = msg
        else:
            self._queue.append(msg)

    async def add(self, ws: WebSocket, snapshot: dict[str, Any]) -> None:
        await ws.accept()
        self.clients.add(ws)
        await ws.send_text(json.dumps({"type": "snapshot", **snapshot}, ensure_ascii=False, default=str))

    def remove(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _send_all(self, msgs: list[dict[str, Any]]) -> None:
        if not msgs or not self.clients:
            return
        payload = json.dumps(msgs if len(msgs) > 1 else msgs[0], ensure_ascii=False, default=str)
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(payload), 2)
                self.sent += 1
            except Exception:
                self.clients.discard(ws)

    async def run(self, twin: Twin) -> None:
        """flush_s마다 합친 값·이벤트를, 1 s마다 요약·토폴로지·버퍼·PLC 메모리 변화를 보낸다."""
        from twin.mes.views import summary, sync_comm_alarms, topology

        last_slow = 0.0
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(self.flush_s)
            try:
                msgs = self._queue + list(self._pending_values.values())
                self._queue, self._pending_values = [], {}
                if loop.time() - last_slow >= 1.0:
                    last_slow = loop.time()
                    sync_comm_alarms(twin)
                    msgs += self._queue
                    self._queue = []
                    ts = iso(now_kst())
                    topo = topology(twin)
                    msgs.append({"type": "summary", **summary(twin), "ts": ts})
                    msgs.append({"type": "topology", **topo, "ts": ts})
                    for n in topo["nodes"]:
                        if n["kind"] == "device" and self._status_prev.get(n["id"]) != n["status"]:
                            self._status_prev[n["id"]] = n["status"]
                            msgs.append({"type": "equip_status", "equip": n["id"], "status": n["status"], "ts": ts})
                    buf = twin.edge.buffer.stats()
                    msgs.append({"type": "edge_buffer", **buf, "mes_link": twin.edge.mes_link_state(), "ts": ts})
                    msgs.extend(self._mem_changes(twin, ts))
                await self._send_all(msgs)
            except Exception as exc:
                log.error("hub_error", equip="*", error=repr(exc))

    def _mem_changes(self, twin: Twin, ts: str) -> list[dict[str, Any]]:
        out = []
        for pid, p in twin.plcs.items():
            cur = p.memory.read(0, 1000)
            prev = self._mem_prev.get(pid)
            self._mem_prev[pid] = cur
            if prev is None:
                continue
            ch = [{"addr": f"D{i:04d}", "value": v} for i, (a, v) in enumerate(zip(prev, cur, strict=True)) if a != v]
            if ch:
                out.append({"type": "plc_mem", "plc": pid, "changes": ch, "ts": ts})
        return out

    async def close(self) -> None:
        for ws in list(self.clients):
            with contextlib.suppress(Exception):
                await ws.close()
        self.clients.clear()
