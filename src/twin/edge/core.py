"""Edge 공통 자료형·정규화·노이즈 필터·로컬 버퍼 (spec 5장, EDG-03~09)."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from twin.common.config import Equip, Item
from twin.common.util import iso


@dataclass
class Sample:
    """장비 1대의 한 번 수집 결과 (공학값)."""

    equip: Equip
    collect_dt: Any  # datetime (KST)
    values: dict[str, float]
    tag_addrs: dict[str, str]
    priority: int = 1


def fmt_value(v: float, it: Item) -> str:
    """스케일 자릿수에 맞춰 문자열로 (0.01 → 소수 2자리)."""
    if it.type == "float":
        return f"{v:.3f}"
    if it.scale >= 1:
        return str(int(round(v)))
    digits = max(0, -int(math.floor(math.log10(it.scale) + 1e-9)))
    return f"{v:.{digits}f}"


def to_raw_items(s: Sample) -> list[dict[str, Any]]:
    """샘플을 IF_SENSOR_RAW 형식 항목 목록으로 바꾼다 (msg_id는 버퍼가 붙인다)."""
    out = []
    for it in s.equip.items:
        if it.key not in s.values:
            continue
        out.append({
            "equip_code": s.equip.code,
            "item_key": it.key,
            "tag_addr": s.tag_addrs.get(it.key, ""),
            "data_type": it.data_type,
            "raw_value": fmt_value(s.values[it.key], it),
            "unit_cd": it.unit,
            "comm_type": s.equip.comm_type,
            "target_table": s.equip.target,
            "resend_yn": "N",
            "collect_dt": iso(s.collect_dt),
        })
    return out


@dataclass
class NoiseFilter:
    """물리 범위·급변 필터. 급변이 3회 연속 같은 방향으로 이어지면 실제 변화로 받아들인다."""

    last: dict[tuple[str, str], float] = field(default_factory=dict)
    pending: dict[tuple[str, str], int] = field(default_factory=dict)
    filtered: dict[str, int] = field(default_factory=dict)
    recent: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, s: Sample) -> Sample:
        keep: dict[str, float] = {}
        for it in s.equip.items:
            if it.key not in s.values:
                continue
            v = s.values[it.key]
            if self._accept(s.equip.code, it, v):
                keep[it.key] = v
            else:
                self.filtered[s.equip.code] = self.filtered.get(s.equip.code, 0) + 1
                self.recent.append({"equip": s.equip.code, "key": it.key, "value": v, "ts": iso(s.collect_dt)})
                del self.recent[:-50]
        s.values = keep
        return s

    def _accept(self, code: str, it: Item, v: float) -> bool:
        k = (code, it.key)
        if it.range is not None and not (it.range[0] <= v <= it.range[1]):
            return False
        prev = self.last.get(k)
        if it.max_step is not None and prev is not None and abs(v - prev) > it.max_step:
            n = self.pending.get(k, 0) + 1
            self.pending[k] = n
            if n < 3:
                return False
        self.pending[k] = 0
        self.last[k] = v
        return True


class Buffer:
    """Edge 로컬 버퍼 (SQLite WAL). 한 행 = 한 샘플 (D-005)."""

    def __init__(self, path: Path, edge_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS buffer (id INTEGER PRIMARY KEY AUTOINCREMENT, priority INTEGER, "
            "created_at REAL, attempts INTEGER DEFAULT 0, buffered INTEGER DEFAULT 0, n_items INTEGER, payload TEXT)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_buf ON buffer(priority, id)")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)")
        self.edge_id = edge_id

    def _meta(self, k: str) -> int:
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return int(row[0]) if row else 0

    def _bump(self, k: str, n: int = 1) -> int:
        self.db.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = v + ?", (k, n, n))
        return self._meta(k)

    def enqueue(self, items: list[dict[str, Any]], priority: int, buffered: bool) -> list[str]:
        """msg_id를 붙여 저장한다. 카운터는 재시작해도 이어진다(meta.seq)."""
        if not items:
            return []
        self.db.execute("BEGIN IMMEDIATE")
        try:
            end = self._bump("seq", len(items))
            start = end - len(items) + 1
            ids = []
            for i, it in enumerate(items):
                it["msg_id"] = f"{self.edge_id}-{start + i:012d}"
                ids.append(it["msg_id"])
            self.db.execute(
                "INSERT INTO buffer(priority, created_at, buffered, n_items, payload) VALUES(?,?,?,?,?)",
                (priority, time.time(), 1 if buffered else 0, len(items), json.dumps(items, ensure_ascii=False)),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return ids

    def next_batch(self, max_items: int) -> list[tuple[int, int, int, list[dict[str, Any]]]]:
        """(행 id, attempts, buffered, 항목들) — 우선순위 → 입력 순서."""
        rows = self.db.execute(
            "SELECT id, attempts, buffered, n_items, payload FROM buffer ORDER BY priority, id LIMIT ?", (max_items,)
        ).fetchall()
        out, total = [], 0
        for rid, att, buf, n, payload in rows:
            if out and total + n > max_items:
                break
            out.append((rid, att, buf, json.loads(payload)))
            total += n
        return out

    def ack(self, row_ids: list[int], n_items: int, resent: int) -> None:
        self.db.executemany("DELETE FROM buffer WHERE id=?", [(r,) for r in row_ids])
        self._bump("sent", n_items)
        if resent:
            self._bump("resent", resent)

    def mark_failed_all(self) -> None:
        """전송 실패: 대기 중인 모든 행을 '버퍼링 복구분'으로 표시한다."""
        self.db.execute("UPDATE buffer SET attempts = attempts + 1, buffered = 1")

    def purge(self, retention_hours: float) -> int:
        cut = time.time() - retention_hours * 3600
        rows = self.db.execute("SELECT COALESCE(SUM(n_items),0) FROM buffer WHERE created_at < ?", (cut,)).fetchone()
        n = int(rows[0])
        if n:
            self.db.execute("DELETE FROM buffer WHERE created_at < ?", (cut,))
            self._bump("purged", n)
        return n

    def stats(self) -> dict[str, Any]:
        samples, items, oldest = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(n_items),0), MIN(created_at) FROM buffer"
        ).fetchone()
        return {
            "pending_samples": samples,
            "pending_items": int(items),
            "oldest": iso_ts(oldest) if oldest else None,
            "sent_total": self._meta("sent"),
            "resent_total": self._meta("resent"),
            "purged_total": self._meta("purged"),
            "seq": self._meta("seq"),
        }

    def close(self) -> None:
        self.db.close()


def iso_ts(epoch: float) -> str:
    from datetime import datetime

    from twin.common.util import KST

    return iso(datetime.fromtimestamp(epoch, KST))
