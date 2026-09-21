"""AC-12 PLC에 Modbus Write 요청 → 거부(예외 01), 로그 기록, 메모리 불변. pymodbus로 상호운용도 확인."""

import pytest
from pymodbus.client import AsyncModbusTcpClient

from tests.conftest import wait_until

pytestmark = pytest.mark.acceptance


async def test_ac12_plc_rejects_writes(twin_http):
    twin, http = twin_http
    port = twin.cfg.port("plc_MASTER")
    await wait_until(lambda: twin.plcs["MASTER"].memory.read(108, 1)[0] > 0, 20)
    client = AsyncModbusTcpClient("127.0.0.1", port=port, timeout=2, retries=0)
    await client.connect()
    try:
        rr = await client.read_holding_registers(900, count=6, device_id=1)
        assert not rr.isError() and rr.registers[0] > 0  # 표준 클라이언트로 읽힘
        freeze = await http.post("/api/sim/faults", json={"target": "SAL-01", "type": "value_freeze"})
        await wait_until(lambda: True, 0.1)
        before = twin.plcs["MASTER"].memory.read(102, 1)[0]
        wr = await client.write_register(102, 9999, device_id=1)
        assert wr.isError() and wr.exception_code == 1
        wr2 = await client.write_registers(100, [1, 2, 3], device_id=1)
        assert wr2.isError() and wr2.exception_code == 1
        wc = await client.write_coil(0, True, device_id=1)
        assert wc.isError()
        assert twin.plcs["MASTER"].memory.read(102, 1)[0] == before
        rej = twin.plcs["MASTER"].write_rejections
        assert [r["fc"] for r in rej[-3:]] == [6, 16, 5]
        mem = (await http.get("/api/plc/MASTER/memory")).json()
        assert mem["diag"]["write_rejections"] >= 3
        await http.delete(f"/api/sim/faults/{freeze.json()['id']}")
    finally:
        client.close()
