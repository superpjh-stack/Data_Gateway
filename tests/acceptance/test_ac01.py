"""AC-01 전체 기동 후 22개 정상, 수집 성공률 ≥ 99 %, IF_SENSOR_RAW에 22개 설비 적재."""

import asyncio

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance


async def test_ac01_all_equipment_ok(twin_http):
    twin, http = twin_http

    async def all_ok() -> bool:
        return (await http.get("/api/summary")).json()["ok"] == 22

    await wait_until(all_ok, 30, msg="22개 정상")
    await asyncio.sleep(10)  # 성공률 표본 확보
    s = (await http.get("/api/summary")).json()
    assert s["ok"] == 22 and s["total"] == 22
    assert s["success_rate"] >= 0.99
    n = twin.mes.db.execute("SELECT COUNT(DISTINCT EQUIP_ID) FROM IF_SENSOR_RAW").fetchone()[0]
    assert n == 22
    assert s["mes_link"] == "OK" and s["plcs"] == {"MASTER": "OK", "SLAVE": "OK"}
