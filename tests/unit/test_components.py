"""진단 상태 판정, 노이즈 필터, 버퍼, 알람 엔진, 공정 모델, WS 합치기."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from tests.conftest import CONFIG
from twin.common.config import load_config
from twin.common.util import STATUS_DELAY, STATUS_DOWN, STATUS_ERROR, STATUS_OK, Diag, iso, now_kst
from twin.edge.core import Buffer, NoiseFilter, Sample, to_raw_items
from twin.field.faults import FaultError, FaultManager
from twin.field.models.process import BrineSensorModel, FoxControllerModel, build_model
from twin.mes.alarms import AlarmEngine
from twin.mes.hub import WsHub

CFG = load_config(CONFIG)


# ── 진단 ──
def test_diag_down_after_three_failed_polls() -> None:
    d = Diag(delay_ms=150)
    assert d.status() == STATUS_DOWN  # 첫 성공 전
    d.attempt(True, 20, None)
    d.poll(True)
    assert d.status() == STATUS_OK
    for _ in range(2):
        d.attempt(False, None, "timeout")
        d.poll(False)
    assert d.status() == STATUS_OK
    d.poll(False)
    assert d.status() == STATUS_DOWN


def test_diag_error_and_delay() -> None:
    d = Diag(delay_ms=150)
    d.attempt(True, 20, None)
    d.poll(True)
    for _ in range(3):
        d.attempt(False, None, "crc")
        d.attempt(True, 20, None)
        d.poll(True)
    assert d.status() == STATUS_ERROR
    d2 = Diag(delay_ms=150)
    for _ in range(5):
        d2.attempt(True, 400, None)
        d2.poll(True)
    assert d2.status() == STATUS_DELAY
    assert d2.success_rate(60) == 1.0


# ── 노이즈 필터 ──
def _sample(code: str, **vals: float) -> Sample:
    return Sample(CFG.equip(code), now_kst(), dict(vals), {k: "T" for k in vals})


def test_noise_filter_range_and_step() -> None:
    f = NoiseFilter()
    assert f.apply(_sample("THD-01", temp=10.0, humid=150.0)).values == {"temp": 10.0}
    assert f.filtered["THD-01"] == 1
    assert f.apply(_sample("THD-01", temp=40.0, humid=80.0)).values == {"humid": 80.0}  # 급변 1회
    assert f.apply(_sample("THD-01", temp=40.0, humid=80.0)).values == {"humid": 80.0}  # 2회
    assert f.apply(_sample("THD-01", temp=40.0, humid=80.0)).values == {
        "temp": 40.0,
        "humid": 80.0,
    }  # 3회 → 인정


# ── 버퍼 ──
def test_buffer_priority_ack_and_seq_persistence(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", "edge01")
    items = to_raw_items(_sample("THD-01", temp=1.0, humid=2.0))
    ids1 = b.enqueue(items, 1, buffered=False)
    ids2 = b.enqueue(to_raw_items(_sample("MD-01", ng_cnt=1.0)), 0, buffered=False)
    assert ids1 == ["edge01-000000000001", "edge01-000000000002"] and ids2 == ["edge01-000000000003"]
    batch = b.next_batch(500)
    assert batch[0][3][0]["equip_code"] == "MD-01"  # 우선순위 0이 먼저
    b.mark_failed_all()
    assert all(att == 1 and buf == 1 for _, att, buf, _ in b.next_batch(500))
    b.ack([r[0] for r in batch], 3, 3)
    st = b.stats()
    assert st["pending_items"] == 0 and st["sent_total"] == 3 and st["resent_total"] == 3
    b.close()
    b2 = Buffer(tmp_path / "b.db", "edge01")
    assert b2.enqueue(to_raw_items(_sample("THD-01", temp=1.0)), 1, False) == ["edge01-000000000004"]


def test_buffer_batch_respects_sample_boundary(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", "edge01")
    for _ in range(3):
        b.enqueue(to_raw_items(_sample("MD-01", result=0, inspect_cnt=1, ng_cnt=0, run=1)), 1, False)
    batch = b.next_batch(10)
    assert sum(len(r[3]) for r in batch) == 8  # 4항목 샘플 2개, 3번째는 다음 배치로


def test_buffer_purge(tmp_path: Path) -> None:
    b = Buffer(tmp_path / "b.db", "edge01")
    b.enqueue(to_raw_items(_sample("THD-01", temp=1.0)), 1, False)
    b.db.execute("UPDATE buffer SET created_at = created_at - 100 * 3600")
    assert b.purge(72) == 1
    assert b.stats()["purged_total"] == 1


# ── 알람 ──
def _engine() -> tuple[AlarmEngine, list[dict]]:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.executescript((Path(__file__).resolve().parents[2] / "src/twin/mes/schema.sql").read_text())
    events: list[dict] = []
    return AlarmEngine(db, CFG.ccp, events.append), events


def test_alarm_hold_then_clear() -> None:
    eng, events = _engine()
    rule = next(r for r in CFG.ccp if r.id == "CCP-SAN")
    t0 = now_kst()
    assert eng.check(rule, "SAN-01", 8.5, iso(t0)) == (True, None)
    assert eng.check(rule, "SAN-01", 8.5, iso(t0 + timedelta(seconds=59)))[1] is None
    dev, aid = eng.check(rule, "SAN-01", 8.4, iso(t0 + timedelta(seconds=60)))
    assert dev and aid
    assert "소독수농도" in events[-1]["message"] and events[-1]["state"] == "RAISED"
    assert eng.check(rule, "SAN-01", 8.4, iso(t0 + timedelta(seconds=61)))[1] is None  # 중복 발생 없음
    eng.check(rule, "SAN-01", 10.5, iso(t0 + timedelta(seconds=62)))
    assert events[-1]["state"] == "CLEARED"


def test_alarm_band_with_target_and_event_ack() -> None:
    eng, events = _engine()
    salt = next(r for r in CFG.ccp if r.id == "CCP-SALT")
    assert eng.check(salt, "SAL-01", 12.5, iso(now_kst()), sub="T1", target=12.0) == (False, None)
    assert eng.check(salt, "SAL-01", 10.5, iso(now_kst()), sub="T1", target=12.0)[0] is True
    metal = next(r for r in CFG.ccp if r.id == "CCP-METAL")
    aid = eng.event(metal, "MD-01", "1", iso(now_kst()), "NG")
    assert eng.ack(aid)["state"] == "CLEARED"  # 이벤트 알람은 확인하면 해제


# ── 고장 관리 ──
def test_fault_validation() -> None:
    fm = FaultManager({"equip": ["SAN-01"], "bus": ["M1"]})
    with pytest.raises(FaultError):
        fm.add("M9", "bus_cut")
    with pytest.raises(FaultError):
        fm.add("SAN-01", "value_spike", {"key": "ppm"})
    f = fm.add("SAN-01", "value_spike", {"key": "ppm", "value": 8.5}, duration_s=0.0001)
    assert fm.spikes("SAN-01") == {} or f.remaining() is not None


# ── 공정 모델 ──
def test_models_are_deterministic_by_seed() -> None:
    def run(seed: int) -> list[tuple]:
        fm = FaultManager({})
        models = [build_model(e, seed, fm, CFG.tanks) for e in CFG.equipment if e.sim["model"] != "scale"]
        seq = []
        for _ in range(300):
            for m in models:
                m.step(1.0)
            seq.append(tuple(round(v, 6) for m in models for v in m.values.values()))
        return seq

    assert run(42) == run(42)
    assert run(42) != run(43)


def test_brine_sensor_switches_tanks_and_fox_stays_in_band() -> None:
    fm = FaultManager({})
    sal = build_model(CFG.equip("SAL-01"), 1, fm, CFG.tanks)
    assert isinstance(sal, BrineSensorModel)
    seen = set()
    for _ in range(600):
        sal.step(1.0)
        seen.add(int(sal.values["tank_no"]))
    assert seen == {1, 2, 3, 4}
    tc = build_model(CFG.equip("TC-01"), 1, fm, CFG.tanks)
    assert isinstance(tc, FoxControllerModel)
    pvs = []
    for _ in range(7200):
        tc.step(1.0)
        pvs.append(tc.values["pv"])
    assert min(pvs) > -1.0 and max(pvs) < 8.0


def test_value_spike_and_freeze_affect_registers() -> None:
    fm = FaultManager({"equip": ["SAN-01"]})
    san = build_model(CFG.equip("SAN-01"), 1, fm, CFG.tanks)
    fm.add("SAN-01", "value_spike", {"key": "ppm", "value": 8.5})
    assert san.read(3, 0, 1) == [850]
    fm.clear()
    fm.add("SAN-01", "value_freeze")
    frozen = san.read(3, 0, 4)
    for _ in range(50):
        san.step(1.0)
    assert san.read(3, 0, 4) == frozen


# ── WS 합치기 ──
def test_ws_hub_coalesces_values() -> None:
    hub = WsHub(0.2)
    for i in range(10):
        hub.publish({"type": "value", "equip": "THD-01", "values": {"temp": float(i)}, "ts": str(i)})
    hub.publish({"type": "value", "equip": "THD-01", "values": {"humid": 50.0}, "ts": "x"})
    hub.publish({"type": "alarm", "alarm_id": 1})
    assert len(hub._pending_values) == 1
    assert hub._pending_values["THD-01"]["values"] == {"temp": 9.0, "humid": 50.0}
    assert len(hub._queue) == 1


def test_brine_tank_switch_not_filtered() -> None:
    """D-014: 절임통 전환으로 염도가 12 → 9 %로 바뀌어도 버리지 않는다."""
    f = NoiseFilter()
    assert f.apply(_sample("SAL-01", salinity=12.3, tank_no=3)).values["salinity"] == 12.3
    assert f.apply(_sample("SAL-01", salinity=9.1, tank_no=4)).values["salinity"] == 9.1
    assert f.filtered.get("SAL-01", 0) == 0
