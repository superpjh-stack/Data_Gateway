"""고장·장애 주입 관리 (spec 8장). 모든 계층이 이 객체를 조회한다."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

# 유형 → 허용 대상 종류
FAULT_TYPES: dict[str, dict[str, Any]] = {
    "sensor_disconnect": {"target": "equip", "label": "센서 무응답", "params": []},
    "sensor_delay": {"target": "equip", "label": "응답 지연", "params": ["ms"]},
    "crc_error": {"target": "equip", "label": "CRC 오류", "params": ["ratio"]},
    "value_spike": {"target": "equip", "label": "값 강제", "params": ["key", "value"]},
    "value_freeze": {"target": "equip", "label": "값 고정", "params": []},
    "bus_cut": {"target": "bus", "label": "RS-485 버스 단선", "params": []},
    "plc_down": {"target": "plc", "label": "PLC 정지", "params": []},
    "master_slave_link_down": {"target": "link", "label": "Master–Slave 연동 끊김", "params": []},
    "opcua_down": {"target": "opcua", "label": "OPC-UA 서버 정지", "params": []},
    "mes_link_down": {"target": "mes", "label": "Edge–MES 회선 장애", "params": []},
    "edge_restart": {"target": "edge", "label": "Edge 재시작", "params": [], "instant": True},
    "metal_ng": {"target": "metal", "label": "금속 이물 통과(NG 발생)", "params": [], "instant": True},
}

FIXED_TARGETS = {"link": ["MASTER-SLAVE"], "mes": ["EDGE-MES"], "edge": ["EDGE"], "plc": ["MASTER", "SLAVE"]}


class FaultError(ValueError):
    """잘못된 고장 요청."""


@dataclass
class Fault:
    id: str
    target: str
    type: str
    params: dict[str, Any]
    created: float
    expires: float | None
    state: dict[str, Any] = field(default_factory=dict)

    def remaining(self) -> float | None:
        return None if self.expires is None else max(0.0, self.expires - time.monotonic())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "type": self.type,
            "label": FAULT_TYPES[self.type]["label"],
            "params": self.params,
            "remaining_s": None if self.remaining() is None else round(self.remaining() or 0, 1),
        }


class FaultManager:
    """활성 고장 목록. 만료는 조회 시점에 정리한다."""

    def __init__(self, targets: dict[str, list[str]]) -> None:
        self._faults: dict[str, Fault] = {}
        self._seq = itertools.count(1)
        self.targets = {**FIXED_TARGETS, **targets}

    def validate(self, target: str, type_: str, params: dict[str, Any]) -> None:
        spec = FAULT_TYPES.get(type_)
        if spec is None:
            raise FaultError(f"알 수 없는 고장 유형 '{type_}'")
        allowed = self.targets.get(spec["target"], [])
        if target not in allowed:
            raise FaultError(f"'{type_}'의 대상은 {allowed} 중 하나여야 함 (받은 값 '{target}')")
        for p in spec["params"]:
            if p not in params:
                raise FaultError(f"'{type_}'에 params.{p} 필요")

    def add(
        self, target: str, type_: str, params: dict[str, Any] | None = None, duration_s: float | None = None
    ) -> Fault:
        params = params or {}
        self.validate(target, type_, params)
        now = time.monotonic()
        f = Fault(
            f"F-{next(self._seq)}", target, type_, params, now, now + duration_s if duration_s else None
        )
        self._faults[f.id] = f
        return f

    def remove(self, fid: str) -> bool:
        return self._faults.pop(fid, None) is not None

    def clear(self) -> None:
        self._faults.clear()

    def active(self) -> list[Fault]:
        now = time.monotonic()
        for fid in [k for k, f in self._faults.items() if f.expires is not None and f.expires <= now]:
            del self._faults[fid]
        return list(self._faults.values())

    def find(self, type_: str, target: str) -> Fault | None:
        for f in self.active():
            if f.type == type_ and f.target == target:
                return f
        return None

    def has(self, type_: str, target: str) -> bool:
        return self.find(type_, target) is not None

    def spikes(self, code: str) -> dict[str, float]:
        return {
            f.params["key"]: float(f.params["value"])
            for f in self.active()
            if f.type == "value_spike" and f.target == code
        }

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "type": t,
                "label": s["label"],
                "params": s["params"],
                "targets": self.targets.get(s["target"], []),
                "instant": bool(s.get("instant")),
            }
            for t, s in FAULT_TYPES.items()
        ]
