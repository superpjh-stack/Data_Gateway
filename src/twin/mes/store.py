"""MES 스텁 저장소: 스키마·기준정보 시드, 수집 원장 적재, 공정 테이블 분배 (spec 6장)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from twin.common.config import CcpRule, Equip, TwinConfig
from twin.common.util import get_logger, iso, now_kst, parse_iso
from twin.mes.alarms import AlarmEngine

log = get_logger("mes")
Publish = Callable[[dict[str, Any]], None]

PROCESSES = ["입고/보관", "절단/전처리", "세척/절임", "세척/선별", "탈수", "혼합(버무림)", "금속검출", "포장/출고", "냉장·숙성"]
DIST_TABLES = ["IF_SENSOR_RAW", "SLT_SALINITY_LOG", "WSH_SANITIZER_LOG", "AGE_ENV_LOG", "AGE_ENV_ALARM", "QUA_METAL_LOG",
               "PKG_TAPING_LOG", "PKG_WEIGHT_INSP", "MIX_FILLER_LOG", "EQP_RUN_LOG", "SLT_TANK_OPR", "TWIN_ALARM"]
WORK_ORDER_ID = 1
LOT_NO = "L260921-01"
ITEM_ID = 1


def plc_tag(cfg: TwinConfig, e: Equip) -> str:
    base = cfg.block_base(e.code)
    if base:
        return f"{base[0]}.D{base[1]:04d}"
    if e.kind == "edge_opcua":
        return "OPCUA.ns=2;s=KF100"
    if e.kind == "edge_ascii":
        return f"SERIAL.{e.code}"
    return f"{e.code}.HR40001"


class MesStore:
    """MES DB와 수집 처리. 이벤트 루프 스레드에서만 쓴다."""

    def __init__(self, cfg: TwinConfig, publish: Publish) -> None:
        self.cfg = cfg
        path = Path(cfg.runtime.data_dir) / "mes.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
        self.publish = publish
        self._seed()
        self.equip_id = {c: i for i, c in self.db.execute("SELECT EQUIP_ID, EQUIP_CODE FROM BAS_EQUIP")}
        self.alarms = AlarmEngine(self.db, cfg.ccp, publish)
        self.last_ingest: str | None = None
        self.ingested = 0
        self.dup = 0
        self.last_values: dict[str, dict[str, Any]] = {}
        self._md_prev: dict[str, tuple[float, float]] = {}
        self._pkg_prev: dict[str, float] = {}
        self._run_state: dict[str, str] = {}

    # ── 시드 ──
    def _seed(self) -> None:
        now = iso(now_kst())
        cfg = self.cfg
        with self.db:
            for e in cfg.equipment:
                pid = PROCESSES.index(e.process) + 1 if e.process in PROCESSES else None
                self.db.execute(
                    "INSERT INTO BAS_EQUIP(EQUIP_CODE, EQUIP_NAME, EQUIP_TYPE, PROCESS_ID, PROCESS_NAME, PLC_TAG, COMM_TYPE,"
                    " COLLECT_ITEM, USE_YN, CREATED_DT) VALUES(?,?,?,?,?,?,?,?, 'Y', ?) ON CONFLICT(EQUIP_CODE) DO UPDATE"
                    " SET EQUIP_NAME=excluded.EQUIP_NAME, PLC_TAG=excluded.PLC_TAG, COMM_TYPE=excluded.COMM_TYPE,"
                    " COLLECT_ITEM=excluded.COLLECT_ITEM, UPDATED_DT=excluded.CREATED_DT",
                    (e.code, e.name, e.type, pid, e.process, plc_tag(cfg, e), e.comm_type,
                     ",".join(i.name for i in e.items), now),
                )
            for r in cfg.ccp:
                self.db.execute(
                    "INSERT INTO BAS_CCP_STD(CCP_CODE, CCP_ITEM, EQUIP_CODES, LOW_LIMIT, HIGH_LIMIT, BAND, UNIT_CD, HOLD_SEC,"
                    " SEVERITY, BASIS, CREATED_DT) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(CCP_CODE) DO UPDATE SET"
                    " LOW_LIMIT=excluded.LOW_LIMIT, HIGH_LIMIT=excluded.HIGH_LIMIT, BAND=excluded.BAND,"
                    " HOLD_SEC=excluded.HOLD_SEC",
                    (r.id, r.item, ",".join(r.equip), r.low, r.high, r.band if r.band is not None else r.band_pct,
                     r.unit, r.hold_sec, r.severity, r.basis, now),
                )
            if not self.db.execute("SELECT 1 FROM ORD_WORK_ORDER").fetchone():
                self.db.execute("INSERT INTO ORD_WORK_ORDER VALUES(?, 'WO-260921-001', ?, ?, ?)",
                                (WORK_ORDER_ID, LOT_NO, ITEM_ID, now))
            if not self.db.execute("SELECT 1 FROM SLT_TANK_OPR").fetchone():
                t0 = now_kst()
                for n, tk in sorted(cfg.tanks.items()):
                    self.db.execute(
                        "INSERT INTO SLT_TANK_OPR(TANK_NO, TARGET_SALINITY, PLAN_HOURS, START_DT, TANK_STATUS)"
                        " VALUES(?,?,?,?, '절임중')",
                        (n, tk.target, tk.hours, iso(t0 - timedelta(hours=tk.offset_h))),
                    )

    # ── 적재 ──
    def ingest(self, items: list[dict[str, Any]]) -> list[str]:
        """IF_SENSOR_RAW에 넣고 새 행만 분배한다. 중복 msg_id는 건너뛰되 수신 확인한다."""
        now = iso(now_kst())
        accepted: list[str] = []
        fresh: list[dict[str, Any]] = []
        self.db.execute("BEGIN")
        try:
            for it in items:
                eid = self.equip_id.get(it["equip_code"])
                accepted.append(it["msg_id"])
                if eid is None:
                    log.warning("unknown_equip", equip=it["equip_code"])
                    continue
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO IF_SENSOR_RAW(EQUIP_ID, TAG_ADDR, DATA_TYPE, RAW_VALUE, UNIT_CD, COMM_TYPE,"
                    " TARGET_TABLE, RESEND_YN, COLLECT_DT, MSG_ID, ITEM_KEY, RECEIVED_DT) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, it["tag_addr"], it["data_type"], it["raw_value"], it.get("unit_cd"), it["comm_type"],
                     it.get("target_table"), it["resend_yn"], it["collect_dt"], it["msg_id"], it["item_key"], now),
                )
                if cur.rowcount:
                    fresh.append(it)
                else:
                    self.dup += 1
            groups: dict[tuple[str, str], dict[str, float]] = {}
            for it in fresh:
                groups.setdefault((it["equip_code"], it["collect_dt"]), {})[it["item_key"]] = float(it["raw_value"])
            for (code, ts), vals in sorted(groups.items(), key=lambda kv: kv[0][1]):
                try:
                    self.route(code, ts, vals)
                except Exception as exc:  # 분배 실패가 원장 적재를 막지 않게
                    log.error("route_error", equip=code, error=repr(exc))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.ingested += len(fresh)
        if fresh:
            self.last_ingest = now
        return accepted

    # ── 분배 ──
    def route(self, code: str, ts: str, vals: dict[str, float]) -> None:
        e = self.cfg.equip(code)
        eid = self.equip_id[code]
        extra: dict[str, Any] = {}
        handler = {
            "SLT_SALINITY_LOG": self._salinity,
            "AGE_ENV_LOG": self._env,
            "WSH_SANITIZER_LOG": self._sanitizer,
            "QUA_METAL_LOG": self._metal,
            "PKG_TAPING_LOG": self._taping,
            "PKG_WEIGHT_INSP": self._weight,
            "MIX_FILLER_LOG": self._filler,
        }.get(e.target)
        if handler is not None:
            extra = handler(e, eid, ts, vals) or {}
        prev = self.last_values.get(code, {}).get("values", {})
        self.last_values[code] = {"values": {**prev, **vals}, "ts": ts, **extra}
        self.publish({"type": "value", "equip": code, "values": vals, "ts": ts, **extra})

    def _rule(self, code: str, key: str) -> CcpRule | None:
        for r in self.alarms.rules_for(code):
            if r.key == key:
                return r
        return None

    def _salinity(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        if "salinity" not in v or "tank_no" not in v:
            return {}
        tank = int(v["tank_no"])
        opr_id, start, hours, target = self._tank_opr(tank, ts)
        elapsed = (parse_iso(ts) - parse_iso(start)).total_seconds() / 3600
        dev = False
        rule = self._rule(e.code, "salinity")
        if rule:
            dev, _ = self.alarms.check(rule, e.code, v["salinity"], ts, sub=f"T{tank}", target=target,
                                       label=f"절임통 {tank}")
        self.db.execute(
            "INSERT INTO SLT_SALINITY_LOG(TANK_OPR_ID, SENSOR_ID, SALINITY_VALUE, ELAPSED_HOURS, ALARM_YN, COLLECT_TYPE,"
            " MEASURE_DT) VALUES(?,?,?,?,?,'PLC 자동',?)",
            (opr_id, e.code, v["salinity"], round(elapsed, 2), "Y" if dev else "N", ts),
        )
        return {"tank": tank, "target": target, "elapsed_h": round(elapsed, 2), "deviating": dev}

    def _tank_opr(self, tank: int, ts: str) -> tuple[int, str, float, float]:
        """절임통의 진행 중 운영건. 계획 시간이 지났으면 완료 처리하고 다음 배치를 연다."""
        while True:
            row = self.db.execute(
                "SELECT TANK_OPR_ID, START_DT, PLAN_HOURS, TARGET_SALINITY FROM SLT_TANK_OPR WHERE TANK_NO=? AND"
                " TANK_STATUS='절임중' ORDER BY TANK_OPR_ID DESC LIMIT 1", (tank,)
            ).fetchone()
            if row is None:
                tk = self.cfg.tanks[tank]
                self.db.execute("INSERT INTO SLT_TANK_OPR(TANK_NO, TARGET_SALINITY, PLAN_HOURS, START_DT, TANK_STATUS)"
                                " VALUES(?,?,?,?, '절임중')", (tank, tk.target, tk.hours, ts))
                continue
            opr_id, start, hours, target = row
            end = parse_iso(start) + timedelta(hours=float(hours))
            if parse_iso(ts) < end:
                return int(opr_id), str(start), float(hours), float(target)
            self.db.execute("UPDATE SLT_TANK_OPR SET TANK_STATUS='완료', END_DT=? WHERE TANK_OPR_ID=?", (iso(end), opr_id))
            self.db.execute("INSERT INTO SLT_TANK_OPR(TANK_NO, TARGET_SALINITY, PLAN_HOURS, START_DT, TANK_STATUS)"
                            " VALUES(?,?,?,?, '절임중')", (tank, target, hours, iso(end)))

    def _env(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        temp = v.get("pv", v.get("temp"))
        cur = self.db.execute(
            "INSERT INTO AGE_ENV_LOG(EQUIP_ID, SENSOR_ID, TEMP_VALUE, HUMID_VALUE, SET_TEMP, COMM_TYPE, COLLECT_DT)"
            " VALUES(?,?,?,?,?, 'RS-485 → PLC → 수집서버', ?)",
            (eid, e.code, temp, v.get("humid"), v.get("sv"), ts),
        )
        env_id = cur.lastrowid
        dev_any = False
        for rule in self.alarms.rules_for(e.code):
            if rule.key in v:
                dev, aid = self.alarms.check(rule, e.code, v[rule.key], ts, label=e.name)
                dev_any = dev_any or dev
                if aid:
                    ccp_id = self.db.execute("SELECT CCP_STD_ID FROM BAS_CCP_STD WHERE CCP_CODE=?", (rule.id,)).fetchone()
                    self.db.execute(
                        "INSERT INTO AGE_ENV_ALARM(ENV_LOG_ID, CCP_STD_ID, ALARM_ITEM, ALARM_VALUE, CONFIRM_YN, ALARM_DT,"
                        " CREATED_DT) VALUES(?,?,?,?, 'N', ?, ?)",
                        (env_id, ccp_id[0] if ccp_id else None, "온도" if rule.key in ("pv", "temp") else "습도",
                         v[rule.key], ts, iso(now_kst())),
                    )
        return {"deviating": dev_any}

    def _sanitizer(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        if "ppm" not in v:
            return {}
        dev = False
        rule = self._rule(e.code, "ppm")
        if rule:
            dev, _ = self.alarms.check(rule, e.code, v["ppm"], ts, label="소독수")
        self.db.execute(
            "INSERT INTO WSH_SANITIZER_LOG(EQUIP_ID, WORK_ORDER_ID, PPM_VALUE, CONTACT_TIME, DOSING_RATE, ALARM_YN,"
            " COLLECT_DT) VALUES(?,?,?,?,?,?,?)",
            (eid, WORK_ORDER_ID, v["ppm"], v.get("contact_min"), v.get("dosing_rate"), "Y" if dev else "N", ts),
        )
        return {"deviating": dev}

    def _metal(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        if "inspect_cnt" not in v or "ng_cnt" not in v:
            return {}
        cur = (v["inspect_cnt"], v["ng_cnt"])
        prev = self._md_prev.get(e.code)
        self._md_prev[e.code] = cur
        if prev is None or cur[0] < prev[0]:
            return {}
        d_insp, d_ng = cur[0] - prev[0], max(0.0, cur[1] - prev[1])
        if d_insp <= 0 and d_ng <= 0:
            return {}
        ng = d_ng > 0
        self.db.execute(
            "INSERT INTO QUA_METAL_LOG(EQUIP_ID, WORK_ORDER_ID, LOT_NO, DETECT_RESULT, INSPECT_QTY, NG_QTY, ALARM_YN,"
            " COLLECT_DT) VALUES(?,?,?,?,?,?,?,?)",
            (eid, WORK_ORDER_ID, LOT_NO, "NG" if ng else "OK", d_insp, d_ng, "Y" if ng else "N", ts),
        )
        rule = self._rule(e.code, "ng_cnt")
        if ng and rule:
            self.alarms.event(rule, e.code, f"{int(cur[1])}", ts,
                              f"금속검출 NG {int(d_ng)}건 (누적 {int(cur[1])}건, LOT {LOT_NO}) — 불합격품 격리 확인")
        return {"ng": ng}

    def _run_log(self, e: Equip, eid: int, running: bool, ts: str) -> None:
        """가동/비가동이 바뀌면 열린 구간을 닫고 새 구간을 연다."""
        state = "가동" if running else "비가동"
        prev = self._run_state.get(e.code)
        if prev is None:
            row = self.db.execute("SELECT RUN_STATUS FROM EQP_RUN_LOG WHERE EQUIP_ID=? AND END_DT IS NULL ORDER BY"
                                  " RUN_LOG_ID DESC LIMIT 1", (eid,)).fetchone()
            prev = row[0] if row else None
        if prev == state:
            self._run_state[e.code] = state
            return
        now = iso(now_kst())
        if prev is not None:
            row = self.db.execute("SELECT RUN_LOG_ID, START_DT FROM EQP_RUN_LOG WHERE EQUIP_ID=? AND END_DT IS NULL"
                                  " ORDER BY RUN_LOG_ID DESC LIMIT 1", (eid,)).fetchone()
            if row:
                mins = (parse_iso(ts) - parse_iso(row[1])).total_seconds() / 60
                self.db.execute("UPDATE EQP_RUN_LOG SET END_DT=?, STOP_MINUTES=?, UPDATED_DT=? WHERE RUN_LOG_ID=?",
                                (ts, round(mins, 2) if prev == "비가동" else None, now, row[0]))
        self.db.execute(
            "INSERT INTO EQP_RUN_LOG(EQUIP_ID, RUN_STATUS, STOP_CODE, START_DT, INPUT_TYPE, CREATED_DT)"
            " VALUES(?,?,?,?, '자동 수집', ?)",
            (eid, state, None if running else "SC-AUTO", ts, now),
        )
        self._run_state[e.code] = state

    def _taping(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        if "running" in v:
            self._run_log(e, eid, v["running"] >= 0.5, ts)
        if "pack_count" in v:
            prev = self._pkg_prev.get(e.code)
            self._pkg_prev[e.code] = v["pack_count"]
            if prev is not None and v["pack_count"] > prev:
                self.db.execute(
                    "INSERT INTO PKG_TAPING_LOG(EQUIP_ID, WORK_ORDER_ID, PACK_QTY, RUN_STATUS, RUN_MINUTES, COLLECT_TYPE,"
                    " COLLECT_DT) VALUES(?,?,?,?,?, 'OPC-UA 자동 수집', ?)",
                    (eid, WORK_ORDER_ID, v["pack_count"] - prev, "가동" if v.get("running", 1) >= 0.5 else "정지",
                     v.get("run_minutes"), ts),
                )
        return {}

    def _weight(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        if "weight" not in v:
            return {}
        rule = self._rule(e.code, "weight")
        std = rule.std if rule and rule.std else 10.0
        band = std * (rule.band_pct or 2.0) / 100 if rule else 0.2
        w = v["weight"]
        judge = "합격" if abs(w - std) <= band else ("미달" if w < std else "초과")
        self.db.execute(
            "INSERT INTO PKG_WEIGHT_INSP(WORK_ORDER_ID, ITEM_ID, STD_WEIGHT, MEASURE_WEIGHT, GAP_WEIGHT, JUDGE_RESULT,"
            " INSPECT_DT, CREATED_DT) VALUES(?,?,?,?,?,?,?,?)",
            (WORK_ORDER_ID, ITEM_ID, std, w, round(w - std, 3), judge, ts, iso(now_kst())),
        )
        if judge != "합격" and rule:
            self.alarms.event(rule, e.code, f"{w:.3f}", ts, f"포장 중량 {judge} {w:.3f}kg (기준 {std:g}kg ±{rule.band_pct:g}%)")
        return {"judge": judge}

    def _filler(self, e: Equip, eid: int, ts: str, v: dict[str, float]) -> dict[str, Any]:
        if "run" in v:
            self._run_log(e, eid, v["run"] >= 0.5, ts)
        self.db.execute(
            "INSERT INTO MIX_FILLER_LOG(EQUIP_ID, WORK_ORDER_ID, BATCH_NO, WORK_SPEED, SET_VOLUME, SETTING_JSON,"
            " COLLECT_TYPE, COLLECT_DT) VALUES(?,?,?,?,?,?, 'Modbus TCP 자동 수집', ?)",
            (eid, WORK_ORDER_ID, f"B{ts[2:10].replace('-', '')}-01", v.get("speed"), v.get("set_volume"),
             json.dumps({k: v[k] for k in ("speed", "set_volume") if k in v}), ts),
        )
        return {}

    # ── 조회 ──
    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = self.db.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def table_counts(self) -> dict[str, int]:
        return {t: int(self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in DIST_TABLES}  # noqa: S608

    def close(self) -> None:
        self.db.close()
