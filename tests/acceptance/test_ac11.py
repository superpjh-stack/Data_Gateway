"""AC-11 습도 150 % → 노이즈 필터에서 FILTERED, IF_SENSOR_RAW에 적재되지 않음."""

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance


async def test_ac11_noise_filtered(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.device_state("THD-07") == "OK", 20)
    await http.post(
        "/api/sim/faults",
        json={
            "target": "THD-07",
            "type": "value_spike",
            "params": {"key": "humid", "value": 150},
            "duration_s": 10,
        },
    )
    await wait_until(lambda: twin.edge.filter.filtered.get("THD-07", 0) >= 2, 10, msg="필터 카운트")
    bad = twin.mes.db.execute(
        "SELECT COUNT(*) FROM IF_SENSOR_RAW r JOIN BAS_EQUIP e ON e.EQUIP_ID=r.EQUIP_ID WHERE e.EQUIP_CODE='THD-07' "
        "AND r.ITEM_KEY='humid' AND CAST(r.RAW_VALUE AS REAL) > 100"
    ).fetchone()[0]
    assert bad == 0
    env_bad = twin.mes.db.execute("SELECT COUNT(*) FROM AGE_ENV_LOG WHERE HUMID_VALUE > 100").fetchone()[0]
    assert env_bad == 0
    st = (await http.get("/api/edge/buffer")).json()
    assert st["filtered"]["THD-07"] >= 2
    assert any(f["equip"] == "THD-07" and f["value"] == 150 for f in st["filtered_recent"])
