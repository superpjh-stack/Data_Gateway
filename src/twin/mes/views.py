"""조회 모델: 장비 상태·토폴로지·요약·PLC 메모리 라벨 (D-007 트윈 내부 조회)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from twin.common.util import STATUS_NAMES, Diag

if TYPE_CHECKING:
    from twin.supervisor import Twin

COMM_GRACE_S = 15.0
SEVERITY_BY_STATE = {"DOWN": "HIGH", "ERROR": "MEDIUM", "STALE": "MEDIUM"}


def diag_of(twin: Twin, code: str) -> Diag | None:
    for p in twin.plcs.values():
        if code in p.points:
            return p.points[code].diag
    d = twin.edge.drivers.get(code)
    return d.diag if d else None


def connection_desc(twin: Twin, code: str) -> dict[str, Any]:
    e = twin.cfg.equip(code)
    base = twin.cfg.block_base(code)
    if e.kind == "bus":
        assert e.via.bus
        return {
            "parent": e.via.bus,
            "plc": twin.cfg.buses[e.via.bus].plc,
            "label": f"{e.via.bus} #{e.via.slave}",
            "plc_block": f"{base[0]}.D{base[1]:04d}" if base else None,
        }
    if e.kind == "plc_tcp":
        return {
            "parent": f"ETH-{e.via.plc_tcp}",
            "plc": e.via.plc_tcp,
            "label": f"Ethernet → {e.via.plc_tcp}",
            "plc_block": f"{base[0]}.D{base[1]:04d}" if base else None,
        }
    return {"parent": "EDGE", "plc": None, "label": f"Edge 직결 ({e.comm_type})", "plc_block": None}


def equip_state(twin: Twin, code: str) -> str:
    return twin.edge.device_state(code)


def equip_row(twin: Twin, code: str) -> dict[str, Any]:
    e = twin.cfg.equip(code)
    d = diag_of(twin, code)
    lv = twin.mes.last_values.get(code, {})
    return {
        "code": code,
        "name": e.name,
        "process": e.process,
        "type": e.type,
        "model": e.model,
        "comm_type": e.comm_type,
        "kind": e.kind,
        "poll_ms": e.poll_ms,
        "status": equip_state(twin, code),
        "diag": d.summary() if d else None,
        "values": lv.get("values", {}),
        "last_ts": lv.get("ts"),
        "extra": {k: v for k, v in lv.items() if k not in ("values", "ts")},
        "assumed": e.assumed,
        "items": [
            {
                "key": i.key,
                "name": i.name,
                "unit": i.unit,
                "reg": i.reg,
                "node": i.node,
                "type": i.type,
                "scale": i.scale,
                "data_type": i.data_type,
            }
            for i in e.items
        ],
        "target": e.target,
        **connection_desc(twin, code),
    }


def _worst(states: list[str]) -> str:
    if not states:
        return "INACTIVE"
    if all(s == "DOWN" for s in states):
        return "DOWN"
    if all(s == "STALE" for s in states):
        return "STALE"
    for s in ("DOWN", "ERROR", "STALE", "DELAY"):
        if s in states:
            return "ERROR" if s in ("DOWN", "STALE") else s
    return "OK"


def topology(twin: Twin) -> dict[str, Any]:
    """노드·링크 상태. 링크 색은 하류(데이터 출발) 쪽 상태를 따른다."""
    cfg = twin.cfg
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    states = {e.code: equip_state(twin, e.code) for e in cfg.equipment}
    for e in cfg.equipment:
        c = connection_desc(twin, e.code)
        nodes.append(
            {
                "id": e.code,
                "kind": "device",
                "label": e.code,
                "name": e.name,
                "status": states[e.code],
                "process": e.process,
                "comm": e.comm_type,
            }
        )
        links.append({"from": e.code, "to": c["parent"], "status": states[e.code], "comm": e.comm_type})
    for bid, bus in cfg.buses.items():
        st = _worst([states[e.code] for e in cfg.equipment if e.via.bus == bid])
        nodes.append({"id": bid, "kind": "bus", "label": bid, "name": f"RS-485 {bid}", "status": st})
        links.append({"from": bid, "to": bus.plc, "status": st, "comm": "RS-485"})
    for pid in cfg.plcs:
        eth = [e.code for e in cfg.equipment if e.kind == "plc_tcp" and e.via.plc_tcp == pid]
        if eth:
            st = _worst([states[c] for c in eth])
            nodes.append(
                {
                    "id": f"ETH-{pid}",
                    "kind": "bus",
                    "label": "ETH",
                    "name": "Ethernet(XBL-EMTA600)",
                    "status": st,
                }
            )
            links.append({"from": f"ETH-{pid}", "to": pid, "status": st, "comm": "Ethernet"})
    for pid, r in twin.edge.readers.items():
        st = r.plc_state()
        nodes.append(
            {
                "id": pid,
                "kind": "plc",
                "label": pid,
                "name": cfg.plcs[pid].name,
                "status": st,
                "model": cfg.plcs[pid].model,
            }
        )
        links.append({"from": pid, "to": "EDGE", "status": st, "comm": "Modbus TCP"})
    master = twin.edge.readers.get("MASTER")
    if master and "SLAVE" in cfg.plcs:
        sl = master.slave_link_state() or "UNKNOWN"
        links.append(
            {
                "from": "SLAVE",
                "to": "MASTER",
                "status": sl if sl != "UNKNOWN" else "STALE",
                "comm": "하트비트",
                "kind": "aux",
            }
        )
    nodes.append(
        {"id": "EDGE", "kind": "edge", "label": "Edge", "name": "Edge Collector (T1 X300)", "status": "OK"}
    )
    ml = twin.edge.mes_link_state()
    nodes.append(
        {
            "id": "MES",
            "kind": "mes",
            "label": "MES",
            "name": "임진강김치 MES",
            "status": "OK" if ml == "OK" else ("DOWN" if ml == "DOWN" else "STALE"),
        }
    )
    links.append(
        {
            "from": "EDGE",
            "to": "MES",
            "status": "OK" if ml == "OK" else ("DOWN" if ml == "DOWN" else "STALE"),
            "comm": "HTTP",
        }
    )
    return {"nodes": nodes, "links": links}


def summary(twin: Twin) -> dict[str, Any]:
    codes = [e.code for e in twin.cfg.equipment]
    states = [equip_state(twin, c) for c in codes]
    ok_polls = total_polls = 0
    for c in codes:
        d = diag_of(twin, c)
        if d is None:
            continue
        cut = time.monotonic() - 60
        w = [p for p in d.polls if p[0] >= cut]
        total_polls += len(w)
        ok_polls += sum(1 for p in w if p[1])
    active = int(
        twin.mes.db.execute("SELECT COUNT(*) FROM TWIN_ALARM WHERE STATE IN ('RAISED','ACKED')").fetchone()[0]
    )
    buf = twin.edge.buffer.stats()
    return {
        "total": len(codes),
        "ok": sum(1 for s in states if s == "OK"),
        "by_status": {s: states.count(s) for s in sorted(set(states))},
        "success_rate": (ok_polls / total_polls) if total_polls else None,
        "buffer_pending": buf["pending_items"],
        "active_alarms": active,
        "mes_link": twin.edge.mes_link_state(),
        "plcs": {pid: r.plc_state() for pid, r in twin.edge.readers.items()},
        "faults": len(twin.faults.active()),
        "uptime_s": round(time.monotonic() - twin.started_at, 1),
    }


def sync_comm_alarms(twin: Twin) -> None:
    """토폴로지 상태로 통신 알람을 올리고 내린다. 기동 직후 15 s는 유예."""
    if time.monotonic() - twin.started_at < COMM_GRACE_S:
        return
    al = twin.mes.alarms
    plc_state = {pid: r.plc_state() for pid, r in twin.edge.readers.items()}
    for pid, st in plc_state.items():
        al.comm(pid, pid, st == "DOWN", "HIGH", f"PLC {pid} 통신 끊김 (Edge 읽기 실패 또는 하트비트 정지)")
    for e in twin.cfg.equipment:
        plc = twin.cfg.plc_of(e)
        st = equip_state(twin, e.code)
        if plc and plc_state.get(plc) == "DOWN":
            st = "OK"  # PLC 알람으로 대표한다
        bad = st in ("DOWN", "ERROR", "STALE")
        label = {"DOWN": "통신 끊김", "ERROR": "통신 오류(CRC·프레임)", "STALE": "값 갱신 없음"}.get(st, "")
        al.comm(e.code, e.code, bad, SEVERITY_BY_STATE.get(st, "LOW"), f"{e.name} {label}")
    master = twin.edge.readers.get("MASTER")
    if master and plc_state.get("MASTER") == "OK" and plc_state.get("SLAVE") == "OK":
        al.comm(
            "MASTER-SLAVE",
            "MASTER-SLAVE",
            master.slave_link_state() == "DOWN",
            "MEDIUM",
            "Master–Slave 연동 끊김 (D0902 정지)",
        )
    else:
        al.comm("MASTER-SLAVE", "MASTER-SLAVE", False, "MEDIUM", "")
    al.comm(
        "EDGE-MES",
        "EDGE-MES",
        twin.edge.mes_link_state() == "DOWN",
        "HIGH",
        "Edge–MES 회선 장애 (Edge 로컬 버퍼링 중)",
    )


def plc_labels(twin: Twin, plc_id: str) -> dict[int, dict[str, Any]]:
    """D주소 → 설비·항목 라벨 (UI-06 툴팁)."""
    out: dict[int, dict[str, Any]] = {}
    for code, base in twin.cfg.plc_map.blocks.get(plc_id, {}).items():
        e = twin.cfg.equip(code)
        out[base] = {"code": code, "field": "통신상태", "kind": "status"}
        out[base + 1] = {"code": code, "field": "연속실패", "kind": "status"}
        off = 0
        for it in e.items:
            for w in range(it.words):
                suffix = "" if it.words == 1 else ("(상위)" if w == 0 else "(하위)")
                out[base + 2 + off + w] = {
                    "code": code,
                    "field": it.name + suffix,
                    "kind": "value",
                    "type": it.type,
                    "scale": it.scale,
                    "unit": it.unit,
                    "word": w,
                    "words": it.words,
                }
            off += it.words
        out[base + 8] = {"code": code, "field": "갱신카운터", "kind": "counter"}
    d = twin.cfg.plc_map.diag_base
    names = [
        "하트비트",
        "버스 상태 비트",
        "Slave 하트비트 미러",
        "스캔시간(ms)",
        "정상 장비 수",
        "Slave 링크 상태",
    ]
    for i, n in enumerate(names):
        if plc_id == "SLAVE" and i in (2, 5):
            continue
        out[d + i] = {"code": "DIAG", "field": n, "kind": "diag"}
    return out


__all__ = ["STATUS_NAMES", "equip_row", "plc_labels", "summary", "sync_comm_alarms", "topology"]
