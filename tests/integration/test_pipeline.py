"""통합: 단계별 완료 조건, 상태 판정(DELAY/ERROR), OPC-UA 장애, Master–Slave 연동, 통신 알람, WebSocket."""

import asyncio
import json

import pytest
import websockets

from tests.conftest import raw_count, wait_until


async def test_stage1_thd01_reaches_raw_ledger(twin_http):
    twin, _ = twin_http
    await wait_until(lambda: raw_count(twin, "THD-01") >= 3, 20, msg="THD-01 3행")
    tags = {
        r[0]
        for r in twin.mes.db.execute(
            "SELECT TAG_ADDR FROM IF_SENSOR_RAW r JOIN BAS_EQUIP e ON e.EQUIP_ID=r.EQUIP_ID WHERE e.EQUIP_CODE='THD-01'"
        )
    }
    assert tags == {"SLAVE.D0102", "SLAVE.D0103"}
    row = twin.mes.db.execute(
        "SELECT COMM_TYPE, TARGET_TABLE, DATA_TYPE FROM IF_SENSOR_RAW WHERE TAG_ADDR='SLAVE.D0102'"
    ).fetchone()
    assert row == ("RS-485", "AGE_ENV_LOG", "온도")


async def test_all_target_tables_receive_rows(twin_http):
    twin, http = twin_http
    tables = [
        "SLT_SALINITY_LOG",
        "WSH_SANITIZER_LOG",
        "AGE_ENV_LOG",
        "QUA_METAL_LOG",
        "PKG_WEIGHT_INSP",
        "MIX_FILLER_LOG",
        "EQP_RUN_LOG",
    ]

    async def filled() -> bool:
        c = (await http.get("/api/tables/stats")).json()["counts"]
        return all(c[t] > 0 for t in tables)

    await wait_until(filled, 25, msg="분배 테이블")


async def test_delay_state_d008(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.device_state("THD-08") == "OK", 20)
    await http.post(
        "/api/sim/faults",
        json={"target": "THD-08", "type": "sensor_delay", "params": {"ms": 200}, "duration_s": 30},
    )
    await wait_until(lambda: twin.edge.device_state("THD-08") == "DELAY", 20, msg="DELAY")


async def test_crc_error_state(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.device_state("THD-09") == "OK", 20)
    await http.post(
        "/api/sim/faults",
        json={"target": "THD-09", "type": "crc_error", "params": {"ratio": 0.5}, "duration_s": 30},
    )
    await wait_until(lambda: twin.edge.device_state("THD-09") == "ERROR", 20, msg="ERROR")
    frames = (await http.get("/api/equip/THD-09/frames")).json()
    assert any(f["result"] == "CRC" for f in frames)
    assert (await http.get("/api/equip/THD-09")).json()["diag"]["errors"]["crc"] > 0


async def test_opcua_down_and_recover(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.device_state("PKG-01") == "OK", 20)
    r = await http.post("/api/sim/faults", json={"target": "PKG-01", "type": "opcua_down"})
    await wait_until(lambda: twin.edge.device_state("PKG-01") == "DOWN", 30, msg="OPC-UA DOWN")
    await http.delete(f"/api/sim/faults/{r.json()['id']}")
    await wait_until(lambda: twin.edge.device_state("PKG-01") == "OK", 30, msg="OPC-UA 복구")


async def test_master_slave_link_down_keeps_slave_devices(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.readers["MASTER"].slave_link_state() == "OK", 20)
    await http.post(
        "/api/sim/faults", json={"target": "MASTER-SLAVE", "type": "master_slave_link_down", "duration_s": 30}
    )
    await wait_until(lambda: twin.edge.readers["MASTER"].slave_link_state() == "DOWN", 10)
    assert twin.edge.device_state("THD-01") == "OK"  # Edge는 Slave를 직접 읽는다
    assert twin.plcs["MASTER"].memory.read(905, 1)[0] == 2


async def test_comm_alarm_raised_and_cleared(twin_factory):
    async with twin_factory() as (twin, http):
        import twin.mes.views as views

        views.COMM_GRACE_S = 0.0
        try:
            await wait_until(lambda: twin.edge.device_state("THD-10") == "OK", 20)
            r = await http.post("/api/sim/faults", json={"target": "THD-10", "type": "sensor_disconnect"})
            q = "SELECT STATE FROM TWIN_ALARM WHERE CATEGORY='COMM' AND EQUIP_CODE='THD-10' ORDER BY ALARM_ID DESC"
            await wait_until(
                lambda: (twin.mes.db.execute(q).fetchone() or [None])[0] == "RAISED", 30, msg="통신 알람"
            )
            await http.delete(f"/api/sim/faults/{r.json()['id']}")
            await wait_until(
                lambda: twin.mes.db.execute(q).fetchone()[0] == "CLEARED", 30, msg="통신 알람 해제"
            )
        finally:
            views.COMM_GRACE_S = 15.0


async def test_websocket_snapshot_and_stream(twin_http):
    twin, _ = twin_http
    url = f"ws://127.0.0.1:{twin.cfg.port('mes_http')}/ws"
    async with websockets.connect(url) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert first["type"] == "snapshot" and first["summary"]["total"] == 22
        seen: set[str] = set()
        for _ in range(40):
            msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
            for m in msg if isinstance(msg, list) else [msg]:
                seen.add(m["type"])
            if {"value", "summary", "topology", "edge_buffer"} <= seen:
                break
        assert {"value", "summary", "topology", "edge_buffer"} <= seen


async def test_scenario_and_fault_api_validation(twin_http):
    _, http = twin_http
    assert (await http.post("/api/sim/faults", json={"target": "M9", "type": "bus_cut"})).status_code == 400
    names = (await http.get("/api/sim/scenarios")).json()
    assert len(names) == 4
    r = await http.post("/api/sim/scenarios/Master 버스 M2 단선/run")
    assert r.status_code == 200
    await wait_until(lambda: True, 0.3)
    faults = (await http.get("/api/sim/faults")).json()
    assert any(f["type"] == "bus_cut" and f["target"] == "M2" for f in faults)
    cat = (await http.get("/api/sim/catalog")).json()
    assert {c["type"] for c in cat} >= {"bus_cut", "plc_down", "mes_link_down", "value_spike", "edge_restart"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/equip",
        "/api/tanks",
        "/api/ccp",
        "/api/alarms",
        "/api/raw",
        "/api/meta",
        "/api/plc/SLAVE/memory",
        "/api/edge/buffer",
        "/api/tables/SLT_TANK_OPR",
        "/api/equip/SCALE-01/history",
    ],
)
async def test_read_endpoints(twin_http, path):
    _, http = twin_http
    r = await http.get(path)
    assert r.status_code == 200, r.text
