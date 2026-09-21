"""AC-14 같은 시드로 두 번 실행하면 수집값 시퀀스가 같다 (Field Simulator 틱 단위)."""

import pytest

from tests.conftest import CONFIG
from twin.common.config import load_config
from twin.field.faults import FaultManager
from twin.field.simulator import FieldSimulator

pytestmark = pytest.mark.acceptance


def _sequence(seed: int, ticks: int = 600) -> list[tuple]:
    cfg = load_config(CONFIG, {"runtime": {"seed": seed}})
    sim = FieldSimulator(cfg, FaultManager({}))
    seq = []
    for _ in range(ticks):
        sim.tick()
        regs = []
        for code in sorted(sim.models):
            m = sim.models[code]
            regs.append((code, tuple(sorted(m.register_map().items())) if code != "SCALE-01" else ()))
        seq.append(tuple(regs))
    return seq


def test_ac14_same_seed_same_sequence():
    a, b = _sequence(20260921), _sequence(20260921)
    assert a == b
    assert a != _sequence(1)
