"""AC-06 TC-01 현재온도 7 ℃ 지속 → hold 경과 시 알람과 AGE_ENV_ALARM 1행 (hold 300 s → 테스트 5 s, D-004)."""

import time

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance
HOLD = 5.0


def _env_alarms(twin):
    return twin.mes.db.execute("SELECT COUNT(*) FROM AGE_ENV_ALARM").fetchone()[0]


async def test_ac06_cold_room_alarm(twin_factory):
    async with twin_factory({"ccp_patch": {"CCP-COLD": {"hold_sec": HOLD}}}) as (twin, http):
        await wait_until(lambda: twin.edge.device_state("TC-01") == "OK", 20)
        await http.post(
            "/api/sim/faults",
            json={
                "target": "TC-01",
                "type": "value_spike",
                "params": {"key": "pv", "value": 7.0},
                "duration_s": 30,
            },
        )
        await wait_until(
            lambda: (
                twin.mes.db.execute(
                    "SELECT COUNT(*) FROM AGE_ENV_LOG WHERE SENSOR_ID='TC-01' AND TEMP_VALUE=7.0"
                ).fetchone()[0]
                > 0
            ),
            10,
            interval=0.05,
        )
        t0 = time.monotonic()
        while time.monotonic() - t0 < HOLD - 1.0:
            assert _env_alarms(twin) == 0
            await wait_until(lambda: True, 0.1)
        await wait_until(lambda: _env_alarms(twin) == 1, HOLD + 4, msg="AGE_ENV_ALARM 생성")
        row = twin.mes.db.execute("SELECT ALARM_ITEM, ALARM_VALUE, CCP_STD_ID FROM AGE_ENV_ALARM").fetchone()
        assert row[0] == "온도" and row[1] == 7.0 and row[2] is not None
        assert (
            twin.mes.db.execute(
                "SELECT COUNT(*) FROM TWIN_ALARM WHERE RULE_ID='CCP-COLD' AND EQUIP_CODE='TC-01'"
            ).fetchone()[0]
            == 1
        )
