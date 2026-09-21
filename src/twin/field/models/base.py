"""가상 장비 모델 공통부. 값은 공학단위로 들고, 읽을 때 레지스터로 바꾼다."""

from __future__ import annotations

import random
import zlib
from typing import TYPE_CHECKING, Any

from twin.common.config import Equip
from twin.common.modbus import EXC_ILLEGAL_ADDRESS, ExceptionResponse, encode_value

if TYPE_CHECKING:
    from twin.field.faults import FaultManager


class DeviceModel:
    """장비 한 대. step(dt)로 상태를 갱신하고 read()로 레지스터를 내준다."""

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        self.equip = equip
        self.code = equip.code
        self.p: dict[str, Any] = equip.sim
        self.rng = random.Random(seed + zlib.crc32(equip.code.encode()))
        self.faults = faults
        self.t = 0.0  # 모델 경과시간(시뮬레이션 초)
        self.values: dict[str, float] = {}

    # ── 하위 클래스가 구현 ──
    def step(self, dt: float) -> None:
        self.t += dt

    # ── 공통 ──
    def effective(self) -> dict[str, float]:
        """고장 주입(value_spike)을 반영한 현재값."""
        vals = dict(self.values)
        vals.update(self.faults.spikes(self.code))
        return vals

    def override(self, key: str) -> float | None:
        return self.faults.spikes(self.code).get(key)

    def register_map(self) -> dict[tuple[int, int], int]:
        """(기능코드, 주소) → 워드. value_freeze 중이면 고정 스냅샷을 쓴다."""
        freeze = self.faults.find("value_freeze", self.code)
        if freeze is not None:
            if "snapshot" not in freeze.state:
                freeze.state["snapshot"] = self._build_map(self.effective())
            snap: dict[tuple[int, int], int] = freeze.state["snapshot"]
            return snap
        return self._build_map(self.effective())

    def _build_map(self, vals: dict[str, float]) -> dict[tuple[int, int], int]:
        regs: dict[tuple[int, int], int] = {}
        for it in self.equip.items:
            if it.reg is None:
                continue
            words = encode_value(vals.get(it.key, 0.0), it.type, it.scale)
            for i, w in enumerate(words):
                regs[(it.fc, it.address + i)] = w
        return regs

    def read(self, fc: int, addr: int, count: int) -> list[int]:
        regs = self.register_map()
        out: list[int] = []
        for a in range(addr, addr + count):
            if (fc, a) not in regs:
                raise ExceptionResponse(EXC_ILLEGAL_ADDRESS)
            out.append(regs[(fc, a)])
        return out

    def gauss(self, sigma: float) -> float:
        return self.rng.gauss(0.0, sigma)

    def snapshot(self) -> dict[str, float]:
        return {k: round(v, 4) for k, v in self.effective().items()}
