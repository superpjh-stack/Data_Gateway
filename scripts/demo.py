"""시연: 트윈을 띄우고 시나리오 4종을 1분 간격으로 실행한다. 대시보드는 http://127.0.0.1:8000"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

from twin.common.config import load_config
from twin.common.util import setup_logging
from twin.mes.views import summary
from twin.supervisor import Twin

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    cfg = load_config(ROOT / "config")
    setup_logging("WARNING")
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(ROOT / cfg.runtime.data_dir)
    async with Twin(cfg) as twin:
        url = f"http://{cfg.runtime.host}:{cfg.port('mes_http')}"
        print(f"대시보드 {url} — 30초 뒤 시나리오를 시작합니다 (Ctrl+C로 종료)", flush=True)
        await asyncio.sleep(30)
        for name in cfg.scenarios:
            print(f"▶ 시나리오: {name}", flush=True)
            twin.run_scenario(name)
            for _ in range(6):
                await asyncio.sleep(10)
                s = summary(twin)
                print(
                    f"   정상 {s['ok']}/{s['total']} · 버퍼 {s['buffer_pending']} · 알람 {s['active_alarms']}"
                    f" · MES {s['mes_link']}",
                    flush=True,
                )
        print("시나리오 완료. 계속 관찰하려면 그대로 두세요.", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
