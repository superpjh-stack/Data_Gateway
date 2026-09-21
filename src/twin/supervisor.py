"""전체 기동: Field → PLC → MES(API) → Edge 순서로 띄우고 고장 상태를 반영한다 (D-003)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import time
from pathlib import Path
from typing import Any

import uvicorn

from twin.common.config import ConfigError, TwinConfig, load_config
from twin.common.util import get_logger, setup_logging
from twin.edge.collector import EdgeCollector
from twin.field.faults import FaultManager
from twin.field.simulator import FieldSimulator
from twin.mes.hub import WsHub
from twin.mes.store import MesStore
from twin.plc.runtime import PlcRuntime

log = get_logger("supervisor")


class Twin:
    """디지털 트윈 전체. 테스트는 이 객체를 직접 띄운다."""

    def __init__(self, cfg: TwinConfig, *, serve_static: bool = True) -> None:
        self.cfg = cfg
        targets: dict[str, list[str]] = {
            "equip": [e.code for e in cfg.equipment],
            "bus": list(cfg.buses),
            "plc": list(cfg.plcs),
            "opcua": [e.code for e in cfg.equipment if e.kind == "edge_opcua"],
            "metal": [e.code for e in cfg.equipment if e.sim.get("model") == "metal_detector"],
        }
        self.faults = FaultManager(targets)
        self.hub = WsHub(cfg.runtime.ws.flush_ms / 1000)
        self.field = FieldSimulator(cfg, self.faults)
        self.plcs = {pid: PlcRuntime(pid, cfg, self.faults) for pid in cfg.plcs}
        self.mes = MesStore(cfg, self.hub.publish)
        self.edge = EdgeCollector(cfg, self.faults)
        self.serve_static = serve_static
        self.started_at = time.monotonic()
        self._server: uvicorn.Server | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._scenario_tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        from twin.mes.app import create_app  # 순환 import 방지

        await self.field.start()
        for p in self.plcs.values():
            await p.start()
        app = create_app(self)
        port = self.cfg.port("mes_http")
        config = uvicorn.Config(
            app,
            host=self.cfg.runtime.host,
            port=port,
            log_level="warning",
            lifespan="off",
            ws_ping_interval=20,
        )
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self._tasks.append(asyncio.create_task(self._server.serve()))
        for _ in range(100):
            if self._server.started:
                break
            await asyncio.sleep(0.05)
        await self.edge.start()
        self._tasks.append(asyncio.create_task(self._reconcile()))
        self._tasks.append(asyncio.create_task(self.hub.run(self)))
        self.started_at = time.monotonic()
        log.info("twin_started", equip="*", url=f"http://{self.cfg.runtime.host}:{port}")

    async def stop(self) -> None:
        # 주기 작업(허브·고장 반영)을 먼저 멈춰야 닫힌 DB·링크를 건드리지 않는다
        for t in [*self._scenario_tasks, *self._tasks[1:]]:
            t.cancel()
        for t in self._tasks[1:]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(t, 3)
        await self.edge.stop()
        for p in self.plcs.values():
            if p.running:
                await p.stop()
        await self.field.stop()
        await self.hub.close()
        if self._server is not None:
            self._server.should_exit = True
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._tasks[0], 5)
        self.mes.close()

    async def __aenter__(self) -> Twin:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # ── 고장 반영 ──
    async def _reconcile(self) -> None:
        while True:
            try:
                for pid, p in self.plcs.items():
                    down = self.faults.has("plc_down", pid)
                    if down and p.running:
                        await p.stop()
                    elif not down and not p.running:
                        await p.start()
                await self.field.reconcile()
            except Exception as exc:
                log.error("reconcile_error", equip="*", error=repr(exc))
            await asyncio.sleep(0.2)

    async def restart_edge(self) -> None:
        """Edge 프로세스 재시작을 흉내 낸다. 버퍼 DB는 디스크에 남는다 (AC-10)."""
        await self.edge.stop()
        self.edge = EdgeCollector(self.cfg, self.faults)
        await self.edge.start()
        log.warning("edge_restarted", equip="EDGE")

    async def apply_fault(
        self, target: str, type_: str, params: dict[str, Any], duration_s: float | None
    ) -> Any:
        if type_ == "edge_restart":
            self.faults.validate(target, type_, params)
            await self.restart_edge()
            return None
        if type_ == "metal_ng":
            self.faults.validate(target, type_, params)
            self.field.trigger_metal_ng(target)
            return None
        return self.faults.add(target, type_, params, duration_s)

    def run_scenario(self, name: str) -> list[str]:
        steps = self.cfg.scenarios[name]

        async def later(step: Any) -> None:
            await asyncio.sleep(step.at_s)
            await self.apply_fault(step.target, step.type, step.params, step.duration_s)

        for s in steps:
            t = asyncio.create_task(later(s))
            self._scenario_tasks.add(t)
            t.add_done_callback(self._scenario_tasks.discard)
        return [f"{s.target}:{s.type}" for s in steps]


async def _main(args: argparse.Namespace) -> None:
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc))
        raise SystemExit(2) from exc
    setup_logging(cfg.runtime.log_level)
    if args.fresh:
        for f in (
            "mes.db",
            "mes.db-wal",
            "mes.db-shm",
            "edge_buffer.db",
            "edge_buffer.db-wal",
            "edge_buffer.db-shm",
        ):
            with contextlib.suppress(FileNotFoundError):
                (Path(cfg.runtime.data_dir) / f).unlink()
    twin = Twin(cfg)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await twin.start()
    print(
        f"\n  임진강김치 수집 트윈 기동 완료 → http://{cfg.runtime.host}:{cfg.port('mes_http')}\n", flush=True
    )
    await stop.wait()
    await asyncio.wait_for(twin.stop(), 5)


def main() -> None:
    ap = argparse.ArgumentParser(description="임진강김치 PLC 데이터수집 디지털 트윈")
    ap.add_argument("--config", default="config")
    ap.add_argument("--fresh", action="store_true", help="MES·Edge DB를 지우고 시작")
    asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    main()
