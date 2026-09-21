"""공정 모델 8종 (spec 7장). 모든 난수는 장비별 rng에서만 뽑는다(AC-14 재현성)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from twin.common.config import Equip, Tank
from twin.field.models.base import DeviceModel

if TYPE_CHECKING:
    from twin.field.faults import FaultManager

DAY = 86400.0


class ThdModel(DeviceModel):
    """온습도센서: 기준값 + 일중 변동 + 완만한 잡음."""

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        super().__init__(equip, seed, faults)
        self.drift_t = 0.0
        self.drift_h = 0.0
        self.phase = self.rng.uniform(0, 2 * math.pi)
        self._update()

    def _update(self) -> None:
        daily = math.sin(2 * math.pi * self.t / DAY + self.phase)
        self.values["temp"] = float(self.p["base_temp"]) + 1.5 * daily + self.drift_t
        self.values["humid"] = min(99.0, max(20.0, float(self.p["base_humid"]) - 3.0 * daily + self.drift_h))

    def step(self, dt: float) -> None:
        super().step(dt)
        k = min(1.0, dt / 600)
        self.drift_t += -self.drift_t * k + self.gauss(0.05) * math.sqrt(max(dt, 1e-9))
        self.drift_h += -self.drift_h * k + self.gauss(0.15) * math.sqrt(max(dt, 1e-9))
        self._update()


class BrineSensorModel(DeviceModel):
    """염도센서: 담당 절임통을 순환 측정. 통마다 목표 염도에서 시간에 따라 서서히 떨어진다."""

    DECAY_PER_H = 0.03

    def __init__(self, equip: Equip, seed: int, faults: FaultManager, tanks: dict[int, Tank]) -> None:
        super().__init__(equip, seed, faults)
        self.tank_ids: list[int] = list(self.p["tanks"])
        self.switch_sec = float(self.p.get("switch_sec", 120))
        self.tanks = {n: tanks[n] for n in self.tank_ids}
        self.elapsed_h = {n: self.tanks[n].offset_h for n in self.tank_ids}
        self.noise = {n: 0.0 for n in self.tank_ids}
        self._update()

    def tank_salinity(self, n: int) -> float:
        tk = self.tanks[n]
        return tk.target + 0.3 - self.DECAY_PER_H * self.elapsed_h[n] + self.noise[n]

    def current_tank(self) -> int:
        return self.tank_ids[int(self.t // self.switch_sec) % len(self.tank_ids)]

    def _update(self) -> None:
        n = self.current_tank()
        self.values["salinity"] = self.tank_salinity(n)
        self.values["water_temp"] = 10.0 + self.noise[n] * 2
        self.values["tank_no"] = float(n)
        self.values["sensor_state"] = 0.0

    def step(self, dt: float) -> None:
        super().step(dt)
        for n in self.tank_ids:
            self.elapsed_h[n] += dt / 3600
            if self.elapsed_h[n] >= self.tanks[n].hours:
                self.elapsed_h[n] -= self.tanks[n].hours  # 새 배치 투입
            self.noise[n] += -self.noise[n] * min(1.0, dt / 300) + self.gauss(0.01) * math.sqrt(max(dt, 1e-9))
        self._update()

    def tank_states(self) -> dict[int, dict[str, float]]:
        return {n: {"salinity": round(self.tank_salinity(n), 2), "elapsed_h": round(self.elapsed_h[n], 2)} for n in self.tank_ids}


class FoxControllerModel(DeviceModel):
    """온도조절기: 냉동기 ON/OFF 히스테리시스 + 문 열림 이벤트."""

    COOL = 0.02
    WARM = 0.008
    DOOR_WARM = 0.05

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        super().__init__(equip, seed, faults)
        self.sv = float(self.p["sv"])
        self.h = float(self.p.get("hysteresis", 1.5))
        self.pv = self.sv + self.rng.uniform(-self.h / 2, self.h / 2)
        self.compressor = self.rng.random() < 0.5
        self.door_left = 0.0
        self._update()

    def _update(self) -> None:
        self.values["pv"] = self.pv
        self.values["sv"] = self.sv
        bits = (1 if self.compressor else 0) | (4 if self.door_left > 0 else 0)
        self.values["out_state"] = float(bits)

    def step(self, dt: float) -> None:
        super().step(dt)
        if self.door_left <= 0 and self.rng.random() < dt / 1800:
            self.door_left = self.rng.uniform(20, 60)
        rate = -self.COOL if self.compressor else self.WARM
        if self.door_left > 0:
            rate += self.DOOR_WARM
            self.door_left -= dt
        self.pv += rate * dt + self.gauss(0.01)
        if self.pv > self.sv + self.h / 2:
            self.compressor = True
        elif self.pv < self.sv - self.h / 2:
            self.compressor = False
        self._update()


class MetalDetectorModel(DeviceModel):
    """금속검출기: 가동 중 포아송 검사, NG 확률."""

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        super().__init__(equip, seed, faults)
        self.inspect = 0
        self.ng = 0
        self.last = 0
        self.frac = 0.0
        self.force_ng = 0
        self._update()

    def _update(self) -> None:
        self.values.update(result=float(self.last), inspect_cnt=float(self.inspect), ng_cnt=float(self.ng), run=1.0)

    def trigger_ng(self) -> None:
        """외부 이벤트: 다음 검사 1건을 NG로 만든다 (고장 주입 metal_ng)."""
        self.inspect += 1
        self.ng += 1
        self.last = 1
        self._update()

    def step(self, dt: float) -> None:
        super().step(dt)
        self.frac += float(self.p.get("rate_per_s", 0.3)) * dt
        n = int(self.frac)
        self.frac -= n
        for _ in range(n):
            self.inspect += 1
            if self.rng.random() < float(self.p.get("ng_prob", 0.002)):
                self.ng += 1
                self.last = 1
            else:
                self.last = 0
        self._update()


class SanitizerModel(DeviceModel):
    """소독수 공급장치: 기준 10 ppm 위에서 변동, 가끔 투입 저하로 농도 하락."""

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        super().__init__(equip, seed, faults)
        self.base = float(self.p.get("base_ppm", 10.6))
        self.dip_left = 0.0
        self.noise = 0.0
        self._update()

    def _update(self) -> None:
        dip = -1.3 if self.dip_left > 0 else 0.0
        self.values["ppm"] = max(0.0, self.base + dip + self.noise)
        self.values["contact_min"] = 5.0 + self.noise * 0.3
        self.values["dosing_rate"] = 1.2 + (-(0.3) if self.dip_left > 0 else 0.0)
        self.values["run"] = 1.0

    def step(self, dt: float) -> None:
        super().step(dt)
        if self.dip_left > 0:
            self.dip_left -= dt
        elif self.rng.random() < dt / 3600:
            self.dip_left = self.rng.uniform(60, 120)
        self.noise += -self.noise * min(1.0, dt / 60) + self.gauss(0.04) * math.sqrt(max(dt, 1e-9))
        self._update()


class TapingMachineModel(DeviceModel):
    """아이스박스자동포장기 KF 100: 분당 약 1박스, 가끔 걸림 정지."""

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        super().__init__(equip, seed, faults)
        self.count = 0
        self.frac = 0.0
        self.run_min = 0.0
        self.stop_left = 0.0
        self._update()

    def running(self) -> bool:
        ov = self.override("running")
        return bool(ov) if ov is not None else self.stop_left <= 0

    def _update(self) -> None:
        self.values.update(
            pack_count=float(self.count),
            running=1.0 if self.stop_left <= 0 else 0.0,
            run_minutes=round(self.run_min, 2),
            alarm_code=12.0 if self.stop_left > 0 else 0.0,
        )

    def step(self, dt: float) -> None:
        super().step(dt)
        if self.stop_left > 0:
            self.stop_left -= dt
        elif self.rng.random() < float(self.p.get("stop_prob", 0.002)) * dt:
            self.stop_left = self.rng.uniform(30, 120)
        if self.running():
            self.run_min += dt / 60
            self.frac += float(self.p.get("boxes_per_min", 1.0)) * dt / 60
            n = int(self.frac)
            self.frac -= n
            self.count += n
        self._update()


class ScaleModel(DeviceModel):
    """중량 저울: 요청마다 새 박스 중량(정규분포). 5 %는 불안정."""

    def measure(self) -> tuple[str, float]:
        ov = self.override("weight")
        w = ov if ov is not None else float(self.p["std_kg"]) + self.gauss(float(self.p.get("sigma_kg", 0.04)))
        state = "US" if self.rng.random() < 0.05 else "ST"
        self.values["weight"] = w
        return state, w

    def step(self, dt: float) -> None:
        super().step(dt)


class FillerModel(DeviceModel):
    """충진기·속넣기기계: 세팅양 고정, 교대(4 h)마다 속도 변경."""

    def __init__(self, equip: Equip, seed: int, faults: FaultManager) -> None:
        super().__init__(equip, seed, faults)
        self.base_speed = float(self.p["speed"])
        self.speed = self.base_speed
        self.count = 0.0
        self.shift = -1
        self._update()

    def _update(self) -> None:
        self.values.update(speed=round(self.speed), set_volume=float(self.p["set_volume"]), run=1.0,
                           count=float(int(self.count)))

    def step(self, dt: float) -> None:
        super().step(dt)
        shift = int(self.t // (4 * 3600))
        if shift != self.shift:
            self.shift = shift
            self.speed = self.base_speed * self.rng.uniform(0.85, 1.15)
        self.count += self.speed * dt / 60
        self._update()


def build_model(equip: Equip, seed: int, faults: FaultManager, tanks: dict[int, Tank]) -> DeviceModel:
    """sim.model 이름으로 모델을 만든다."""
    name = equip.sim.get("model")
    table: dict[str, Any] = {
        "thd": ThdModel,
        "fox_controller": FoxControllerModel,
        "metal_detector": MetalDetectorModel,
        "sanitizer": SanitizerModel,
        "taping_machine": TapingMachineModel,
        "scale": ScaleModel,
        "filler": FillerModel,
    }
    if name == "brine_sensor":
        return BrineSensorModel(equip, seed, faults, tanks)
    if name not in table:
        raise ValueError(f"{equip.code}: 알 수 없는 sim.model '{name}'")
    model: DeviceModel = table[name](equip, seed, faults)
    return model
