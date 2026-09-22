# 임진강김치 PLC 데이터수집 디지털 트윈

㈜임진강김치 스마트공장(선도형 스마트공장 구축지원사업)의 **센서·설비 → PLC 제어반(LS산전 XBC-DN32H Master/Slave) → Edge Collector → MES** 수집 경로를 소프트웨어로 재현하고, 수집 현황을 실시간 대시보드로 보여줍니다. 장비 22개(염도센서 2, 온습도센서 10, 온도조절기 4, 금속검출기, 소독수 모듈, 아이스박스자동포장기, 저울·충진기·속넣기기계)가 RS-485(Modbus RTU), Ethernet(Modbus TCP), OPC-UA, RS-232(ASCII)로 데이터를 내보냅니다. PLC 트윈과 Edge 트윈은 이 데이터를 실제 프로토콜로 읽습니다. MES 스텁은 SF-TD5 설계 그대로 `IF_SENSOR_RAW`에 적재한 뒤 공정별 테이블로 나눕니다. 설비로 쓰기 명령은 보내지 않습니다.

> 배경·범위: [`intro.md`](intro.md) · [`problem.md`](problem.md) · [`spec.md`](spec.md)
> 설계: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/UI_DESIGN.md`](docs/UI_DESIGN.md) · 결정 기록 [`docs/DECISIONS.md`](docs/DECISIONS.md) · 시험 결과 [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md)

## 빠른 시작

사전 요구사항: macOS/Linux, [uv](https://docs.astral.sh/uv/) (Python 3.12 자동 설치), Node.js 20+

```bash
make setup      # Python·npm 의존성 설치
make run        # 백엔드(:8000) + 대시보드 개발 서버(:5173)
```

브라우저에서 http://127.0.0.1:5173 을 엽니다. 대시보드를 빌드해 포트 하나로 쓰려면 `make run-prod`를 실행하고 http://127.0.0.1:8000 을 엽니다.

| 명령 | 동작 |
|---|---|
| `make run` | 백엔드 + 대시보드 dev 서버. 시작할 때 MES·Edge DB를 새로 만든다 |
| `make run-prod` | 대시보드 빌드 후 8000 포트 하나로 서빙 |
| `make demo` | 기동 30초 뒤 시나리오 4종을 1분 간격으로 자동 실행 |
| `make test` | ruff + mypy + pytest(단위·통합·수용·안전, 커버리지) + vitest |
| `make e2e` | Playwright 스모크 (빌드된 대시보드 + 임시 서버) |
| `make clean` | `data/`, 빌드 산출물 삭제 |

## 구성

```
Field Simulator ──RS-485(RTU)/Ethernet──▶ PLC Master·Slave ──Modbus TCP──▶ Edge Collector ──HTTP──▶ MES 스텁 ──WS──▶ 대시보드
   (22개 장비)          OPC-UA·RS-232·Modbus TCP (직결) ─────────────────▶      (버퍼·재전송)      (IF_SENSOR_RAW → 공정 테이블)
```

모든 계층은 한 프로세스에서 돌고, 계층 사이는 모두 127.0.0.1 소켓(실제 프로토콜)으로 통신합니다(D-003). 가상 RS-485는 RTU 바이트를 그대로 싣는 TCP 링크입니다. `socat`은 필요 없습니다.

| 디렉터리 | 내용 |
|---|---|
| `config/` | 장비·버스(`equipment.yaml`), D영역 맵(`plc_map.yaml`), CCP 기준(`ccp_std.yaml`), 시나리오, 포트·주기(`runtime.yaml`) |
| `src/twin/field` | 공정 모델 8종, 프로토콜 서버, 고장 주입 |
| `src/twin/plc` | 버스 스캐너, D영역 메모리, 읽기 전용 Modbus TCP 서버 |
| `src/twin/edge` | PLC 리더·직결 드라이버, 노이즈 필터, SQLite 버퍼, 전송기 |
| `src/twin/mes` | 스키마(TD5), 적재·분배, 알람, 토폴로지, REST·WebSocket |
| `dashboard/` | React + Vite 대시보드 |
| `tests/` | unit · integration · acceptance(AC-01~14) · safety |

## 화면

| 경로 | 화면 |
|---|---|
| `/` | 개요 — 수집 토폴로지(UI-02), 상태 분포, PLC, 활성 알람 |
| `/process` | 공정 현황(UI-03) — 공정 흐름 위 장비 카드, 절임통 8기 |
| `/collection` | 수집 현황 표(UI-04) — 성공률·응답시간·오류 유형, 정렬·필터 |
| `/equip/:code` | 장비 상세(UI-05) — 태그, 1시간 추이, 원시 프레임 |
| `/plc` | PLC 메모리(UI-06) — Master/Slave D영역, 진단, 거부된 쓰기 |
| `/edge` | Edge 버퍼(UI-07) — 대기·재전송·보존 삭제, 노이즈 필터 |
| `/raw` | 수집 원장(UI-08) — `IF_SENSOR_RAW`, 분배 테이블 행 수 |
| `/alarms` | 알람(UI-09) — 활성·이력·CCP 기준 |
| `/sim` | 시뮬레이션 제어(UI-10) — 고장 12종, 시나리오 프리셋 |
| `/kiosk` | 현황판 모드 — 토폴로지 → 공정 → 알람 15초 순환 |

API 문서는 실행 중 http://127.0.0.1:8000/docs 에서 볼 수 있습니다.

## 가상 장비를 실장비로 바꾸기

설비별로 연결 정보만 바꾸면 되고, 드라이버·대시보드는 그대로입니다.

```yaml
# config/equipment.yaml
buses:
  M1: {plc: MASTER, link: bus_M1, endpoint: /dev/tty.usbserial-A1, baud: 9600, timeout_ms: 300, retries: 2}
```

- RS-485 버스: `buses.<id>.endpoint`에 `/dev/...`(직렬 포트) 또는 `tcp://host:port`(시리얼-이더넷 컨버터)
- Ethernet·OPC-UA·저울: `runtime.yaml`의 `ports` 또는 장비의 `via.endpoint`
- 현재 한계: 모든 연결이 `runtime.host` 하나를 공유하고 계층이 한 프로세스에서 뜹니다. 실제 PLC(PLC별 IP 지정)에 Edge만 붙이는 구성과 계층별 개별 실행은 v0.2 과제입니다

## `[가정]` 값과 바꿀 위치

현장 실사 전이라 설계서에 없는 값은 가정으로 두었습니다. 대시보드에는 점선 "가정" 배지로 표시됩니다. 전체 목록은 `problem.md` 8장(Q1~Q10)과 `docs/PLAN.md` 3장에 있습니다.

| 항목 | 위치 |
|---|---|
| 센서 레지스터 맵, 통신 프로토콜, 수집 주기 | `config/equipment.yaml` `items[].reg`, `poll_ms`, `assumed` |
| 염도센서 2식 ↔ 절임통 8기 매핑, 절임 조건 | `config/equipment.yaml` `sim.tanks`, `tanks` |
| PLC D영역 주소 | `config/plc_map.yaml` |
| 냉장·냉동 온도, 염도 허용폭, 포장 중량, 지속시간 | `config/ccp_std.yaml` (`basis: 가정`) |
| Edge 버퍼 보존 기간 | `config/runtime.yaml` `edge.retention_hours` |
| 저울·충진기·속넣기기계 통신 방식 | `config/equipment.yaml` SCALE-01, FILL-01, STUFF-01 |

## DB 일일 정리

수집 데이터가 하루 약 260 MB씩 쌓이므로 매일 KST 03:00에 정리합니다(D-017). 설정은 `config/runtime.yaml`에 있습니다.

```yaml
mes:
  purge:
    enabled: true
    at: "03:00"      # 매일 정리 시각 (KST)
    keep_hours: 0    # 0 = 그 이전 수집 데이터 전부 삭제, 24 = 최근 하루 보존
    vacuum: true     # 삭제 후 파일 크기 축소
```

- 기준정보, 진행 중 절임 운영, 열린 가동 구간, 해제되지 않은 알람은 남깁니다. 수집은 멈추지 않고 곧바로 다시 쌓입니다.
- 이력은 `TWIN_PURGE_LOG`, 상태는 `GET /api/admin/purge`, 수동 실행은 `POST /api/admin/purge` 또는 대시보드 **수집원장 → DB 일일 정리 → 지금 정리**(두 번 눌러 확인)입니다.

## 테스트

```bash
make test   # 린트·타입 + pytest 76건(약 10분) + vitest 12건
make e2e    # Playwright 2건
```

수용 기준 AC-01~14는 `tests/acceptance/test_ac01.py`~`test_ac14.py`에 1:1로 있습니다. 긴 지속시간(1분·5분·10분)은 테스트에서 설정 오버라이드로 줄였습니다(D-004). 최근 결과는 [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md)에 있습니다.
