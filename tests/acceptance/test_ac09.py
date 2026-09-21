"""AC-09 Edge–MES 회선 장애 → 버퍼 누적 → 복구 후 비워짐, 누락·중복 0, 복구분 RESEND_YN=Y.

실제 10분 장애를 테스트에서는 8 s로 줄인다 (D-004)."""

import pytest

from tests.conftest import ids_present, raw_count, wait_until

pytestmark = pytest.mark.acceptance


async def test_ac09_buffer_and_resend(twin_http):
    twin, http = twin_http
    await wait_until(lambda: raw_count(twin) > 50, 20)
    r = await http.post(
        "/api/sim/faults", json={"target": "EDGE-MES", "type": "mes_link_down", "duration_s": 8}
    )
    assert r.status_code == 200
    await wait_until(
        lambda: twin.edge.buffer.stats()["pending_items"] > 30 and twin.edge.mes_link_state() == "DOWN",
        8,
        msg="버퍼 누적 + 링크 DOWN",
    )
    await wait_until(
        lambda: twin.edge.buffer.stats()["pending_items"] == 0 and twin.edge.mes_link_state() == "OK",
        60,
        msg="버퍼 비워짐",
    )
    seq = twin.edge.buffer.stats()["seq"]
    await wait_until(lambda: ids_present(twin, seq) == seq, 10, msg="msg_id 1..seq 모두 도착 (누락 0)")
    total, distinct = twin.mes.db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT MSG_ID) FROM IF_SENSOR_RAW"
    ).fetchone()
    assert total == distinct, "중복 적재"
    assert raw_count(twin, RESEND_YN="Y") > 0
    assert twin.mes.dup == 0
