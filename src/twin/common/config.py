"""설정 로더: YAML 5종을 pydantic으로 검증하고 메모리 맵·1:1 매핑을 확인한다."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PLC_IDS = ("MASTER", "SLAVE")
VALUE_WORDS = 6  # 블록 +2 ~ +7


class ConfigError(Exception):
    """설정 오류. 메시지는 '파일 경로: 설명' 한 줄이다."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(_Strict):
    key: str
    name: str
    reg: str | None = None
    node: str | None = None
    type: Literal["uint16", "int16", "uint32", "bool", "float"]
    scale: float = 1.0
    unit: str
    data_type: str
    range: tuple[float, float] | None = None
    max_step: float | None = None

    @property
    def fc(self) -> int:
        """레지스터 종류로 정한 읽기 기능코드 (IR → 04, HR → 03)."""
        assert self.reg
        return 4 if self.reg.startswith("IR") else 3

    @property
    def address(self) -> int:
        """0 기반 프로토콜 주소 (IR30001 → 0)."""
        assert self.reg
        return int(self.reg[2:]) % 10000 - 1

    @property
    def words(self) -> int:
        return 2 if self.type == "uint32" else 1

    @model_validator(mode="after")
    def _check_reg(self) -> Item:
        if self.reg is not None:
            prefix, num = self.reg[:2], self.reg[2:]
            if prefix not in ("IR", "HR") or not num.isdigit() or len(num) != 5:
                raise ValueError(f"reg 형식 오류 '{self.reg}' (예: IR30001, HR40001)")
            if (prefix == "IR") != num.startswith("3"):
                raise ValueError(f"reg 접두어와 번호 불일치 '{self.reg}'")
        return self


class Via(_Strict):
    bus: str | None = None
    slave: int | None = None
    plc_tcp: str | None = None
    edge: Literal["modbus_tcp", "opcua", "ascii"] | None = None
    link: str | None = None
    unit: int = 1
    endpoint: str | None = None


class Equip(_Strict):
    code: str
    name: str
    process: str
    type: str
    model: str | None = None
    via: Via
    poll_ms: int = Field(gt=0)
    delay_ms: int | None = None
    target: str
    items: list[Item]
    sim: dict[str, Any]
    assumed: list[str] = []

    @property
    def kind(self) -> str:
        """연결 방식: bus / plc_tcp / edge_modbus_tcp / edge_opcua / edge_ascii."""
        if self.via.bus:
            return "bus"
        if self.via.plc_tcp:
            return "plc_tcp"
        return f"edge_{self.via.edge}"

    @property
    def plc(self) -> str | None:
        return self.via.plc_tcp

    @property
    def comm_type(self) -> str:
        return {
            "bus": "RS-485",
            "plc_tcp": "Ethernet(TCP/IP)",
            "edge_modbus_tcp": "Ethernet(TCP/IP)",
            "edge_opcua": "OPC-UA",
            "edge_ascii": "RS-232",
        }[self.kind]

    @property
    def value_words(self) -> int:
        return sum(i.words for i in self.items)

    def effective_delay_ms(self) -> int:
        """DELAY 판정 기준 응답시간 (D-008)."""
        if self.delay_ms is not None:
            return self.delay_ms
        return 150 if self.kind == "bus" else 250


class Bus(_Strict):
    plc: str
    link: str
    baud: int = 9600
    timeout_ms: int = 300
    retries: int = 2
    endpoint: str | None = None


class PlcDef(_Strict):
    model: str
    name: str
    area: str


class Tank(_Strict):
    target: float
    hours: float
    offset_h: float = 0.0


class EdgeCfg(_Strict):
    id: str = "edge01"
    plc_poll_ms: int = 1000
    plc_timeout_ms: int = 800
    batch_max: int = 500
    retention_hours: float = 72
    backoff_max_s: float = 30
    stale_factor: float = 3
    send_interval_ms: int = 200


class FieldCfg(_Strict):
    tick_ms: int = 1000


class WsCfg(_Strict):
    flush_ms: int = 200


class PurgeCfg(_Strict):
    """MES DB 일일 정리 (D-017)."""

    enabled: bool = True
    at: str = Field("03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # KST 매일 이 시각
    keep_hours: float = Field(0.0, ge=0)  # 0 = 정리 시각 이전 수집 데이터를 모두 지운다
    vacuum: bool = True  # 삭제 후 파일 크기를 실제로 줄인다


class MesCfg(_Strict):
    purge: PurgeCfg = PurgeCfg()


class Runtime(_Strict):
    seed: int = 0
    time_scale: float = 1.0
    host: str = "127.0.0.1"
    ports: dict[str, int]
    edge: EdgeCfg = EdgeCfg()
    field: FieldCfg = FieldCfg()
    ws: WsCfg = WsCfg()
    mes: MesCfg = MesCfg()
    data_dir: str = "data"
    log_level: str = "INFO"


class PlcMap(_Strict):
    block_words: int = 10
    diag_base: int = 900
    blocks: dict[str, dict[str, int]]


class CcpRule(_Strict):
    id: str
    item: str
    equip: list[str]
    key: str
    low: float | None = None
    high: float | None = None
    band: float | None = None
    band_pct: float | None = None
    std: float | None = None
    ng_immediate: bool = False
    unit: str
    hold_sec: float = 0
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    basis: str


class ScenarioStep(_Strict):
    target: str
    type: str
    params: dict[str, Any] = {}
    duration_s: float | None = None
    at_s: float = 0


class EquipmentFile(_Strict):
    plcs: dict[str, PlcDef]
    buses: dict[str, Bus]
    item_sets: dict[str, Any] = {}
    equipment: list[Equip]
    tanks: dict[int, Tank]


class TwinConfig(BaseModel):
    """검증을 마친 전체 설정."""

    runtime: Runtime
    plcs: dict[str, PlcDef]
    buses: dict[str, Bus]
    equipment: list[Equip]
    tanks: dict[int, Tank]
    plc_map: PlcMap
    ccp: list[CcpRule]
    scenarios: dict[str, list[ScenarioStep]]

    def equip(self, code: str) -> Equip:
        for e in self.equipment:
            if e.code == code:
                return e
        raise KeyError(code)

    def port(self, link: str) -> int:
        return self.runtime.ports[link]

    def block_base(self, code: str) -> tuple[str, int] | None:
        for plc, blocks in self.plc_map.blocks.items():
            if code in blocks:
                return plc, blocks[code]
        return None

    def plc_of(self, e: Equip) -> str | None:
        if e.kind == "bus":
            assert e.via.bus
            return self.buses[e.via.bus].plc
        return e.via.plc_tcp


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = _deep_merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(patch)


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config: {path.name}: 파일 없음") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"config: {path.name}: YAML 문법 오류 {exc}") from exc


def _fmt_validation(fname: str, exc: ValidationError, prefix: str = "") -> ConfigError:
    err = exc.errors()[0]
    loc = prefix
    for part in err["loc"]:
        loc += f"[{part}]" if isinstance(part, int) else (f".{part}" if loc else str(part))
    return ConfigError(f"config: {fname} {loc}: {err['msg']}")


def load_config(config_dir: str | Path = "config", overrides: dict[str, Any] | None = None) -> TwinConfig:
    """설정을 읽어 검증한다. overrides는 테스트용 부분 덮어쓰기다.

    키: runtime(깊은 병합), equipment_patch{code: dict}, ccp_patch{id: dict}, plc_map(깊은 병합),
    bus_patch{id: dict}.
    """
    d = Path(config_dir)
    ov = overrides or {}
    raw_runtime = _deep_merge(_read_yaml(d / "runtime.yaml"), ov.get("runtime", {}))
    raw_equip = _read_yaml(d / "equipment.yaml")
    for code, patch in ov.get("equipment_patch", {}).items():
        for i, e in enumerate(raw_equip["equipment"]):
            if e["code"] == code:
                raw_equip["equipment"][i] = _deep_merge(e, patch)
    for bus_id, patch in ov.get("bus_patch", {}).items():
        raw_equip["buses"][bus_id] = _deep_merge(raw_equip["buses"][bus_id], patch)
    raw_map = _deep_merge(_read_yaml(d / "plc_map.yaml"), ov.get("plc_map", {}))
    raw_ccp = _read_yaml(d / "ccp_std.yaml")
    for rid, patch in ov.get("ccp_patch", {}).items():
        for i, r in enumerate(raw_ccp):
            if r["id"] == rid:
                raw_ccp[i] = _deep_merge(r, patch)
    raw_scen = _read_yaml(d / "scenarios.yaml") or {}

    try:
        runtime = Runtime.model_validate(raw_runtime)
    except ValidationError as exc:
        raise _fmt_validation("runtime.yaml", exc) from exc
    try:
        ef = EquipmentFile.model_validate(raw_equip)
    except ValidationError as exc:
        raise _fmt_validation("equipment.yaml", exc) from exc
    try:
        pmap = PlcMap.model_validate(raw_map)
    except ValidationError as exc:
        raise _fmt_validation("plc_map.yaml", exc) from exc
    try:
        ccp = [CcpRule.model_validate(r) for r in raw_ccp]
    except ValidationError as exc:
        raise _fmt_validation("ccp_std.yaml", exc) from exc
    try:
        scen = {k: [ScenarioStep.model_validate(s) for s in v] for k, v in raw_scen.items()}
    except ValidationError as exc:
        raise _fmt_validation("scenarios.yaml", exc) from exc

    cfg = TwinConfig(
        runtime=runtime,
        plcs=ef.plcs,
        buses=ef.buses,
        equipment=ef.equipment,
        tanks=ef.tanks,
        plc_map=pmap,
        ccp=ccp,
        scenarios=scen,
    )
    validate_semantics(cfg)
    return cfg


def validate_semantics(cfg: TwinConfig) -> None:
    """교차 검증: 코드 중복, 버스·슬레이브, 메모리 블록 겹침, 설비↔블록 1:1, 포트."""
    codes = [e.code for e in cfg.equipment]
    dup = {c for c in codes if codes.count(c) > 1}
    if dup:
        raise ConfigError(f"config: equipment.yaml equipment: 설비 코드 중복 {sorted(dup)}")

    for bid, bus in cfg.buses.items():
        if bus.plc not in cfg.plcs:
            raise ConfigError(f"config: equipment.yaml buses.{bid}.plc: 없는 PLC '{bus.plc}'")
        if bus.link not in cfg.runtime.ports and not bus.endpoint:
            raise ConfigError(
                f"config: equipment.yaml buses.{bid}.link: runtime.yaml ports에 '{bus.link}' 없음"
            )

    seen_slave: dict[tuple[str, int], str] = {}
    for idx, e in enumerate(cfg.equipment):
        where = f"config: equipment.yaml equipment[{idx}]({e.code})"
        k = e.kind
        if k == "bus":
            if e.via.bus not in cfg.buses or e.via.slave is None:
                raise ConfigError(f"{where}.via: 버스 '{e.via.bus}' 또는 slave 누락")
            key = (e.via.bus, e.via.slave)
            if key in seen_slave:
                raise ConfigError(
                    f"{where}.via.slave: {e.via.bus} slave {e.via.slave}가 {seen_slave[key]}와 중복"
                )
            seen_slave[key] = e.code
        elif k == "plc_tcp":
            if e.via.plc_tcp not in cfg.plcs:
                raise ConfigError(f"{where}.via.plc_tcp: 없는 PLC '{e.via.plc_tcp}'")
        elif e.via.edge is None:
            raise ConfigError(f"{where}.via: bus, plc_tcp, edge 중 하나가 필요")
        if k != "bus" and e.via.link and e.via.link not in cfg.runtime.ports and not e.via.endpoint:
            raise ConfigError(f"{where}.via.link: runtime.yaml ports에 '{e.via.link}' 없음")
        for j, it in enumerate(e.items):
            needs_reg = k in ("bus", "plc_tcp", "edge_modbus_tcp")
            if needs_reg and it.reg is None:
                raise ConfigError(f"{where}.items[{j}].reg: Modbus 장비는 reg 필수")
            if k == "edge_opcua" and it.node is None:
                raise ConfigError(f"{where}.items[{j}].node: OPC-UA 장비는 node 필수")
        if k in ("bus", "plc_tcp") and e.value_words > VALUE_WORDS:
            raise ConfigError(f"{where}.items: 값 {e.value_words}워드가 블록 한도 {VALUE_WORDS}워드 초과")

    _validate_memory_map(cfg)


def _validate_memory_map(cfg: TwinConfig) -> None:
    pm = cfg.plc_map
    by_code = {e.code: e for e in cfg.equipment}
    mapped: dict[str, str] = {}
    for plc, blocks in pm.blocks.items():
        if plc not in cfg.plcs:
            raise ConfigError(f"config: plc_map.yaml blocks.{plc}: 없는 PLC")
        spans: list[tuple[int, int, str]] = []
        for code, base in blocks.items():
            if code not in by_code:
                raise ConfigError(f"config: plc_map.yaml blocks.{plc}.{code}: equipment.yaml에 없는 설비")
            if code in mapped:
                raise ConfigError(
                    f"config: plc_map.yaml blocks.{plc}.{code}: {mapped[code]}에도 매핑됨 (1:1 위반)"
                )
            mapped[code] = plc
            owner = cfg.plc_of(by_code[code])
            if owner != plc:
                raise ConfigError(f"config: plc_map.yaml blocks.{plc}.{code}: 이 설비는 {owner} 소속")
            spans.append((base, base + pm.block_words, code))
        spans.append((pm.diag_base, pm.diag_base + pm.block_words, "진단영역"))
        spans.sort()
        for (s1, e1, c1), (s2, _e2, c2) in zip(spans, spans[1:], strict=False):
            if s2 < e1:
                raise ConfigError(
                    f"config: plc_map.yaml blocks.{plc}: D{s2:04d}({c2})가 D{s1:04d}~D{e1 - 1:04d}({c1})와 겹침"
                )
    for e in cfg.equipment:
        if e.kind in ("bus", "plc_tcp") and e.code not in mapped:
            raise ConfigError(f"config: plc_map.yaml blocks: {e.code}의 D영역 블록 없음")
