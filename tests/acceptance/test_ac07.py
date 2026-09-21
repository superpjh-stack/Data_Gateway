"""AC-07 금속검출 NG → 2 s 이내 알람, QUA_METAL_LOG.DETECT_RESULT='NG', NG_QTY 증가."""

import time

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance


async def test_ac07_metal_ng_fast_alarm(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.mes.db.execute("SELECT COUNT(*) FROM QUA_METAL_LOG").fetchone()[0] > 0, 20)
    t0 = time.monotonic()
    r = await http.post("/api/sim/faults", json={"target": "MD-01", "type": "metal_ng"})
    assert r.status_code == 200
    await wait_until(
        lambda: (
            twin.mes.db.execute("SELECT COUNT(*) FROM TWIN_ALARM WHERE RULE_ID='CCP-METAL'").fetchone()[0]
            == 1
        ),
        3,
        interval=0.02,
        msg="금속 알람",
    )
    elapsed = time.monotonic() - t0
    assert elapsed <= 2.0, f"알람까지 {elapsed:.2f}s"
    row = twin.mes.db.execute(
        "SELECT DETECT_RESULT, NG_QTY, ALARM_YN, LOT_NO FROM QUA_METAL_LOG WHERE DETECT_RESULT='NG'"
    ).fetchone()
    assert row[0] == "NG" and row[1] >= 1 and row[2] == "Y" and row[3]
