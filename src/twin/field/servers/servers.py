"""가상 장비 프로토콜 서버: RS-485 버스(RTU over TCP), Modbus TCP, RS-232 ASCII 저울, OPC-UA."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from twin.common.modbus import (
    EXC_ILLEGAL_FUNCTION,
    READ_FCS,
    ExceptionResponse,
    FrameErr,
    crc_ok,
    exception_pdu,
    mbap,
    read_mbap,
    read_rtu_frame,
    with_crc,
    words_pdu,
)
from twin.common.util import get_logger

if TYPE_CHECKING:
    from twin.field.faults import FaultManager
    from twin.field.models.base import DeviceModel
    from twin.field.models.process import ScaleModel, TapingMachineModel

log = get_logger("field")


class _TcpServerBase:
    """asyncio TCP 서버 공통: 시작·정지와 연결 목록 관리."""

    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self._server: asyncio.base_events.Server | None = None
        self._conns: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_conn, self.host, self.port, reuse_address=True)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            for w in list(self._conns):
                w.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)
            self._server = None
        for t in list(self._tasks):
            t.cancel()

    @property
    def running(self) -> bool:
        return self._server is not None

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._conns.add(writer)
        task = asyncio.current_task()
        if task:
            self._tasks.add(task)
        try:
            await self.serve(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        except Exception as exc:  # 연결 하나의 오류가 서버 전체로 번지지 않게
            log.warning("conn_error", port=self.port, error=repr(exc))
        finally:
            self._conns.discard(writer)
            if task:
                self._tasks.discard(task)
            writer.close()

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        raise NotImplementedError


async def _apply_device_faults(faults: FaultManager, code: str) -> bool:
    """무응답이면 False. 지연 고장은 여기서 기다린다."""
    if faults.has("sensor_disconnect", code):
        return False
    d = faults.find("sensor_delay", code)
    if d is not None:
        await asyncio.sleep(float(d.params["ms"]) / 1000)
    return True


def _crc_corrupt(faults: FaultManager, code: str, rng: Any) -> bool:
    f = faults.find("crc_error", code)
    return f is not None and rng.random() < float(f.params["ratio"])


class RtuBusServer(_TcpServerBase):
    """RS-485 버스 하나. 한 포트에 여러 slave를 두고 반이중으로 한 번에 한 요청만 처리한다."""

    def __init__(self, bus_id: str, host: str, port: int, devices: dict[int, DeviceModel], faults: FaultManager,
                 baud: int) -> None:
        super().__init__(host, port)
        self.bus_id = bus_id
        self.devices = devices
        self.faults = faults
        self.baud = baud
        self._line = asyncio.Lock()

    def _wire_delay(self, nbytes: int) -> float:
        return nbytes * 11 / self.baud

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            try:
                req = await read_rtu_frame(reader, request=True)
            except FrameErr:
                continue
            async with self._line:
                resp = await self._handle(req)
            if resp is not None:
                writer.write(resp)
                await writer.drain()

    async def _handle(self, req: bytes) -> bytes | None:
        await asyncio.sleep(self._wire_delay(len(req)))
        if self.faults.has("bus_cut", self.bus_id) or not crc_ok(req):
            return None
        unit, fc = req[0], req[1]
        dev = self.devices.get(unit)
        if dev is None:
            return None  # 없는 주소는 실제 버스처럼 무응답
        if not await _apply_device_faults(self.faults, dev.code):
            return None
        if fc not in READ_FCS:
            pdu = exception_pdu(fc, EXC_ILLEGAL_FUNCTION)
        else:
            addr, count = int.from_bytes(req[2:4], "big"), int.from_bytes(req[4:6], "big")
            try:
                pdu = words_pdu(fc, dev.read(fc, addr, count))
            except ExceptionResponse as exc:
                pdu = exception_pdu(fc, exc.code)
        resp = with_crc(bytes([unit]) + pdu)
        if _crc_corrupt(self.faults, dev.code, dev.rng):
            resp = resp[:-1] + bytes([resp[-1] ^ 0xFF])
        await asyncio.sleep(self._wire_delay(len(resp)))
        return resp


class ModbusTcpDeviceServer(_TcpServerBase):
    """Ethernet 장비 한 대 (Modbus TCP 서버). 읽기 FC만 받는다."""

    def __init__(self, host: str, port: int, device: DeviceModel, faults: FaultManager) -> None:
        super().__init__(host, port)
        self.device = device
        self.faults = faults

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            tid, unit, pdu = await read_mbap(reader)
            if not await _apply_device_faults(self.faults, self.device.code):
                continue
            fc = pdu[0]
            if fc not in READ_FCS or len(pdu) != 5:
                out = exception_pdu(fc, EXC_ILLEGAL_FUNCTION)
            else:
                addr, count = int.from_bytes(pdu[1:3], "big"), int.from_bytes(pdu[3:5], "big")
                try:
                    out = words_pdu(fc, self.device.read(fc, addr, count))
                except ExceptionResponse as exc:
                    out = exception_pdu(fc, exc.code)
            if _crc_corrupt(self.faults, self.device.code, self.device.rng):
                out = out[:-1]  # TCP에는 CRC가 없으므로 잘린 프레임으로 흉내 낸다
            writer.write(mbap(tid, unit, out))
            await writer.drain()


class AsciiScaleServer(_TcpServerBase):
    """RS-232 저울 (TCP로 감싼 직렬). 'Q\\r\\n' 요청 → 'ST,GS,+0010.250kg\\r\\n' 응답."""

    def __init__(self, host: str, port: int, model: ScaleModel, faults: FaultManager) -> None:
        super().__init__(host, port)
        self.model = model
        self.faults = faults

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            line = await reader.readline()
            if not line:
                return
            if line.strip() != b"Q":
                continue
            if not await _apply_device_faults(self.faults, self.model.code):
                continue
            await asyncio.sleep(20 * 11 / 9600)
            state, w = self.model.measure()
            sign = "+" if w >= 0 else "-"
            msg = f"{state},GS,{sign}{abs(w):08.3f}kg\r\n"
            if _crc_corrupt(self.faults, self.model.code, self.model.rng):
                msg = "S?,G#," + msg[6:9] + "\r\n"
            writer.write(msg.encode("ascii"))
            await writer.drain()


class TapingOpcUaServer:
    """아이스박스자동포장기 KF 100 OPC-UA 서버 (asyncua)."""

    NS_URI = "urn:limjingang:kf100"

    def __init__(self, host: str, port: int, model: TapingMachineModel) -> None:
        self.endpoint = f"opc.tcp://{host}:{port}/"
        self.model = model
        self._server: Any = None
        self._nodes: dict[str, Any] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        from asyncua import Server, ua

        for name in ("asyncua", "asyncua.server", "asyncua.common"):
            logging.getLogger(name).setLevel(logging.ERROR)
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("KF 100 Ice-box Taping Machine (twin)")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        idx = await server.register_namespace(self.NS_URI)
        obj = await server.nodes.objects.add_object(ua.NodeId("KF100", idx), "KF100")
        specs = {
            "PackCount": (ua.VariantType.UInt32, 0),
            "Running": (ua.VariantType.Boolean, True),
            "RunMinutes": (ua.VariantType.Double, 0.0),
            "AlarmCode": (ua.VariantType.UInt16, 0),
        }
        for name, (vt, init) in specs.items():
            node = await obj.add_variable(ua.NodeId(f"KF100.{name}", idx), name, ua.Variant(init, vt))
            self._nodes[name] = (node, vt)
        await server.start()
        self._server = server
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        from asyncua import ua

        while True:
            v = self.model.effective()
            vals = {
                "PackCount": int(v["pack_count"]),
                "Running": bool(v["running"]),
                "RunMinutes": float(v["run_minutes"]),
                "AlarmCode": int(v["alarm_code"]),
            }
            for name, val in vals.items():
                node, vt = self._nodes[name]
                with contextlib.suppress(Exception):
                    await node.write_value(ua.Variant(val, vt))
            await asyncio.sleep(0.2)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._server is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.stop(), 3)
            self._server = None
