"""알람 엔진: CCP 기준 이탈(지속시간 조건)·이벤트 알람·통신 알람 (spec 6.3, D-006)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from twin.common.config import CcpRule
from twin.common.util import iso, now_kst, parse_iso

Publish = Callable[[dict[str, Any]], None]
ACTIVE = ("RAISED", "ACKED")


class AlarmEngine:
    """조건 알람은 이탈이 hold_sec 이상 이어지면 발생하고, 정상으로 돌아오면 해제된다."""

    def __init__(self, db: sqlite3.Connection, rules: list[CcpRule], publish: Publish) -> None:
        self.db = db
        self.rules = {r.id: r for r in rules}
        self.by_equip: dict[str, list[CcpRule]] = {}
        for r in rules:
            for code in r.equip:
                self.by_equip.setdefault(code, []).append(r)
        self.publish = publish
        self.timers: dict[tuple[str, str, str], datetime] = {}
        self.active: dict[tuple[str, str, str], int] = {}
        for aid, rule, equip, sub in db.execute(
            "SELECT ALARM_ID, RULE_ID, EQUIP_CODE, COALESCE(VALUE_KEY,'') FROM TWIN_ALARM WHERE STATE IN ('RAISED','ACKED')"
        ):
            self.active[(rule, equip, sub)] = aid

    def rules_for(self, code: str) -> list[CcpRule]:
        return self.by_equip.get(code, [])

    @staticmethod
    def deviates(rule: CcpRule, value: float, target: float | None = None) -> bool:
        if rule.low is not None and value < rule.low:
            return True
        if rule.high is not None and value > rule.high:
            return True
        if rule.band is not None and target is not None and abs(value - target) > rule.band:
            return True
        if rule.band_pct is not None and rule.std:
            return abs(value - rule.std) / rule.std * 100 > rule.band_pct
        return False

    @staticmethod
    def describe(rule: CcpRule, target: float | None = None) -> str:
        if rule.band is not None and target is not None:
            return f"목표 {target:g}±{rule.band:g}{rule.unit}"
        if rule.band_pct is not None and rule.std:
            return f"기준 {rule.std:g}{rule.unit} ±{rule.band_pct:g}%"
        parts = []
        if rule.low is not None:
            parts.append(f"{rule.low:g}{rule.unit} 이상")
        if rule.high is not None:
            parts.append(f"{rule.high:g}{rule.unit} 이하")
        return "기준 " + " · ".join(parts)

    # ── 조건 알람 ──
    def check(self, rule: CcpRule, equip: str, value: float, ts: str, sub: str = "",
              target: float | None = None, label: str = "") -> tuple[bool, int | None]:
        """(이탈 여부, 이번에 발생한 알람 ID)."""
        key = (rule.id, equip, sub)
        dev = self.deviates(rule, value, target)
        t = parse_iso(ts)
        if not dev:
            self.timers.pop(key, None)
            if key in self.active:
                self._clear(key, ts)
            return False, None
        start = self.timers.setdefault(key, t)
        if key in self.active or (t - start).total_seconds() < rule.hold_sec:
            return True, None
        hold = f", {rule.hold_sec:g}초 지속" if rule.hold_sec else ""
        msg = f"{label or equip} {rule.item} {value:g}{rule.unit} ({self.describe(rule, target)}{hold})"
        return True, self._raise("CCP", rule.id, rule.item, equip, rule.severity, msg, f"{value:g}", iso(start), sub)

    # ── 이벤트 알람 (금속 NG, 중량 이탈) ──
    def event(self, rule: CcpRule, equip: str, value: str, ts: str, msg: str) -> int:
        key = (rule.id, equip, "")
        if key in self.active:
            aid = self.active[key]
            self.db.execute("UPDATE TWIN_ALARM SET MESSAGE=?, VALUE=?, RAISED_DT=?, STATE='RAISED' WHERE ALARM_ID=?",
                            (msg, value, ts, aid))
            self.publish({"type": "alarm", **self.get(aid)})
            return aid
        return self._raise("CCP", rule.id, rule.item, equip, rule.severity, msg, value, ts, "")

    # ── 통신 알람 ──
    def comm(self, key_id: str, equip: str, bad: bool, severity: str, msg: str, hold_s: float = 3.0) -> None:
        key = ("COMM", equip, key_id)
        ts = iso(now_kst())
        if not bad:
            self.timers.pop(key, None)
            if key in self.active:
                self._clear(key, ts)
            return
        start = self.timers.setdefault(key, now_kst())
        if key not in self.active and (now_kst() - start).total_seconds() >= hold_s:
            self._raise("COMM", "COMM", key_id, equip, severity, msg, None, iso(start), key_id)

    # ── 저장 ──
    def _raise(self, cat: str, rule_id: str, item: str, equip: str, sev: str, msg: str, value: str | None,
               ts: str, sub: str) -> int:
        cur = self.db.execute(
            "INSERT INTO TWIN_ALARM(CATEGORY, RULE_ID, ITEM, EQUIP_CODE, SEVERITY, MESSAGE, VALUE, VALUE_KEY, STATE, "
            "RAISED_DT) VALUES(?,?,?,?,?,?,?,?,'RAISED',?)",
            (cat, rule_id, item, equip, sev, msg, value, sub, ts),
        )
        aid = int(cur.lastrowid or 0)
        self.active[(rule_id if cat == "CCP" else "COMM", equip, sub)] = aid
        self.publish({"type": "alarm", **self.get(aid)})
        return aid

    def _clear(self, key: tuple[str, str, str], ts: str) -> None:
        aid = self.active.pop(key)
        self.db.execute("UPDATE TWIN_ALARM SET STATE='CLEARED', CLEARED_DT=? WHERE ALARM_ID=?", (ts, aid))
        self.publish({"type": "alarm", **self.get(aid)})

    def ack(self, aid: int) -> dict[str, Any] | None:
        row = self.get(aid)
        if row is None:
            return None
        ts = iso(now_kst())
        rule = self.rules.get(row["rule_id"])
        is_event = rule is not None and (rule.ng_immediate or rule.band_pct is not None)
        if row["state"] == "RAISED":
            if is_event:
                self.db.execute("UPDATE TWIN_ALARM SET STATE='CLEARED', ACKED_DT=?, CLEARED_DT=? WHERE ALARM_ID=?",
                                (ts, ts, aid))
                for k, v in list(self.active.items()):
                    if v == aid:
                        del self.active[k]
            else:
                self.db.execute("UPDATE TWIN_ALARM SET STATE='ACKED', ACKED_DT=? WHERE ALARM_ID=?", (ts, aid))
        out = self.get(aid)
        if out:
            self.publish({"type": "alarm", **out})
        return out

    def get(self, aid: int) -> dict[str, Any] | None:
        cur = self.db.execute("SELECT * FROM TWIN_ALARM WHERE ALARM_ID=?", (aid,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0].lower() for c in cur.description]
        return dict(zip(cols, row, strict=True))
