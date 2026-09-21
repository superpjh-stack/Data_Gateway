"""AC-08 포장기 정지 → 가동 → EQP_RUN_LOG 비가동 구간 1행 (START_DT, END_DT, STOP_MINUTES)."""

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance


async def test_ac08_taping_machine_downtime(twin_http):
    twin, http = twin_http
    eid = twin.mes.equip_id["PKG-01"]
    q = "SELECT RUN_STATUS, START_DT, END_DT, STOP_MINUTES FROM EQP_RUN_LOG WHERE EQUIP_ID=? ORDER BY RUN_LOG_ID"
    await wait_until(lambda: len(twin.mes.db.execute(q, (eid,)).fetchall()) > 0, 20, msg="가동 구간 시작")
    r = await http.post(
        "/api/sim/faults",
        json={
            "target": "PKG-01",
            "type": "value_spike",
            "params": {"key": "running", "value": 0},
            "duration_s": 4,
        },
    )
    assert r.status_code == 200

    def closed_stop() -> bool:
        return any(
            row[0] == "비가동" and row[2] is not None for row in twin.mes.db.execute(q, (eid,)).fetchall()
        )

    await wait_until(closed_stop, 20, msg="비가동 구간 종료")
    stop = next(row for row in twin.mes.db.execute(q, (eid,)).fetchall() if row[0] == "비가동")
    assert stop[1] < stop[2] and stop[3] > 0
    assert twin.mes.db.execute(q, (eid,)).fetchall()[-1][0] == "가동"
