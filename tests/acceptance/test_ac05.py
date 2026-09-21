"""AC-05 소독수 농도 8.5 ppm 지속 → hold_sec 경과 시 알람, WSH_SANITIZER_LOG.ALARM_YN=Y, 그 전에는 알람 없음.

실제 기준 hold 60 s를 테스트에서는 5 s로 줄인다 (D-004)."""

import time

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance
HOLD = 5.0


def _alarm(twin):
    return twin.mes.db.execute(
        "SELECT ALARM_ID, RAISED_DT, MESSAGE FROM TWIN_ALARM WHERE RULE_ID='CCP-SAN'"
    ).fetchone()


async def test_ac05_sanitizer_alarm_after_hold(twin_factory):
    async with twin_factory({"ccp_patch": {"CCP-SAN": {"hold_sec": HOLD}}}) as (twin, http):
        await wait_until(
            lambda: twin.mes.db.execute("SELECT COUNT(*) FROM WSH_SANITIZER_LOG").fetchone()[0] > 0, 20
        )
        assert _alarm(twin) is None
        await http.post(
            "/api/sim/faults",
            json={
                "target": "SAN-01",
                "type": "value_spike",
                "params": {"key": "ppm", "value": 8.5},
                "duration_s": 30,
            },
        )
        await wait_until(
            lambda: (
                twin.mes.db.execute("SELECT COUNT(*) FROM WSH_SANITIZER_LOG WHERE PPM_VALUE=8.5").fetchone()[
                    0
                ]
                > 0
            ),
            10,
            interval=0.05,
            msg="8.5 ppm 수신",
        )
        first_seen = time.monotonic()
        while time.monotonic() - first_seen < HOLD - 1.0:
            assert _alarm(twin) is None, "hold 전에 알람이 나면 안 됨"
            await wait_until(lambda: True, 0.1)
        await wait_until(lambda: _alarm(twin) is not None, HOLD + 4, msg="알람 발생")
        a = _alarm(twin)
        assert "소독수" in a[2] and "8.5" in a[2]
        y = twin.mes.db.execute("SELECT COUNT(*) FROM WSH_SANITIZER_LOG WHERE ALARM_YN='Y'").fetchone()[0]
        assert y >= 2
        active = (await http.get("/api/alarms", params={"active": True})).json()
        assert any(x["rule_id"] == "CCP-SAN" for x in active)
