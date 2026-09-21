# TEST_REPORT — v0.1 (2026-09-21)

환경: macOS 26 (arm64), Python 3.12.13 (uv), Node 24, pymodbus 3.15, asyncua 2.0.1, React 19, Vite 8

## 1. 요약

| 구분 | 결과 |
|---|---|
| pytest 전체 (unit 35 · integration 19 · acceptance 14 · safety 3) | **71 passed**, 0 failed, 0 xfail (9분 21초) |
| 수용 기준 AC-01~14 | **14/14 PASS** |
| 백엔드 커버리지 (`pytest-cov`) | **92 %** (2,882문 중 231 미실행) |
| ruff check / ruff format | 통과 |
| mypy --strict (plc · edge · mes) | 0 errors |
| vitest (대시보드) | **12 passed** |
| Playwright E2E 스모크 | **2 passed** |
| oxlint (대시보드) | 오류 0, 경고 5 (아래 4장) |

## 2. 수용 기준

긴 지속시간은 설정 오버라이드로 줄여 판정 논리만 같게 검증했다(D-004). "테스트 값" 열이 실제로 쓴 값이다.

| AC | 시나리오 | 결과 | 측정/판정 | 테스트 값 | 테스트 파일 |
|---|---|---|---|---|---|
| AC-01 | 기동 후 22개 정상, 성공률 ≥ 99 %, 22개 설비 적재 | PASS | 22/22 OK, 성공률 ≥ 0.99, `IF_SENSOR_RAW` 설비 22종 | 기동 후 30 s 안에 전부 OK + 10 s 표본 | tests/acceptance/test_ac01.py |
| AC-02 | Master D0102 ÷ 100 = 염도 = SLT_SALINITY_LOG | PASS | 세 값 일치, TAG_ADDR `MASTER.D0102` (D-010) | SAL-01 값 고정 후 비교 | test_ac02.py |
| AC-03 | bus_cut(M2) → M2 장비만 DOWN | PASS | TC-01~04·MD-01 DOWN ≤ 30 s, 나머지 17개 OK, M2 링크 DOWN, 해제 후 복구 | 주기 1 s | test_ac03.py |
| AC-04 | plc_down(SLAVE) | PASS | THD-01~06 STALE, D0902 정지 감지, Slave 노드 DOWN, THD-07 OK, 해제 후 복구 | — | test_ac04.py |
| AC-05 | 소독수 8.5 ppm 지속 → 알람 | PASS | hold 경과 전 알람 없음, 이후 알람 발생, `ALARM_YN=Y` ≥ 2행 | hold 60 s → **5 s** | test_ac05.py |
| AC-06 | TC-01 7 ℃ 지속 → AGE_ENV_ALARM | PASS | hold 전 0행, 이후 1행(온도 7.0, CCP_STD_ID 연결) | hold 300 s → **5 s** | test_ac06.py |
| AC-07 | 금속 NG → 2 s 이내 알람 | PASS | API 주입부터 `TWIN_ALARM` 발생까지 ≤ 2.0 s, QUA_METAL_LOG NG 행 | Edge PLC 읽기 500 ms (D-011) | test_ac07.py |
| AC-08 | 포장기 정지→가동 → EQP_RUN_LOG | PASS | 비가동 구간 1행(START < END, STOP_MINUTES > 0), 마지막 구간 가동 | 정지 4 s | test_ac08.py |
| AC-09 | MES 장애 → 버퍼 → 복구 | PASS | 버퍼 누적 → 0, msg_id 1..seq 전부 도착(누락 0), 중복 0, `RESEND_YN=Y` > 0 | 장애 10분 → **8 s** | test_ac09.py |
| AC-10 | 버퍼 쌓인 채 Edge 재시작 | PASS | 버퍼 유지, msg_id 연속, 복구 후 누락·중복 0 | — | test_ac10.py |
| AC-11 | 습도 150 % → FILTERED | PASS | 필터 카운트 ≥ 2, 원장·AGE_ENV_LOG에 100 % 초과 값 0 | — | test_ac11.py |
| AC-12 | PLC Write → 거부 | PASS | pymodbus FC06·FC16·FC05 모두 예외 코드 01, 메모리 불변, 거부 로그 3건 | pymodbus 클라이언트 | test_ac12.py |
| AC-13 | 블록 겹침 → 기동 거부 | PASS | 종료 코드 2, `D0205(TC-02)가 D0200~D0209(TC-01)와 겹침` | 서브프로세스 실행 | test_ac13.py |
| AC-14 | 같은 시드 → 같은 시퀀스 | PASS | 600틱 × 22장비 레지스터 시퀀스 동일, 다른 시드는 다름 | — | test_ac14.py |

## 3. 그 밖의 검증

| 항목 | 테스트 |
|---|---|
| 1단계 완료 조건: THD-01 → S1 → Slave → Edge → `IF_SENSOR_RAW`(`SLAVE.D0102`, RS-485, AGE_ENV_LOG) | integration/test_pipeline.py::test_stage1 |
| 분배 테이블 7종 모두 적재 | test_all_target_tables_receive_rows |
| DELAY 판정(D-008), CRC 오류 → ERROR와 원시 프레임 `CRC` | test_delay_state_d008, test_crc_error_state |
| OPC-UA 서버 정지 → DOWN → 복구 | test_opcua_down_and_recover |
| Master–Slave 연동 끊김 시 Slave 장비는 계속 수집 | test_master_slave_link_down_keeps_slave_devices |
| 통신 알람 발생·해제 | test_comm_alarm_raised_and_cleared |
| WebSocket 스냅샷과 value·summary·topology·edge_buffer 스트림 | test_websocket_snapshot_and_stream |
| 고장 API 검증 오류(400), 시나리오 실행 | test_scenario_and_fault_api_validation |
| 안전: 코드 전체에 Modbus 쓰기 호출 0건, OPC-UA 쓰기는 필드 시뮬레이터 자기 노드만 | safety/test_no_device_writes.py |
| 염도 통 전환이 필터에 걸리지 않음 (D-014 회귀) | unit/test_components.py::test_brine_tank_switch_not_filtered |
| E2E: 개요 22/22·WS 연결, 버스 단선 → 토폴로지 표시 (D-015 회귀) | dashboard/e2e/smoke.spec.ts |

## 4. 알려진 사항

- **개발 중 찾아 고친 결함**
  - D-014: 염도 급변 필터가 절임통 전환 값을 버림. 대시보드 점검 중 발견
  - D-015: 토폴로지가 고장 목록을 직접 읽어 관측보다 먼저 DOWN으로 표시. E2E에서 발견
  - AC-09 타이밍: 부하가 클 때 버퍼 누적 조건만 기다려 링크 상태 판정이 앞서는 경우가 있었음. 두 조건을 함께 기다리도록 수정
  - 종료 순서: WebSocket 허브가 닫힌 DB를 조회함. 주기 작업을 먼저 멈추도록 수정
- **oxlint 경고 5건**: 폴링 훅의 effect 안 setState, PLC 메모리 변화 감지, 렌더 중 `Date.now`, 컴포넌트 파일의 비컴포넌트 export. 동작 오류가 아닌 권고 수준이라 v0.1에서는 남겨 둔다.
- **커버리지가 낮은 곳**
  - `plc/link.py` 72 %: 실장비용 `SerialPortLink`는 하드웨어가 없어 실행하지 않음
  - `supervisor.py` 78 %: CLI 진입부
- **실시간 조건**: 원래 지속시간(1·5·10분) 그대로의 시험은 자동화하지 않았다. `make demo` 또는 대시보드의 시나리오 프리셋으로 실시간 확인할 수 있다.

## 5. 재현

```bash
make test   # lint + pytest(coverage) + vitest
make e2e    # Playwright
```
