"""Field Simulator: 장비 모델 22개와 프로토콜 서버를 띄우고 1 s 틱으로 모델을 갱신한다."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from twin.common.config import TwinConfig
from twin.common.util import get_logger
from twin.field.faults import FaultManager
from twin.field.models.base import DeviceModel
from twin.field.models.process import (
    BrineSensorModel,
    MetalDetectorModel,
    ScaleModel,
    TapingMachineModel,
    build_model,
)
from twin.field.servers.servers import (
    AsciiScaleServer,
    ModbusTcpDeviceServer,
    RtuBusServer,
    TapingOpcUaServer,
)

log = get_logger("field")


class FieldSimulator:
    """가상 장비 전체."""

    def __init__(self, cfg: TwinConfig, faults: FaultManager) -> None:
        self.cfg = cfg
        self.faults = faults
        seed = cfg.runtime.seed
        self.models: dict[str, DeviceModel] = {
            e.code: build_model(e, seed, faults, cfg.tanks) for e in cfg.equipment
        }
        host = cfg.runtime.host
        self.bus_servers: dict[str, RtuBusServer] = {}
        for bid, bus in cfg.buses.items():
            devs = {
                e.via.slave: self.models[e.code] for e in cfg.equipment if e.via.bus == bid and e.via.slave
            }
            self.bus_servers[bid] = RtuBusServer(bid, host, cfg.port(bus.link), devs, faults, bus.baud)
        self.tcp_servers: list[Any] = []
        self.opcua: TapingOpcUaServer | None = None
        for e in cfg.equipment:
            m = self.models[e.code]
            if e.kind in ("plc_tcp", "edge_modbus_tcp"):
                assert e.via.link
                self.tcp_servers.append(ModbusTcpDeviceServer(host, cfg.port(e.via.link), m, faults))
            elif e.kind == "edge_ascii":
                assert e.via.link and isinstance(m, ScaleModel)
                self.tcp_servers.append(AsciiScaleServer(host, cfg.port(e.via.link), m, faults))
            elif e.kind == "edge_opcua":
                assert e.via.link and isinstance(m, TapingMachineModel)
                self.opcua = TapingOpcUaServer(host, cfg.port(e.via.link), m)
        self._tick_task: asyncio.Task[None] | None = None
        self.ticks = 0

    async def start(self) -> None:
        for s in self.bus_servers.values():
            await s.start()
        for t in self.tcp_servers:
            await t.start()
        if self.opcua is not None:
            await self.opcua.start()
        self._tick_task = asyncio.create_task(self._ticker())
        log.info("field_started", equip="*", devices=len(self.models))

    async def stop(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
        for s in self.bus_servers.values():
            await s.stop()
        for t in self.tcp_servers:
            await t.stop()
        if self.opcua is not None:
            await self.opcua.stop()

    def tick(self) -> None:
        dt = self.cfg.runtime.field.tick_ms / 1000 * self.cfg.runtime.time_scale
        for m in self.models.values():
            m.step(dt)
        self.ticks += 1

    async def _ticker(self) -> None:
        period = self.cfg.runtime.field.tick_ms / 1000
        while True:
            await asyncio.sleep(period)
            try:
                self.tick()
            except Exception as exc:
                log.error("tick_error", equip="*", error=repr(exc))

    async def reconcile(self) -> None:
        """opcua_down 고장 상태에 맞춰 OPC-UA 서버를 켜고 끈다."""
        if self.opcua is None:
            return
        down = self.faults.has("opcua_down", self.opcua.model.code)
        if down and self.opcua.running:
            await self.opcua.stop()
            log.warning("opcua_stopped", equip=self.opcua.model.code)
        elif not down and not self.opcua.running:
            await self.opcua.start()
            log.info("opcua_started", equip=self.opcua.model.code)

    def trigger_metal_ng(self, code: str) -> None:
        m = self.models[code]
        if not isinstance(m, MetalDetectorModel):
            raise ValueError(f"{code}는 금속검출기가 아님")
        m.trigger_ng()

    def tank_states(self) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for m in self.models.values():
            if isinstance(m, BrineSensorModel):
                cur = m.current_tank()
                for n, st in m.tank_states().items():
                    out[n] = {**st, "sensor": m.code, "measuring": n == cur}
        return out
