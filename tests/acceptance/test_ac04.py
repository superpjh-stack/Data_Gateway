"""AC-04 plc_down(SLAVE) → THD-01~06 STALE, Master D0902 정지 감지, 토폴로지 Slave DOWN."""

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance
SLAVE_DEV = [f"THD-0{i}" for i in range(1, 7)]


async def test_ac04_slave_plc_down(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.readers["MASTER"].slave_link_state() == "OK", 20)
    r = await http.post("/api/sim/faults", json={"target": "SLAVE", "type": "plc_down", "duration_s": 60})
    fid = r.json()["id"]
    await wait_until(lambda: all(twin.edge.device_state(c) == "STALE" for c in SLAVE_DEV), 15, msg="STALE")
    before = twin.plcs["MASTER"].memory.read(902, 1)[0]
    await wait_until(
        lambda: twin.edge.readers["MASTER"].slave_link_state() == "DOWN", 10, msg="D0902 정지 감지"
    )
    assert twin.plcs["MASTER"].memory.read(902, 1)[0] == before
    topo = (await http.get("/api/topology")).json()
    assert next(n for n in topo["nodes"] if n["id"] == "SLAVE")["status"] == "DOWN"
    assert next(n for n in topo["nodes"] if n["id"] == "MASTER")["status"] == "OK"
    assert twin.edge.device_state("THD-07") == "OK"  # Master 쪽은 영향 없음
    await http.delete(f"/api/sim/faults/{fid}")
    await wait_until(lambda: all(twin.edge.device_state(c) == "OK" for c in SLAVE_DEV), 20, msg="Slave 복구")
