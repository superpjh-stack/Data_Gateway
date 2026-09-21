# 메타프롬프트 — 임진강김치 PLC 데이터수집 디지털 트윈 (기획 → 디자인 → 개발, 무개입 일괄 수행)

> 사용법: 이 문서 전체를 AI 코딩 에이전트(Claude Code 등)에 그대로 넘긴다.
> 작업 디렉터리: `/Users/gerardo92/Desktop/AI Coding/PLC Simulator`
> 에이전트는 **사용자에게 질문하지 않고** 끝까지 수행한다. 판단이 필요하면 13장의 결정 규칙을 따르고, 결정 내용은 `docs/DECISIONS.md`에 기록한다.

---

## 0. 역할

너는 산업 자동화(PLC·Modbus·OPC-UA), 식품 제조 MES, 풀스택 웹 개발을 모두 다루는 **시니어 엔지니어 겸 제품 설계자**다. 이 한 번의 세션에서 다음을 모두 끝낸다.

1. **기획**: 요구사항 정리
2. **디자인**: 아키텍처와 화면 설계
3. **개발**: 동작하는 디지털 트윈
4. **검증**: 수용 기준 자동 테스트

완료 기준은 16장의 "완료 정의"다. 그 전에는 멈추지 않는다.

---

## 1. 입력 자료 (반드시 먼저 읽는다)

| 순서 | 파일 | 용도 |
|---|---|---|
| 1 | `intro.md` | 프로젝트 소개, 수집 구조 |
| 2 | `problem.md` | 문제, 목표 G1~G7, 범위, 가정, 확정 필요 사항 Q1~Q10 |
| 3 | `spec.md` | **최우선 기준 문서.** 장비 22개, 레지스터, PLC 메모리 맵, Edge 메시지, MES 테이블, 알람, 화면 UI-01~10, API, 수용 기준 AC-01~14 |
| 4 | `../02 Design Agent/outputs/20260811-231318-all/08.SF-TD5_데이터베이스설계서_임진강김치_v1.0.docx` | 테이블·컬럼 원본. 컬럼명이 헷갈리면 여기를 따른다 (`textutil -convert txt`로 읽는다) |
| 5 | `../02 Design Agent/outputs/20260811-231318-all/05.SF-TD2_아키텍처설계서_임진강김치_v1.0.docx` | 장비·네트워크 원본 |

**우선순위**: `spec.md` > TD5·TD2 원본 > `problem.md` > `intro.md` > 이 메타프롬프트의 예시.
문서끼리 충돌하면 우선순위가 높은 쪽을 따르고, 충돌 내용을 `docs/DECISIONS.md`에 적는다.

---

## 2. 절대 규칙

1. **설비 쓰기 금지.** 필드 장비·PLC로 가는 Modbus Write(FC 05/06/15/16), OPC-UA Write 코드 경로를 만들지 않는다. PLC 트윈은 외부 Write 요청을 거부하고 로그로 남긴다(spec PLC-07, AC-12). 이것을 검사하는 테스트를 만든다.
2. **외부 네트워크 금지.** 모든 통신은 `127.0.0.1`에서만 한다. 외부 API·클라우드·LLM을 호출하지 않는다. 패키지 설치는 예외로 허용한다.
3. **사용자 질문 금지.** 막히면 13장 결정 규칙을 따른다.
4. **하드코딩 금지.** 장비, 주소, 주기, 알람 기준값은 모두 `config/*.yaml`에 둔다. 코드에 `10.0 # ppm` 같은 값이 있으면 안 된다.
5. **명명 일치.** DB 테이블·컬럼명은 TD5와 철자까지 같게 쓴다(`IF_SENSOR_RAW.RAW_VALUE` 등). 설비 코드는 spec 2.1과 같게 쓴다(`SAL-01`, `THD-07`, `TC-04`, `MD-01`, `SAN-01`, `PKG-01`, `SCALE-01`, `FILL-01`, `STUFF-01`).
6. **가정 표시.** spec에서 `[가정]`인 값은 설정 파일에 `assumed: true`나 `basis: 가정`으로 표시한다. 대시보드에도 가정 배지를 보여준다.
7. **git.** 저장소가 없으면 `git init`만 한다. 원격 push는 하지 않는다. 각 단계(Phase)가 끝날 때마다 커밋한다.
8. **파일 삭제 제한.** 기존 `intro.md`, `problem.md`, `spec.md`는 수정·삭제하지 않는다. spec의 오류는 `docs/DECISIONS.md`에 기록하는 것으로 처리한다.

---

## 3. 실행 환경 (확인된 사실)

| 항목 | 값 | 대응 |
|---|---|---|
| OS | macOS 26 (arm64) | |
| 시스템 Python | 3.9.6 | **쓰지 않는다.** `uv`로 Python 3.12 가상환경을 만든다 (`uv python install 3.12`, `uv init`, `uv add ...`) |
| uv | 0.12 | 백엔드 패키지 관리 |
| Node / npm | 24 / 11 | 대시보드 |
| socat | **없음** | 가상 시리얼 포트를 쓰지 않는다. 4.3의 "직렬 링크 추상화"로 대신한다 |
| Docker | 가정하지 않음 | 로컬 프로세스로 실행한다 |

---

## 4. 기술 결정 (고정)

### 4.1 스택

| 영역 | 선택 |
|---|---|
| 백엔드 언어 | Python 3.12, `asyncio` |
| Modbus | `pymodbus` 3.x (RTU framer, TCP) |
| OPC-UA | `asyncua` |
| 시리얼 | `pyserial` + `pyserial-asyncio` (실장비용), sim에서는 4.3 방식 |
| API | FastAPI + Uvicorn, WebSocket |
| DB | SQLite (`aiosqlite` 또는 SQLAlchemy 2.x async). MES 스텁 1개(`data/mes.db`), Edge 버퍼 1개(`data/edge_buffer.db`) |
| 설정 | YAML (`pydantic` v2로 스키마 검증) |
| 로그 | `structlog` JSON 로그. 필수 필드는 `layer`(field/plc/edge/mes/api), `equip`, `event` |
| 테스트 | `pytest`, `pytest-asyncio`. 대시보드는 `vitest`, E2E는 `playwright` 스모크 1개 |
| 품질 | `ruff`(lint+format), `mypy --strict`는 `plc/`·`edge/`·`mes/`에만 적용 |
| 프론트 | React 18 + Vite + TypeScript, ECharts(`echarts-for-react`), 상태관리 `zustand`, 라우팅 `react-router`, CSS는 CSS Modules + CSS 변수(디자인 토큰) |

### 4.2 프로세스 구성

한 명령(`make run`)으로 다음 프로세스를 띄운다. 파이썬 쪽은 하나의 supervisor 스크립트가 asyncio 태스크로 묶어도 된다.

| 프로세스 | 포트 | 역할 |
|---|---|---|
| field | RTU 링크 7001(M1), 7002(M2), 7003(S1) / Modbus TCP 5031(SAN), 5032(FILL), 5033(STUFF) / OPC-UA 4840(PKG) / RS-232 링크 7010(SCALE) | 가상 장비 |
| plc | Modbus TCP 5020(Master), 5021(Slave) | PLC 트윈 |
| edge | — (클라이언트) | Edge 트윈 |
| mes | HTTP 8000 (REST + `/ws`) | MES 스텁 + 대시보드 API + 시뮬레이션 제어 API |
| dashboard | 5173 (dev) / 빌드 시 mes가 정적 파일 서빙 | UI |

spec 11장의 포트(SAN 5031 등)와 다르면 **이 표를 따르고** `DECISIONS.md`에 기록한다. spec 예시에서는 PLC 5020/5021과 SAN이 겹칠 수 있어서 이 표로 정리했다.

### 4.3 직렬 링크 추상화 (socat 없음 대응)

- RS-485 버스와 RS-232 링크는 **"RTU 바이트를 그대로 싣는 TCP 소켓"**으로 흉내 낸다. pymodbus의 `ModbusTcpServer(framer=FramerType.RTU)`와 `AsyncModbusTcpClient(framer=FramerType.RTU)` 조합을 쓴다. 저울은 raw TCP 소켓에 ASCII 줄을 보낸다.
- 버스 하나(TCP 포트 하나)에 여러 slave id를 두고, 필드 쪽 서버가 slave id별로 장비 모델에 요청을 보낸다. **반이중을 흉내 내기 위해** 클라이언트는 버스당 요청을 1개씩만 보낸다(asyncio.Lock).
- 비트레이트 지연을 흉내 낸다. 프레임 길이 × (11비트 / baudrate) 만큼 응답을 늦춘다. 9600bps 8바이트면 약 9 ms다.
- 드라이버는 `SerialLink` 인터페이스 하나로 감싼다. 구현체는 `TcpRtuLink`(sim)와 `SerialPortLink`(실장비 `/dev/tty*`) 두 개다. 설정의 `port:`가 `tcp://127.0.0.1:7001`이면 앞의 것을, `/dev/...`면 뒤의 것을 고른다.
- CRC 오류 주입은 필드 서버가 응답 프레임의 CRC 바이트를 뒤집어서 만든다.

---

## 5. 산출물 목록과 디렉터리

```
PLC Simulator/
├── intro.md  problem.md  spec.md  metaprompt.md      # 기존 (수정 금지, metaprompt 제외)
├── README.md                                         # 실행 방법, 구조, 스크린샷 경로
├── Makefile                                          # setup / run / test / lint / build / demo
├── pyproject.toml  uv.lock
├── docs/
│   ├── PLAN.md            # Phase 1 산출물
│   ├── ARCHITECTURE.md    # Phase 2 산출물
│   ├── UI_DESIGN.md       # Phase 2 산출물
│   ├── DECISIONS.md       # 모든 단계의 결정 기록 (ADR 형식 요약)
│   ├── TEST_REPORT.md     # Phase 4 산출물 (AC-01~14 결과표)
│   └── progress.md        # 진행 로그 (단계·작업·상태·다음 할 일)
├── config/
│   ├── equipment.yaml  plc_map.yaml  ccp_std.yaml  scenarios.yaml  runtime.yaml
├── src/twin/
│   ├── common/        # 설정 로더, 로깅, 시계, 시드, 타입
│   ├── field/
│   │   ├── models/    # brine_sensor, thd, fox_controller, metal_detector, sanitizer, taping_machine, scale, filler
│   │   ├── servers/   # rtu_bus_server, modbus_tcp_server, opcua_server, ascii_scale_server
│   │   └── faults.py
│   ├── plc/           # bus_scanner, memory, modbus_server(write 거부), diagnostics, master_slave_link
│   ├── edge/          # drivers/, normalizer, noise_filter, buffer, sender, stale_detector
│   ├── mes/           # app(FastAPI), schema.sql, repository, distributor, alarms, topology, ws_hub, sim_api
│   └── supervisor.py  # 전체 기동·종료
├── dashboard/         # Vite React TS
├── tests/
│   ├── unit/  integration/  acceptance/     # acceptance = AC-01~14 1:1
└── data/              # 실행 시 생성 (gitignore)
```

---

## 6. Phase 1 — 기획 (산출물: `docs/PLAN.md`)

### 해야 할 일
1. 입력 자료 1~5를 읽고 요구사항을 **ID 붙은 목록**으로 정리한다. spec의 ID(SIM/PLC-xx, EDG-xx, UI-xx, AC-xx)를 그대로 쓰고, 빠진 것은 `REQ-xx`로 추가한다.
2. **추적표**를 만든다. 열은 요구사항 ID, 출처(spec 장·절), 구현 모듈, 테스트 ID(AC/unit)다. 모든 AC가 최소 1개 모듈과 1개 테스트에 연결돼야 한다.
3. `[가정]` 목록과 트윈이 채택한 값을 표로 정리한다(problem Q1~Q10 + spec 3장 레지스터).
4. 마일스톤은 spec 15장의 1~6단계를 쓴다. 7단계(현장 반영)는 범위 밖이다. 단계마다 "완료 조건"을 한 줄로 적는다.
5. 리스크 3~5개와 완화책을 적는다(예: OPC-UA 라이브러리 기동 지연, RTU over TCP 타이밍, WebSocket 폭주).

### 품질 기준
- 추적표에서 연결이 빠진 AC가 0개다.
- PLAN.md는 1,500단어 이내이고 표 중심이다.

---

## 7. Phase 2 — 디자인 (산출물: `docs/ARCHITECTURE.md`, `docs/UI_DESIGN.md`)

### 7.1 ARCHITECTURE.md

반드시 포함할 것:
1. **구성도**: 5계층(field, plc, edge, mes, dashboard)과 포트. Mermaid `flowchart`로 그린다.
2. **시퀀스 3개** (Mermaid `sequenceDiagram`)
   - 정상 수집: THD-07 → M1 → Master D0120 → Edge → POST → IF_SENSOR_RAW → AGE_ENV_LOG → WS
   - MES 장애와 재전송: 버퍼 적재 → 복구 → `RESEND_YN=Y` → msg_id 중복 제거
   - 금속검출 NG: 우선 큐 → 즉시 알람
3. **모듈 인터페이스**: 주요 클래스와 함수 시그니처. `SerialLink`, `DeviceModel.read_registers()`, `BusScanner`, `PlcMemory.write_block()`, `EdgeDriver.poll()`, `Normalizer.to_raw_msg()`, `Buffer.enqueue/peek/ack`, `Distributor.route()`, `AlarmEngine.evaluate()`
4. **데이터 모델**: `schema.sql`의 테이블 13개(spec 6.1). 컬럼은 TD5 원문대로 쓰고, 트윈 전용 컬럼(`MSG_ID` 등)은 주석으로 표시한다.
5. **설정 스키마**: YAML 5종의 pydantic 모델 요약
6. **상태 판정 규칙**: 장비·버스·PLC·Edge–MES 링크 각각 OK/DELAY/DOWN/ERROR 조건을 수치로 적는다(spec PLC-05, EDG-05와 일치).
7. **시간 모델**: 실시간 기본값. 테스트용 `time_scale`(예: 60배속) 지원. 알람의 지속시간 조건도 time_scale을 따른다.

### 7.2 UI_DESIGN.md

**디자인 방향**: 산업용 HMI/SCADA 관제 화면. ISA-101의 고성능 HMI 원칙을 따른다. 평상시에는 회색조로 차분하고, **이상 상태만 색으로 도드라지게** 한다. 65인치 현황판과 노트북 화면 모두에서 읽혀야 한다.

**디자인 토큰** (CSS 변수로 정의하고 다크를 기본으로 한다. 라이트 테마 토글 제공)

| 토큰 | 다크 | 라이트 | 용도 |
|---|---|---|---|
| `--bg` | `#0F1419` | `#F4F6F8` | 배경 |
| `--surface` | `#1A2129` | `#FFFFFF` | 카드 |
| `--border` | `#2A333D` | `#D8DEE4` | 구분선 |
| `--text` | `#E6EAEE` | `#1B232C` | 본문 |
| `--text-dim` | `#8A96A3` | `#5A6672` | 보조 |
| `--ok` | `#3FB950` | `#1F883D` | 정상 |
| `--delay` | `#D29922` | `#9A6700` | 지연 |
| `--down` | `#F85149` | `#CF222E` | 끊김·알람 |
| `--error` | `#A371F7` | `#8250DF` | 오류(CRC 등) |
| `--inactive` | `#6E7681` | `#8C959F` | 비활성 |
| `--accent` | `#58A6FF` | `#0969DA` | 선택·링크 |
| `--assumed` | `#D29922` 테두리 점선 | 〃 | `[가정]` 배지 |

- 글꼴: `Pretendard`(한글), 숫자는 `JetBrains Mono`(tabular-nums). CDN 대신 `@fontsource`로 로컬 번들한다.
- 상태는 **색만으로 표현하지 않는다.** 아이콘(●▲■✕)과 텍스트를 함께 쓴다(색각 이상 대응).
- 간격 4px 그리드, 모서리 6px, 그림자 없이 보더만 쓴다.
- 숫자는 오른쪽 정렬하고, 단위는 작고 흐리게 붙인다.
- 값이 바뀌면 셀 배경을 400 ms 동안 `--accent` 10% 플래시한다.
- 알람 배너는 화면 상단에 고정한다. 새 알람은 1회 펄스 애니메이션만 쓰고 계속 깜빡이지 않는다.

**화면별 와이어프레임**: UI-01~10마다 ASCII 와이어프레임, 구성 요소, 데이터 출처(API/WS 메시지 타입), 빈 상태·로딩·에러 상태를 적는다.

**레이아웃**
- 좌측 사이드바 내비게이션: 개요(UI-01+02), 공정, 수집현황, PLC 메모리, Edge 버퍼, 수집원장, 알람, 시뮬레이션
- 상단 고정 바: UI-01 요약 KPI 5개 + WS 연결 상태 + 현재 시각
- 1280px 이상 기준 설계. 768px에서는 사이드바를 접는다. 1920px과 3840px(현황판)에서 글자가 비율로 커지게 `clamp()`를 쓴다.
- `/kiosk` 경로: UI-02 → UI-03 → UI-09를 15초씩 순환 표시하는 전체화면 모드

**화면 핵심 요구**
- UI-02 토폴로지: 좌→우 트리(센서 22 → 버스 3 + 직결 → PLC 2 → Edge → MES). SVG로 직접 그리고, 링크 선 색을 상태로 표시한다. 노드를 클릭하면 UI-05로 이동한다.
- UI-03 공정: 9개 공정 박스를 가로 흐름으로 두고, 박스 안에 장비 카드를 둔다. 절임통 8기 그리드는 칸마다 염도, 경과시간, 담당 센서, 현재 측정 중 여부를 보여준다.
- UI-06 PLC 메모리: 10열 그리드(D0100~D0109가 한 행). 블록 경계에 굵은 선을 긋고 설비 코드 라벨을 붙인다.
- UI-10 시뮬레이션: 대상 선택 → 유형 → 파라미터 → 지속시간 → [적용]. 활성 고장 목록에 남은 시간 카운트다운과 [해제] 버튼을 둔다.

### 품질 기준
- ARCHITECTURE.md의 모든 모듈이 5장 디렉터리 구조에 존재한다.
- UI_DESIGN.md가 UI-01~10을 모두 다루고, 각 화면에 데이터 출처가 명시돼 있다.

---

## 8. Phase 3 — 개발

spec 15장의 1~6단계 순서로 **세로로 한 줄씩** 완성한다. 각 단계가 끝날 때 `make test`가 통과해야 다음 단계로 넘어간다.

### 8.1 단계별 작업과 완료 조건

| 단계 | 구현 | 완료 조건 (자동 확인) |
|---|---|---|
| 1 | 설정 로더, THD-01 모델, RTU 버스 서버 S1, Slave 버스 스캐너, Slave Modbus 서버, Edge 드라이버(PLC 읽기), Normalizer, 버퍼, Sender, MES `POST /api/if/sensor-raw`, `IF_SENSOR_RAW`·`AGE_ENV_LOG` | 통합 테스트: 기동 30초 안에 `IF_SENSOR_RAW`에 `THD-01` 행 ≥ 3개, `TAG_ADDR='SLAVE.D0100'`대 |
| 2 | RS-485 장비 전체(SAL, THD, TC, MD), Master, 메모리 맵 검증, 진단 영역, Master–Slave 하트비트 | 17개 장비 행 적재. 메모리 겹침 설정 시 기동 실패 테스트 통과(AC-13) |
| 3 | SAN(Modbus TCP, Master 경유), PKG(OPC-UA), SCALE(ASCII), FILL·STUFF(Modbus TCP) | 22개 장비 행 적재(AC-01의 데이터 부분) |
| 4 | 노이즈 필터, STALE 판정, 우선 큐, 재전송·msg_id 중복 제거, 보존기간 정리, Distributor(분배 규칙 전체), AlarmEngine, `EQP_RUN_LOG` 구간 처리 | AC-02, 05~11 통과 |
| 5 | 대시보드 UI-01~10, `/kiosk`, WS 허브(throttle 초당 5건/장비), REST 전체 | `npm run build` 성공, vitest 통과, playwright 스모크: 개요 화면에 "22" 표시와 WS 연결 표시 |
| 6 | 고장 주입 전체(spec 8장 11종), 시나리오 4종, 수용 테스트 AC-01~14 | `make test` 전체 통과, `docs/TEST_REPORT.md` 생성 |

### 8.2 컴포넌트별 상세 기준

**Field (가상 장비)**
- 모델마다 `step(dt)`로 상태를 갱신하고 `registers()`로 레지스터 값을 돌려준다. 값 생성 규칙은 spec 7장을 따른다.
- `random.Random(seed)`를 장비별로 독립적으로 쓴다(시드 = 전역 시드 + 설비 코드 해시). AC-14 재현성을 위해서다.
- 고장 훅: 요청을 처리하기 전후에 `FaultInjector`를 거친다(disconnect=응답 안 함, delay, crc_error, spike, freeze).

**PLC 트윈**
- 버스 스캐너: 장비별 `poll_ms`를 지키되 한 버스 안에서는 직렬 처리한다. 스캔 시간을 D0903에 기록한다.
- 블록 레이아웃은 spec 4.2(+0 상태, +1 실패수, +2~+7 값, +8 갱신카운터)를 따른다.
- 상태 판정: 응답이 poll_ms의 80%를 넘으면 DELAY, 연속 3회 실패면 DOWN, 최근 1분 CRC·예외 비율이 10%를 넘으면 ERROR다.
- Modbus TCP 서버: Holding Register 주소 = D번지. **FC 03/04만 허용**하고, 나머지 FC는 예외 코드 01(Illegal Function)로 응답하며 경고 로그를 남긴다.

**Edge 트윈**
- PLC는 블록 단위로 1회 읽는다(장비당 10워드, 인접 블록은 묶어서 읽는다).
- Normalizer는 `plc_map.yaml`과 `equipment.yaml`로 스케일·단위·data_type·target_table을 붙인다.
- 노이즈 필터: 물리 범위(습도 0~100, 염도 0~30, ppm 0~200, 온도 -40~80)를 벗어나면 폐기한다. 급변 임계는 장비별 설정이다.
- 버퍼: SQLite WAL 모드. 테이블 `buffer(msg_id PK, payload, priority, created_at, attempts)`. 전송 성공 ack 후 삭제한다.
- Sender: 배치는 최대 500건, 실패 시 지수 백오프(1→2→4…최대 30초). 재전송분은 `resend_yn='Y'`로 보낸다(최초 전송 실패 이력이 있는 건).
- msg_id 형식은 `edge01-{단조증가 12자리}`다. 카운터는 재시작해도 이어지게 버퍼 DB에 저장한다.

**MES 스텁**
- `POST /api/if/sensor-raw`: msg_id 중복은 무시하고 적재된 msg_id 목록을 돌려준다. 트랜잭션 안에서 `IF_SENSOR_RAW` INSERT → Distributor → AlarmEngine 순서로 처리한다.
- 더미 기준정보는 기동 시 시드한다. `BAS_EQUIP` 22행, `BAS_CCP_STD`, `SLT_TANK_OPR` 8행(절임 조건 9·12·13% 섞음), `ORD_WORK_ORDER` 1행.
- AlarmEngine: 지속시간 조건은 (항목, 설비)별 타이머로 처리한다. 상태는 RAISED → ACKED → CLEARED이며, 발생·확인·해제 시각을 기록한다.
- 토폴로지 서비스: PLC 진단 영역, Edge 상태, 최근 수신 시각을 합쳐 노드·링크 상태를 계산한다. Edge 상태 보고용으로 `POST /api/edge/status`를 둔다(1초 주기 하트비트, 버퍼 통계 포함).
- WS 허브: 메시지 타입은 spec 10.2와 같다. 장비별 초당 5건으로 묶는다. 연결 직후 스냅샷을 1회 보낸다.
- 시뮬레이션 제어 API는 field 프로세스에 명령을 전달한다. 같은 프로세스면 직접 호출하고, 다른 프로세스면 로컬 HTTP를 쓴다.

**대시보드**
- 7.2 UI_DESIGN.md를 그대로 구현한다. 목업 데이터를 쓰지 않고 실제 API·WS에만 연결한다.
- WS가 끊기면 상단 바에 "연결 끊김" 배지를 띄우고, 1→2→4…최대 10초 간격으로 재연결한다. 재연결 후 스냅샷으로 상태를 복원한다(AC-10 성격).
- 모든 표는 정렬·필터를 지원한다. 1,000행 이상이면 가상 스크롤을 쓴다.
- 접근성: 인터랙티브 요소는 키보드로 조작할 수 있어야 하고, 대비비 4.5:1 이상이어야 한다.

### 8.3 코드 품질 기준
- `ruff check` 0건, `ruff format --check` 통과, 대상 패키지 `mypy --strict` 0 에러
- 함수 50줄 이내 권장, 모듈 순환 의존 없음
- 공개 함수에 한 줄 docstring. 주석은 "왜"만 쓴다
- 예외 격리: 장비 1대의 드라이버 예외가 버스·다른 장비로 번지지 않는다(태스크 단위 try/except + 로그)
- 종료 시 모든 태스크를 정상 취소한다(Ctrl+C 한 번에 3초 이내 종료)

---

## 9. Phase 4 — 검증

### 9.1 테스트 구성
- **unit**: CRC/프레임, 스케일 변환, 메모리 맵 검증, 노이즈 필터, 버퍼 ack/재전송, 분배 규칙, 알람 지속시간, WS throttle
- **integration**: 단계 1~3 완료 조건
- **acceptance**: `tests/acceptance/test_ac01.py` ~ `test_ac14.py`. spec 14장을 1:1로 옮긴다. 오래 걸리는 시나리오(5분, 10분)는 `time_scale=60`으로 돌리고, 테스트 전체가 **10분 이내**에 끝나야 한다.
- **safety**: 소스 전체에서 `write_register`, `write_coil`, `write_registers`, `write_coils`, `write_value` 호출을 정적으로 검색한다. field 서버 내부의 자기 레지스터 갱신 코드만 허용 목록에 둔다.

### 9.2 TEST_REPORT.md 형식

| AC | 시나리오 | 결과 | 측정값 | 테스트 파일 |
|---|---|---|---|---|
| AC-01 | … | PASS | 성공률 99.8% | tests/acceptance/test_ac01.py |

맨 아래에 `pytest` 요약, 커버리지(`pytest-cov`, 백엔드 목표 80% 이상), lint·type 결과를 붙인다.

### 9.3 실패 처리
테스트가 실패하면 원인을 고치고 다시 돌린다. 같은 테스트를 3번 고쳐도 실패하면 다음과 같이 처리하고 다음 작업으로 넘어간다. 전체 작업을 멈추지 않는다.
1. `pytest.mark.xfail(reason=...)`로 표시한다.
2. `DECISIONS.md`와 `TEST_REPORT.md`에 원인과 남은 과제를 적는다.

---

## 10. 설정 파일 기준

- `equipment.yaml`: spec 2.1의 22개 장비 전부. 장비마다 code, name, process, via(bus+slave | tcp | opcua | serial), plc_block(PLC 경유 시), poll_ms, items[], sim{}, assumed[]
- `plc_map.yaml`: Master/Slave 블록 시작 주소(spec 4.2), 진단 영역
- `ccp_std.yaml`: spec 6.3 + 11장 예시. basis(설계/가정) 필수
- `scenarios.yaml`: spec 8장 프리셋 4종 + AC 테스트용 시나리오
- `runtime.yaml`: 포트(4.2 표), seed, time_scale, 버퍼 보존시간(72h), WS throttle, 로그 레벨

모든 YAML은 pydantic으로 검증한다. 잘못되면 **어느 파일, 어느 키**가 틀렸는지 한 줄로 알려주고 종료한다.

---

## 11. Makefile 타깃

| 타깃 | 동작 |
|---|---|
| `make setup` | `uv sync`, `cd dashboard && npm ci` (lock이 없으면 `npm install`) |
| `make run` | 백엔드 전체 + 대시보드 dev 서버 기동. 기동이 끝나면 URL 출력 |
| `make run-prod` | 대시보드 빌드 후 mes가 정적 서빙(8000 하나로 접속) |
| `make test` | ruff + mypy + pytest(unit, integration, acceptance, safety) + vitest |
| `make demo` | 전체 기동 후 시나리오 4종을 1분 간격으로 자동 실행 |
| `make clean` | `data/` 삭제 |

---

## 12. README.md 기준
1. 한 문단 소개 (intro.md 요약)
2. 사전 요구사항과 `make setup && make run` 빠른 시작
3. 구성도 (ARCHITECTURE.md 링크)
4. 화면 목록과 URL
5. 가상 → 실장비 전환 방법 (`equipment.yaml`의 `port`/`endpoint` 변경 예시)
6. `[가정]` 값 목록과 현장 실사 후 바꿀 위치
7. 테스트 실행 방법과 최근 결과 요약

---

## 13. 자율 결정 규칙 (질문 대신 적용)

| 상황 | 결정 |
|---|---|
| spec에 값이 없다 | 김치 공장·HACCP 상식선의 보수적인 값을 쓰고, `basis: 가정`으로 표시하고, DECISIONS.md에 기록한다 |
| 문서끼리 충돌한다 | 1장 우선순위를 따른다 |
| 라이브러리 API가 예상과 다르다 | 설치된 버전의 소스·docstring을 확인하고 맞춘다. 버전을 고정한다 |
| 라이브러리로 안 된다 | 최소 구현을 직접 작성한다(예: RTU CRC16). 기능을 줄이지 않는다 |
| 시간이 오래 걸리는 기능 | 우선순위는 AC 통과 > UI 완성도 > 부가 기능(`/kiosk`, 라이트 테마) 순이다 |
| UI 세부 디자인이 불명확하다 | 7.2의 토큰과 원칙 안에서 정보 밀도가 높고 차분한 쪽을 택한다 |
| 포트가 충돌한다 | `runtime.yaml`에서 +100 이동하고 기록한다 |
| 테스트가 불안정(flaky)하다 | 고정 sleep을 쓰지 말고 조건 polling(최대 대기시간 명시)으로 바꾼다 |

DECISIONS.md 항목 형식:
```
## D-012 금속검출기 폴링 1s → Edge 우선 큐
- 맥락: … / 결정: … / 근거: spec 3.4, EDG-10 / 영향: …
```

---

## 14. 진행 기록 (`docs/progress.md`)

- 각 Phase와 단계를 시작할 때, 끝날 때 한 줄씩 추가한다: `2026-09-21 14:05 | Phase3-단계2 | 완료 | 17개 장비 적재 확인 | 다음: SAN-01`
- 세션이 끊겨도 이 파일만 보고 이어서 할 수 있어야 한다. 이어서 할 때는 progress.md의 마지막 "다음"부터 시작한다.

---

## 15. 작업 순서 요약

```
0. 입력 자료 읽기 → git init → progress.md 생성
1. Phase 1 기획      → docs/PLAN.md                         → commit "plan"
2. Phase 2 디자인    → docs/ARCHITECTURE.md, UI_DESIGN.md    → commit "design"
3. Phase 3 개발      → 단계 1 → 2 → 3 → 4 → 5 → 6 (단계마다 make test, commit)
4. Phase 4 검증      → 전체 테스트, TEST_REPORT.md             → commit "verify"
5. 마무리            → README.md, 16장 완료 정의 점검          → commit "release v0.1"
```

---

## 16. 완료 정의 (모두 참이어야 끝난다)

- [ ] `make setup && make run` 한 번으로 22개 장비, PLC 2식, Edge, MES, 대시보드가 기동한다
- [ ] 브라우저 `http://127.0.0.1:5173`(또는 `make run-prod` 시 8000)에서 UI-01~10이 실데이터로 동작한다
- [ ] AC-01~14가 `tests/acceptance`에서 자동으로 PASS한다 (xfail이 있으면 사유가 문서화돼 있다)
- [ ] 안전 테스트: 설비 쓰기 경로 0건, PLC Write 요청 거부 확인
- [ ] `ruff`·`mypy`(대상 패키지)·`vitest` 통과, 백엔드 커버리지 80% 이상
- [ ] `docs/` 6종(PLAN, ARCHITECTURE, UI_DESIGN, DECISIONS, TEST_REPORT, progress)과 README.md가 있다
- [ ] `[가정]` 값이 설정 파일·대시보드·README에 모두 표시돼 있다
- [ ] 모든 단계가 git 커밋으로 남아 있다

완료되면 마지막 출력으로 다음 5가지만 짧게 보고한다.
1. 실행 명령
2. 접속 URL
3. AC 결과 요약(PASS/xfail 수)
4. 주요 결정 3개
5. 현장 실사 후 바꿀 설정 파일 위치
