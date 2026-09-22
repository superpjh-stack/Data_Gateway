"""DB 일일 정리 (D-017): 수집 데이터를 비우고 파일을 줄인 뒤, 수집은 그대로 다시 쌓인다."""

from tests.conftest import raw_count, wait_until
from twin.common.util import iso, now_kst

KEEP = ["BAS_EQUIP", "BAS_CCP_STD", "ORD_WORK_ORDER"]


def _count(twin, table: str, where: str = "1=1") -> int:
    return int(twin.mes.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


async def test_purge_clears_and_reloads(twin_http):
    twin, http = twin_http
    await wait_until(lambda: raw_count(twin) > 200 and _count(twin, "EQP_RUN_LOG") > 0, 30, msg="데이터 적재")
    open_runs = _count(twin, "EQP_RUN_LOG", "END_DT IS NULL")
    active_tanks = _count(twin, "SLT_TANK_OPR", "TANK_STATUS='절임중'")
    masters = {t: _count(twin, t) for t in KEEP}

    r = await http.post("/api/admin/purge")
    assert r.status_code == 200
    res = r.json()
    assert res["trigger"] == "MANUAL" and res["deleted"]["IF_SENSOR_RAW"] > 200
    assert res["deleted_total"] == sum(res["deleted"].values())
    assert res["db_bytes_after"] < res["db_bytes_before"], "VACUUM 뒤 파일이 줄어야 한다"

    # 정리 직후: 수집 데이터는 비고, 기준정보·진행 중 운영건은 남는다
    assert raw_count(twin) < 50
    assert {t: _count(twin, t) for t in KEEP} == masters
    assert _count(twin, "SLT_TANK_OPR", "TANK_STATUS='절임중'") == active_tanks
    assert _count(twin, "EQP_RUN_LOG", "END_DT IS NULL") == open_runs

    # 다시 적재된다 (22개 설비 모두)
    await wait_until(
        lambda: twin.mes.db.execute("SELECT COUNT(DISTINCT EQUIP_ID) FROM IF_SENSOR_RAW").fetchone()[0] == 22,
        30,
        msg="정리 후 22개 설비 재적재",
    )
    st = (await http.get("/api/admin/purge")).json()
    assert st["enabled"] and st["at"] == "03:00" and st["next"]
    assert st["history"][0]["TRIGGER_TYPE"] == "MANUAL"
    assert st["history"][0]["DELETED_JSON"]["IF_SENSOR_RAW"] == res["deleted"]["IF_SENSOR_RAW"]


async def test_purge_keeps_rows_after_cutoff(twin_http):
    twin, _ = twin_http
    await wait_until(lambda: raw_count(twin) > 100, 30)
    cutoff = iso(now_kst())
    await wait_until(
        lambda: _count(twin, "IF_SENSOR_RAW", f"COLLECT_DT >= '{cutoff}'") > 20, 20, msg="기준 이후 적재"
    )
    newer = _count(twin, "IF_SENSOR_RAW", f"COLLECT_DT >= '{cutoff}'")
    res = twin.mes.purge(cutoff, trigger="SCHEDULE", vacuum=False)
    assert _count(twin, "IF_SENSOR_RAW", f"COLLECT_DT < '{cutoff}'") == 0
    assert _count(twin, "IF_SENSOR_RAW") >= newer
    assert res["deleted"]["IF_SENSOR_RAW"] > 0


async def test_active_alarm_survives_purge(twin_factory):
    async with twin_factory({"ccp_patch": {"CCP-SAN": {"hold_sec": 1}}}) as (twin, http):
        await http.post(
            "/api/sim/faults",
            json={
                "target": "SAN-01",
                "type": "value_spike",
                "params": {"key": "ppm", "value": 8.5},
                "duration_s": 60,
            },
        )
        q = "SELECT COUNT(*) FROM TWIN_ALARM WHERE RULE_ID='CCP-SAN' AND STATE='RAISED'"
        await wait_until(lambda: twin.mes.db.execute(q).fetchone()[0] == 1, 20, msg="알람 발생")
        twin.purge_now()
        assert twin.mes.db.execute(q).fetchone()[0] == 1, "해제되지 않은 알람은 지우지 않는다"
