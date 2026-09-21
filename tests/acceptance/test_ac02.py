"""AC-02 Master D0102 ÷ 100 = SAL-01 염도 = SLT_SALINITY_LOG 최신값 (D-010)."""

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance


async def test_ac02_memory_matches_tables(twin_http):
    twin, http = twin_http
    await wait_until(
        lambda: (
            twin.mes.db.execute("SELECT COUNT(*) FROM SLT_SALINITY_LOG WHERE SENSOR_ID='SAL-01'").fetchone()[
                0
            ]
            > 0
        ),
        20,
        msg="SAL-01 염도 적재",
    )
    # 값 비교 중 변하지 않도록 고정
    r = await http.post(
        "/api/sim/faults", json={"target": "SAL-01", "type": "value_freeze", "duration_s": 60}
    )
    assert r.status_code == 200

    def settled() -> bool:
        mem = twin.plcs["MASTER"].memory.read(102, 1)[0] / 100
        row = twin.mes.db.execute(
            "SELECT SALINITY_VALUE FROM SLT_SALINITY_LOG WHERE SENSOR_ID='SAL-01' ORDER BY "
            "SALINITY_LOG_ID DESC LIMIT 1"
        ).fetchone()
        return row is not None and abs(row[0] - mem) < 1e-9

    await wait_until(settled, 15, msg="D0102 ↔ SLT_SALINITY_LOG 일치")
    mem = twin.plcs["MASTER"].memory.read(102, 1)[0] / 100
    raw = twin.mes.db.execute(
        "SELECT r.RAW_VALUE, r.TAG_ADDR FROM IF_SENSOR_RAW r JOIN BAS_EQUIP e ON e.EQUIP_ID="
        "r.EQUIP_ID WHERE e.EQUIP_CODE='SAL-01' AND r.ITEM_KEY='salinity' ORDER BY r.RAW_ID DESC "
        "LIMIT 1"
    ).fetchone()
    assert float(raw[0]) == pytest.approx(mem)
    assert raw[1] == "MASTER.D0102"
    api = (await http.get("/api/plc/MASTER/memory", params={"start": 100, "count": 10})).json()
    assert api["words"][2] / 100 == pytest.approx(mem)
    assert api["labels"]["D0102"]["code"] == "SAL-01"
