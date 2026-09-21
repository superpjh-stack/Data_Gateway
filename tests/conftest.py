"""테스트 하네스: 빈 포트·임시 데이터 폴더로 트윈 전체를 띄운다."""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from twin.common.config import TwinConfig, load_config
from twin.common.util import setup_logging
from twin.supervisor import Twin

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
PORT_KEYS = [
    "bus_M1",
    "bus_M2",
    "bus_S1",
    "scale",
    "san",
    "fill",
    "stuff",
    "opcua",
    "plc_MASTER",
    "plc_SLAVE",
    "mes_http",
]

setup_logging("WARNING")


def free_ports(n: int) -> list[int]:
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


def make_config(tmp: Path, overrides: dict[str, Any] | None = None) -> TwinConfig:
    ov = dict(overrides or {})
    ports = dict(zip(PORT_KEYS, free_ports(len(PORT_KEYS)), strict=True))
    rt = ov.setdefault("runtime", {})
    rt.setdefault("ports", {}).update(ports)
    rt["data_dir"] = str(tmp / "data")
    return load_config(CONFIG, ov)


FAST = {
    code: {"poll_ms": 1000}
    for code in [f"THD-0{i}" for i in range(1, 10)]
    + ["THD-10", "TC-01", "TC-02", "TC-03", "TC-04", "SAL-01", "SAL-02", "SAN-01", "FILL-01", "STUFF-01"]
}
FAST["PKG-01"] = {"poll_ms": 1000}


async def wait_until(
    pred: Callable[[], Awaitable[bool]] | Callable[[], bool],
    timeout: float,
    interval: float = 0.2,
    msg: str = "",
) -> float:
    """조건이 참이 될 때까지 기다리고 걸린 시간을 돌려준다 (고정 sleep 금지)."""
    t0 = time.monotonic()
    while True:
        r = pred()
        if asyncio.iscoroutine(r):
            r = await r
        if r:
            return time.monotonic() - t0
        if time.monotonic() - t0 > timeout:
            raise AssertionError(f"{timeout}s 안에 조건 불충족: {msg}")
        await asyncio.sleep(interval)


@pytest.fixture
def twin_factory(tmp_path: Path) -> Callable[..., Any]:
    """async with twin_factory(overrides) as (twin, http): ..."""

    class _Ctx:
        def __init__(self, overrides: dict[str, Any] | None, fast: bool) -> None:
            ov = dict(overrides or {})
            if fast:
                patch = {k: dict(v) for k, v in FAST.items()}
                for k, v in ov.get("equipment_patch", {}).items():
                    patch.setdefault(k, {}).update(v)
                ov["equipment_patch"] = patch
            self.cfg = make_config(tmp_path, ov)
            self.twin: Twin | None = None
            self.http: httpx.AsyncClient | None = None

        async def __aenter__(self) -> tuple[Twin, httpx.AsyncClient]:
            self.twin = Twin(self.cfg, serve_static=False)
            await self.twin.start()
            self.http = httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{self.cfg.port('mes_http')}", timeout=10
            )
            return self.twin, self.http

        async def __aexit__(self, *exc: object) -> None:
            if self.http:
                await self.http.aclose()
            if self.twin:
                await self.twin.stop()

    def factory(overrides: dict[str, Any] | None = None, fast: bool = True) -> _Ctx:
        return _Ctx(overrides, fast)

    return factory


@pytest.fixture
async def twin_http(twin_factory: Callable[..., Any]) -> AsyncIterator[tuple[Twin, httpx.AsyncClient]]:
    async with twin_factory() as pair:
        yield pair


def raw_count(twin: Twin, code: str | None = None, **where: str) -> int:
    sql = "SELECT COUNT(*) FROM IF_SENSOR_RAW r JOIN BAS_EQUIP e ON e.EQUIP_ID=r.EQUIP_ID WHERE 1=1"
    params: list[Any] = []
    if code:
        sql += " AND e.EQUIP_CODE=?"
        params.append(code)
    for k, v in where.items():
        sql += f" AND r.{k}=?"
        params.append(v)
    return int(twin.mes.db.execute(sql, params).fetchone()[0])


def ids_present(twin: Twin, upto: int) -> int:
    """msg_id 번호가 upto 이하인 원장 행 수 (누락 검사: upto와 같아야 한다)."""
    return int(
        twin.mes.db.execute(
            "SELECT COUNT(*) FROM IF_SENSOR_RAW WHERE CAST(substr(MSG_ID, 8) AS INTEGER) <= ?", (upto,)
        ).fetchone()[0]
    )
