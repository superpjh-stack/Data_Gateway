"""AC-10 버퍼가 쌓인 상태에서 Edge 재시작 → 버퍼 유지, msg_id 연속, 복구 후 전송 재개."""

import pytest

from tests.conftest import ids_present, wait_until

pytestmark = pytest.mark.acceptance


async def test_ac10_edge_restart_keeps_buffer(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.mes_link_state() == "OK", 20)
    r = await http.post("/api/sim/faults", json={"target": "EDGE-MES", "type": "mes_link_down"})
    fid = r.json()["id"]
    await wait_until(lambda: twin.edge.buffer.stats()["pending_items"] > 20, 10)
    before = twin.edge.buffer.stats()
    old_edge = twin.edge
    r = await http.post("/api/sim/faults", json={"target": "EDGE", "type": "edge_restart"})
    assert r.status_code == 200
    assert twin.edge is not old_edge
    after = twin.edge.buffer.stats()
    assert after["pending_items"] >= before["pending_items"]
    await wait_until(lambda: twin.edge.buffer.stats()["seq"] > after["seq"], 10, msg="재시작 후 수집 재개")
    await http.delete(f"/api/sim/faults/{fid}")
    await wait_until(lambda: twin.edge.buffer.stats()["pending_items"] == 0, 60, msg="버퍼 비워짐")
    seq = twin.edge.buffer.stats()["seq"]
    await wait_until(lambda: ids_present(twin, seq) == seq, 10, msg="재시작 전후 msg_id 누락 없음")
    total, distinct = twin.mes.db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT MSG_ID) FROM IF_SENSOR_RAW"
    ).fetchone()
    assert total == distinct
