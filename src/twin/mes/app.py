"""MES 스텁 HTTP API (spec 10장): 수집 적재, 조회, 알람, 시뮬레이션 제어, WebSocket, 대시보드 정적 파일."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from twin.common.util import iso, now_kst
from twin.field.faults import FaultError
from twin.mes.store import DIST_TABLES
from twin.mes.views import diag_of, equip_row, plc_labels, summary, topology

if TYPE_CHECKING:
    from twin.supervisor import Twin

DIST_DIR = Path(__file__).resolve().parents[3] / "dashboard" / "dist"


class RawItemIn(BaseModel):
    equip_code: str
    item_key: str
    tag_addr: str
    data_type: str
    raw_value: str
    unit_cd: str | None = None
    comm_type: str
    target_table: str | None = None
    resend_yn: str = "N"
    collect_dt: str
    msg_id: str


class RawBatchIn(BaseModel):
    edge_id: str
    items: list[RawItemIn]


class FaultIn(BaseModel):
    target: str
    type: str
    params: dict[str, Any] = {}
    duration_s: float | None = None


def create_app(twin: Twin) -> FastAPI:
    app = FastAPI(title="임진강김치 MES 스텁 · 수집 트윈 API", version="0.1.0")
    cfg = twin.cfg

    # ── 수집 적재 (Edge → MES) ──
    @app.post("/api/if/sensor-raw")
    async def sensor_raw(batch: RawBatchIn) -> dict[str, Any]:
        accepted = twin.mes.ingest([i.model_dump() for i in batch.items])
        return {"accepted": accepted, "count": len(accepted)}

    # ── 조회 ──
    @app.get("/api/summary")
    async def get_summary() -> dict[str, Any]:
        return summary(twin)

    @app.get("/api/topology")
    async def get_topology() -> dict[str, Any]:
        return topology(twin)

    @app.get("/api/equip")
    async def list_equip() -> list[dict[str, Any]]:
        return [equip_row(twin, e.code) for e in cfg.equipment]

    def _code(code: str) -> str:
        try:
            cfg.equip(code)
        except KeyError as exc:
            raise HTTPException(404, f"설비 없음 {code}") from exc
        return code

    @app.get("/api/equip/{code}")
    async def get_equip(code: str) -> dict[str, Any]:
        return equip_row(twin, _code(code))

    @app.get("/api/equip/{code}/frames")
    async def frames(code: str, limit: int = Query(50, le=50)) -> list[dict[str, Any]]:
        d = diag_of(twin, _code(code))
        if d is None:
            return []
        return [f.__dict__ for f in list(d.frames)[-limit:]][::-1]

    @app.get("/api/equip/{code}/history")
    async def history(code: str, minutes: int = Query(60, le=1440)) -> dict[str, Any]:
        eid = twin.mes.equip_id[_code(code)]
        since = iso(now_kst() - timedelta(minutes=minutes))
        rows = twin.mes.db.execute(
            "SELECT ITEM_KEY, RAW_VALUE, COLLECT_DT FROM IF_SENSOR_RAW WHERE EQUIP_ID=? AND COLLECT_DT>=? ORDER BY RAW_ID"
            " DESC LIMIT 8000",
            (eid, since),
        ).fetchall()
        series: dict[str, list[tuple[str, float]]] = {}
        for key, val, ts in reversed(rows):
            series.setdefault(key, []).append((ts, float(val)))
        return {"code": code, "series": series}

    @app.get("/api/raw")
    async def raw(
        equip: str | None = None,
        resend: str | None = None,
        limit: int = Query(200, le=2000),
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT r.RAW_ID, e.EQUIP_CODE, r.TAG_ADDR, r.DATA_TYPE, r.RAW_VALUE, r.UNIT_CD, r.COMM_TYPE,"
            " r.TARGET_TABLE, r.RESEND_YN, r.COLLECT_DT, r.MSG_ID, r.ITEM_KEY, r.RECEIVED_DT FROM IF_SENSOR_RAW r"
            " JOIN BAS_EQUIP e ON e.EQUIP_ID = r.EQUIP_ID WHERE 1=1"
        )
        params: list[Any] = []
        if equip:
            sql += " AND e.EQUIP_CODE=?"
            params.append(equip)
        if resend in ("Y", "N"):
            sql += " AND r.RESEND_YN=?"
            params.append(resend)
        if since:
            sql += " AND r.COLLECT_DT>=?"
            params.append(since)
        sql += " ORDER BY r.RAW_ID DESC LIMIT ?"
        params.append(limit)
        return twin.mes.rows(sql, tuple(params))

    @app.get("/api/tables/stats")
    async def table_stats() -> dict[str, Any]:
        return {
            "counts": twin.mes.table_counts(),
            "ingested": twin.mes.ingested,
            "duplicates": twin.mes.dup,
            "last_ingest": twin.mes.last_ingest,
        }

    @app.get("/api/tables/{table}")
    async def table(table: str, limit: int = Query(100, le=1000)) -> list[dict[str, Any]]:
        if table not in DIST_TABLES + ["BAS_EQUIP", "BAS_CCP_STD", "ORD_WORK_ORDER"]:
            raise HTTPException(404, f"조회할 수 없는 테이블 {table}")
        return twin.mes.rows(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT ?", (limit,))  # noqa: S608

    @app.get("/api/tanks")
    async def tanks() -> list[dict[str, Any]]:
        field_state = twin.field.tank_states()
        out = []
        for n in sorted(cfg.tanks):
            opr = twin.mes.rows(
                "SELECT o.TANK_OPR_ID, o.TARGET_SALINITY, o.PLAN_HOURS, o.START_DT, (SELECT SALINITY_VALUE FROM"
                " SLT_SALINITY_LOG s WHERE s.TANK_OPR_ID=o.TANK_OPR_ID ORDER BY SALINITY_LOG_ID DESC LIMIT 1) AS LAST,"
                " (SELECT MEASURE_DT FROM SLT_SALINITY_LOG s WHERE s.TANK_OPR_ID=o.TANK_OPR_ID ORDER BY SALINITY_LOG_ID"
                " DESC LIMIT 1) AS LAST_DT, (SELECT ALARM_YN FROM SLT_SALINITY_LOG s WHERE s.TANK_OPR_ID=o.TANK_OPR_ID"
                " ORDER BY SALINITY_LOG_ID DESC LIMIT 1) AS ALARM_YN FROM SLT_TANK_OPR o WHERE o.TANK_NO=? AND"
                " o.TANK_STATUS='절임중' ORDER BY o.TANK_OPR_ID DESC LIMIT 1",
                (n,),
            )
            row = opr[0] if opr else {}
            fs = field_state.get(n, {})
            elapsed = None
            if row.get("START_DT"):
                from twin.common.util import parse_iso

                elapsed = round((now_kst() - parse_iso(row["START_DT"])).total_seconds() / 3600, 1)
            out.append(
                {
                    "tank": n,
                    "target": row.get("TARGET_SALINITY"),
                    "plan_hours": row.get("PLAN_HOURS"),
                    "elapsed_h": elapsed,
                    "salinity": row.get("LAST"),
                    "measured_at": row.get("LAST_DT"),
                    "alarm": row.get("ALARM_YN") == "Y",
                    "sensor": fs.get("sensor"),
                    "measuring": fs.get("measuring", False),
                }
            )
        return out

    @app.get("/api/plc/{plc_id}/memory")
    async def plc_memory(plc_id: str, start: int = 100, count: int = Query(900, le=1000)) -> dict[str, Any]:
        plc_id = plc_id.upper()
        if plc_id not in twin.plcs:
            raise HTTPException(404, f"PLC 없음 {plc_id}")
        p = twin.plcs[plc_id]
        labels = plc_labels(twin, plc_id)
        return {
            "plc": plc_id,
            "start": start,
            "words": p.memory.read(start, count),
            "running": p.running,
            "labels": {f"D{k:04d}": v for k, v in labels.items() if start <= k < start + count},
            "diag": p.diag_snapshot(),
            "write_rejections": p.write_rejections[-20:],
        }

    @app.get("/api/edge/buffer")
    async def edge_buffer() -> dict[str, Any]:
        return twin.edge.status()

    @app.get("/api/ccp")
    async def ccp() -> list[dict[str, Any]]:
        return [r.model_dump() for r in cfg.ccp]

    # ── 알람 ──
    @app.get("/api/alarms")
    async def alarms(
        active: bool = False,
        category: str | None = None,
        equip: str | None = None,
        limit: int = Query(200, le=2000),
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM TWIN_ALARM WHERE 1=1"
        params: list[Any] = []
        if active:
            sql += " AND STATE IN ('RAISED','ACKED')"
        if category:
            sql += " AND CATEGORY=?"
            params.append(category)
        if equip:
            sql += " AND EQUIP_CODE=?"
            params.append(equip)
        sql += " ORDER BY ALARM_ID DESC LIMIT ?"
        params.append(limit)
        return [{k.lower(): v for k, v in r.items()} for r in twin.mes.rows(sql, tuple(params))]

    @app.post("/api/alarms/{aid}/ack")
    async def ack(aid: int) -> dict[str, Any]:
        out = twin.mes.alarms.ack(aid)
        if out is None:
            raise HTTPException(404, "알람 없음")
        return out

    # ── 시뮬레이션 제어 ──
    @app.get("/api/sim/catalog")
    async def catalog() -> list[dict[str, Any]]:
        items = twin.faults.catalog()
        keys = {e.code: [i.key for i in e.items] for e in cfg.equipment}
        for it in items:
            if "key" in it["params"]:
                it["keys"] = keys
        return items

    @app.get("/api/sim/faults")
    async def list_faults() -> list[dict[str, Any]]:
        return [f.to_dict() for f in twin.faults.active()]

    @app.post("/api/sim/faults")
    async def add_fault(f: FaultIn) -> dict[str, Any]:
        try:
            res = await twin.apply_fault(f.target, f.type, f.params, f.duration_s)
        except FaultError as exc:
            raise HTTPException(400, str(exc)) from exc
        return (
            res.to_dict()
            if res is not None
            else {"id": None, "type": f.type, "target": f.target, "instant": True}
        )

    @app.delete("/api/sim/faults/{fid}")
    async def del_fault(fid: str) -> dict[str, Any]:
        if not twin.faults.remove(fid):
            raise HTTPException(404, "고장 없음")
        return {"removed": fid}

    @app.delete("/api/sim/faults")
    async def clear_faults() -> dict[str, Any]:
        twin.faults.clear()
        return {"cleared": True}

    @app.get("/api/sim/scenarios")
    async def scenarios() -> dict[str, Any]:
        return {k: [s.model_dump() for s in v] for k, v in cfg.scenarios.items()}

    @app.post("/api/sim/scenarios/{name}/run")
    async def run_scenario(name: str) -> dict[str, Any]:
        if name not in cfg.scenarios:
            raise HTTPException(404, "시나리오 없음")
        return {"started": twin.run_scenario(name)}

    @app.get("/api/meta")
    async def meta() -> dict[str, Any]:
        return {
            "processes": list(
                dict.fromkeys(
                    [
                        "입고/보관",
                        "절단/전처리",
                        "세척/절임",
                        "세척/선별",
                        "탈수",
                        "혼합(버무림)",
                        "금속검출",
                        "포장/출고",
                        "냉장·숙성",
                    ]
                )
            ),
            "plcs": {k: v.model_dump() for k, v in cfg.plcs.items()},
            "buses": {k: v.model_dump() for k, v in cfg.buses.items()},
        }

    # ── DB 일일 정리 (D-017) ──
    @app.get("/api/admin/purge")
    async def purge_status() -> dict[str, Any]:
        pc = cfg.runtime.mes.purge
        return {
            "enabled": pc.enabled,
            "at": pc.at,
            "keep_hours": pc.keep_hours,
            "next": twin.next_purge(),
            "db_bytes": twin.mes.db_bytes(),
            "history": twin.mes.purge_history(),
        }

    @app.post("/api/admin/purge")
    async def purge_run() -> dict[str, Any]:
        return twin.purge_now("MANUAL")

    # ── WebSocket ──
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        snap = {
            "summary": summary(twin),
            "topology": topology(twin),
            "alarms": [
                {k.lower(): v for k, v in r.items()}
                for r in twin.mes.rows(
                    "SELECT * FROM TWIN_ALARM WHERE STATE IN ('RAISED','ACKED') ORDER BY ALARM_ID DESC"
                )
            ],
            "values": {c: v for c, v in twin.mes.last_values.items()},
        }
        await twin.hub.add(sock, snap)
        try:
            while True:
                await sock.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            twin.hub.remove(sock)

    # ── 대시보드 정적 파일 (빌드된 경우) ──
    if twin.serve_static and DIST_DIR.exists():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            f = DIST_DIR / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(DIST_DIR / "index.html")

    return app
