"""AC-03 bus_cut(M2) → TC-01~04, MD-01만 끊김. M1·S1·SAN-01은 정상, 토폴로지 M2 링크 DOWN."""

import pytest

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance
M2 = ["TC-01", "TC-02", "TC-03", "TC-04", "MD-01"]


async def test_ac03_bus_cut_isolated(twin_http):
    twin, http = twin_http
    await wait_until(lambda: twin.edge.device_state("TC-01") == "OK", 20)
    r = await http.post("/api/sim/faults", json={"target": "M2", "type": "bus_cut", "duration_s": 60})
    fid = r.json()["id"]

    async def m2_down() -> bool:
        rows = {e["code"]: e["status"] for e in (await http.get("/api/equip")).json()}
        return all(rows[c] == "DOWN" for c in M2)

    elapsed = await wait_until(m2_down, 30, msg="M2 장비 DOWN")
    assert elapsed <= 30
    rows = {e["code"]: e["status"] for e in (await http.get("/api/equip")).json()}
    others = [c for c in rows if c not in M2]
    assert all(rows[c] == "OK" for c in others), {c: rows[c] for c in others if rows[c] != "OK"}
    topo = (await http.get("/api/topology")).json()
    link = next(lk for lk in topo["links"] if lk["from"] == "M2")
    assert link["status"] == "DOWN"
    assert next(lk for lk in topo["links"] if lk["from"] == "M1")["status"] == "OK"
    await http.delete(f"/api/sim/faults/{fid}")
    await wait_until(lambda: all(twin.edge.device_state(c) == "OK" for c in M2), 20, msg="M2 복구")
