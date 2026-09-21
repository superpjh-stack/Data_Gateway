"""E2E용 트윈 서버: MES 포트만 지정하고 나머지는 빈 포트·임시 데이터 폴더로 띄운다."""

from __future__ import annotations

import asyncio
import signal
import socket
import sys
import tempfile
from pathlib import Path

from twin.common.config import load_config
from twin.common.util import setup_logging
from twin.supervisor import Twin

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["bus_M1", "bus_M2", "bus_S1", "scale", "san", "fill", "stuff", "opcua", "plc_MASTER", "plc_SLAVE"]


def _free() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def main(port: int) -> None:
    setup_logging("WARNING")
    tmp = tempfile.mkdtemp(prefix="twin-e2e-")
    ports = {k: _free() for k in KEYS} | {"mes_http": port}
    cfg = load_config(ROOT / "config", {"runtime": {"ports": ports, "data_dir": tmp}})
    twin = Twin(cfg)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    await twin.start()
    await stop.wait()
    await asyncio.wait_for(twin.stop(), 5)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8765))
