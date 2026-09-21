# PLAN — 임진강김치 PLC 데이터수집 디지털 트윈 v0.1

> 입력: `spec.md`(최우선), `problem.md`, `intro.md`, SF-TD5·TD2 원본 · 작성 2026-09-21

## 1. 요구사항 목록

| ID | 요구사항 | 출처 |
|---|---|---|
| SIM-01 | 설정 파일의 장비를 독립 모델로 구동 | spec 7 |
| SIM-02 | 공정 모델로 그럴듯한 값 생성 (염도 감소, 냉동기 히스테리시스 등) | spec 7 |
| SIM-03 | 프로토콜 서버: RTU 버스, Modbus TCP, OPC-UA, RS-232 ASCII | spec 3 |
| SIM-04 | 고장 주입 11종, 지속시간, 시나리오 프리셋 | spec 8 |
| SIM-05 | 시드 기반 재현성 | spec 7 |
| PLC-01~08 | 버스 순차 폴링, 재시도, 원시값 D영역 기록, SAN 경유, Modbus TCP 공개, Master–Slave 하트비트, **Write 거부**, 스캔 진단 | spec 4.1 |
| PLC-MAP | 10워드 블록 맵, 진단 영역, 기동 시 겹침·1:1 검증 | spec 4.2 |
| EDG-01~11 | PLC 블록 읽기, 직결 장비 수집, 정규화, 노이즈 필터, STALE, 버퍼, 재전송(RESEND_YN), 보존기간, NG 우선 큐, 제어 금지 | spec 5.1 |
| EDG-MSG | 표준 메시지 = `IF_SENSOR_RAW` 한 행 + msg_id | spec 5.2 |
| MES-01 | TD5 수집 관련 13개 테이블 | spec 6.1 |
| MES-02 | 분배 규칙 | spec 6.2 |
| MES-03 | 기준 이탈 알람 (설정 기반) | spec 6.3 |
| UI-01~10 | 대시보드 10개 화면 + `/kiosk` | spec 9 |
| API-01 | REST 13종 + WebSocket 7종 메시지 | spec 10 |
| NFR-01~08 | 지연 2 s, 무손실, 격리, YAML 확장, endpoint 교체, `make run`, JSON 로그, 쓰기 경로 0 | spec 12 |
| REQ-01 | 트윈 전용 알람 테이블 `TWIN_ALARM` (TD5에는 통합 알람 테이블이 없음) | 추가 (D-006) |
| REQ-02 | 장비 진단 지표(성공률·응답시간·오류유형)는 트윈 내부 조회로 제공 | 추가 (D-007) |

## 2. 추적표 (AC ↔ 모듈 ↔ 테스트)

| AC | 핵심 요구 | 구현 모듈 | 테스트 |
|---|---|---|---|
| AC-01 | 22개 정상, 성공률 ≥ 99 %, 22개 설비 적재 | field/*, plc/bus_scanner, edge/*, mes/ingest | tests/acceptance/test_ac01.py |
| AC-02 | D0100 ÷ 100 = 염도 = SLT_SALINITY_LOG | plc/memory, edge/normalizer, mes/distributor | test_ac02.py |
| AC-03 | bus_cut(M2) → M2 장비만 DOWN | field/faults, plc/bus_scanner, mes/topology | test_ac03.py |
| AC-04 | plc_down(SLAVE) → THD-01~06 STALE, D0902 정지 | plc/runtime, edge/plc_reader, mes/topology | test_ac04.py |
| AC-05 | 소독수 이탈 지속 → 알람, ALARM_YN=Y | mes/alarms, mes/distributor | test_ac05.py |
| AC-06 | 냉장 온도 이탈 지속 → AGE_ENV_ALARM | mes/alarms | test_ac06.py |
| AC-07 | 금속 NG → 2 s 이내 알람·QUA_METAL_LOG | edge/buffer(priority), mes/alarms | test_ac07.py |
| AC-08 | 포장기 정지→가동 → EQP_RUN_LOG 구간 | edge/drivers/opcua, mes/distributor | test_ac08.py |
| AC-09 | MES 장애 → 버퍼 → 복구 후 누락·중복 0, RESEND_YN=Y | edge/buffer, edge/sender, mes/ingest | test_ac09.py |
| AC-10 | Edge 재시작 후 버퍼 유지 | edge/buffer | test_ac10.py |
| AC-11 | 습도 150 % → FILTERED, 미적재 | edge/noise_filter | test_ac11.py |
| AC-12 | PLC Write 거부·로그·메모리 불변 | plc/modbus_server | test_ac12.py + tests/safety |
| AC-13 | 메모리 블록 겹침 → 기동 거부 | common/config, plc/memory | test_ac13.py |
| AC-14 | 같은 시드 → 같은 시퀀스 | field/models | test_ac14.py |

연결이 빠진 AC는 없다.

## 3. 가정값 채택표

| Q | 항목 | 채택값 | 위치 |
|---|---|---|---|
| Q1 | 수집 주기 | SAL·SAN·FILL·STUFF 5 s, THD·TC 10 s, MD 1 s, SCALE 1 s, PKG 구독 + 10 s | `config/equipment.yaml` `poll_ms` |
| Q2 | 버퍼 보존 | 72 h | `config/runtime.yaml` `edge.retention_hours` |
| Q3 | 염도센서 매핑 | SAL-01 → 1~4번 통, SAL-02 → 5~8번 통, 120 s마다 전환 | `equipment.yaml` `sim.tanks` |
| Q4 | 금속검출기 | 1대, RS-485 Modbus RTU | `equipment.yaml` MD-01 |
| Q5 | 저울 | RS-232 ASCII 요청/응답 | SCALE-01 |
| Q6 | 충진기·속넣기 | Modbus TCP | FILL-01, STUFF-01 |
| Q7 | 냉장고 | 숙성·원품·탈수 냉장 + 냉동 1 | TC-01~04 |
| Q8 | 온도·염도 기준 | 냉장 -1~5 ℃ (5분), 냉동 ≤ -18 ℃ (10분), 염도 목표 ±1.0 %p (5분) | `config/ccp_std.yaml` |
| Q9 | 망 분리 | 구분 안 함 | — |
| Q10 | 온습도 배분 | THD-01~06 → Slave S1, THD-07~10 → Master M1 | `equipment.yaml` |
| — | 레지스터 맵 | spec 3장 | `equipment.yaml` `items[].reg` |
| — | RS-485 통신 | 9600 8N1, 타임아웃 300 ms, 재시도 2 | `equipment.yaml` `buses` |

## 4. 마일스톤

| 단계 | 내용 | 완료 조건 |
|---|---|---|
| 1 | THD-01 → S1 → Slave → Edge → MES 한 줄 | `IF_SENSOR_RAW`에 THD-01 행 ≥ 3, TAG_ADDR `SLAVE.D0102` |
| 2 | RS-485 장비 17개, Master, 메모리 맵 검증 | 17개 설비 적재, AC-13 통과 |
| 3 | SAN, PKG(OPC-UA), SCALE, FILL, STUFF | 22개 설비 적재 |
| 4 | 필터·STALE·우선큐·재전송·분배·알람 | AC-02, 05~11 통과 |
| 5 | 대시보드 UI-01~10, `/kiosk`, WS | `npm run build`, vitest, playwright 스모크 |
| 6 | 고장 11종, 시나리오 4종, AC 전체 | `make test` 통과, TEST_REPORT.md |

## 5. 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| RTU over TCP 타이밍·반이중 재현 | 버스 폴링이 병렬로 새서 실제와 다른 결과 | 버스당 `asyncio.Lock`, baud 지연 주입, 프로토콜 직접 구현(D-002) |
| asyncua 기동 지연(1~3 s) | 테스트 불안정 | 조건 polling 대기, 서버 준비 이벤트 |
| 장시간 시나리오(5~10분) | 테스트 10분 제한 초과 | 테스트는 설정 오버라이드로 지속시간 단축(D-004) |
| WS 메시지 폭주 | 브라우저 지연 | 장비별 200 ms 합치기(초당 5건) |
| 단일 프로세스 내 이벤트 루프 부하 | 지연 증가 | 블록 단위 읽기, SQLite 배치 트랜잭션, WAL |
