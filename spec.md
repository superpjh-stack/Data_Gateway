# 기능 명세 — 임진강김치 PLC 데이터수집 디지털 트윈

> 관련 문서: `intro.md`(소개), `problem.md`(문제·목표·범위·확정 필요 사항)
> 근거: 임진강김치 SF-AD1·AD2, SF-TD2·TD4·TD5 (로뎀솔루션, 2026-08)
> 버전: v0.2 (2026-09-21, 분석·설계 산출물 기준으로 재작성)

**표기 규칙**
- `[설계]`: 설계 산출물에 명시된 값이며 그대로 따른다.
- `[가정]`: 설계 산출물에서 미확정인 값이다. 트윈이 임시로 정했고, 현장 실사 후 바꾼다(`problem.md` 8장 Q1~Q10).

---

## 1. 시스템 구성

설계서의 수집 경로(TD4 MES-TD4-065)를 계층별로 재현한다.

```
설비·센서 → PLC(RS-485/Ethernet/OPC-UA) → Edge Collector(프로토콜 표준화·버퍼링) → 수집 API → IF_SENSOR_RAW 적재 → 공정별 실적 테이블 분배
```

```
┌─────────────────────────── ① Field Simulator ───────────────────────────┐
│ 염도 SAL×2 · 온습도 THD×10 · 온도조절기 TC×4 · 금속검출 MD×1            │
│ 소독수 SAN×1 · 자동포장기 PKG×1 · 저울 SCALE×1 · 충진 FILL×1 · 속넣기 STUFF×1 │
│ 공정 모델로 값 생성 + 프로토콜 서버 + 고장 주입                          │
└──┬──────────────RS-485(Modbus RTU)──────────────┬──Ethernet──┬─OPC-UA─┬─RS-232─┬─Modbus TCP─┘
   │                                              │            │        │        │
┌──▼─────────────── ② PLC Twin ────────────────┐  │            │        │        │
│ PLC Master (XBC-DN32H)   PLC Slave (XBC-DN32H)│◀─┘ SAN-01     │        │        │
│  RS-485 버스 M1, M2       RS-485 버스 S1      │               │        │        │
│  D영역 메모리              D영역 메모리       │               │        │        │
│  Modbus TCP 서버(FEnet)    Modbus TCP 서버    │               │        │        │
└──────────┬────────────────────┬──────────────┘               │        │        │
           │ Ethernet            │                              │        │        │
┌──────────▼────────────────────▼──── ③ Edge Collector Twin ────▼────────▼────────▼──┐
│ 드라이버(modbus_tcp / opcua / serial_ascii) → 노이즈 필터 → 표준 메시지(IF_SENSOR_RAW) │
│ → 로컬 버퍼(SQLite) → 전송기(HTTP, 재전송 시 RESEND_YN=Y)                             │
└──────────────────────────────────────┬─────────────────────────────────────────────┘
                                       │ HTTP (MQTT 선택)
┌──────────────────────────────────────▼──── ④ MES Stub ─────────────────────────────┐
│ 수집 API → IF_SENSOR_RAW → 공정별 테이블 분배 → 기준 이탈 알람                         │
└──────────────────────────────────────┬─────────────────────────────────────────────┘
                                       │ REST + WebSocket
                              ┌────────▼────────┐
                              │ ⑤ Dashboard     │
                              └─────────────────┘
```

| 계층 | 실제 장비 | 트윈이 재현하는 것 |
|---|---|---|
| ① Field | 센서 17식, 금속검출기, 자동포장기, 기존 설비 | 측정값 생성, 통신 프로토콜, 고장 |
| ② PLC | LS산전 XBC-DN32H Master 1식·Slave 1식 `[설계]` | RS-485 폴링, D영역 기록, 상위 통신 제공. **읽기만 하고 제어 로직은 없다** `[설계]` |
| ③ Edge | Mini PC T1 X300 `[설계]` | 프로토콜 표준화, 노이즈 필터, 로컬 버퍼링, 재전송 `[설계]` |
| ④ MES | AWS MES 수집 API | `IF_SENSOR_RAW` 적재·분배·알람. 수집 관련 테이블만 구현 |
| ⑤ Dashboard | 관리용 PC, 현황판(65인치) | 수집 현황 시각화, 고장 주입 |

### 1.1 기술 스택

| 영역 | 선택 |
|---|---|
| 언어 | Python 3.12 (시뮬레이터·PLC·Edge·MES), TypeScript (대시보드) |
| 비동기 | `asyncio` |
| Modbus RTU/TCP | `pymodbus` 3.x |
| OPC-UA | `asyncua` |
| 시리얼 | `pyserial-asyncio`. 가상 포트는 `socat` pty 쌍 또는 `socket://` URL |
| MES API | FastAPI + WebSocket |
| 저장 | SQLite (Edge 버퍼, MES 스텁). 테이블·컬럼명은 TD5와 같게 해서 PostgreSQL로 옮기기 쉽게 한다 |
| 대시보드 | React + Vite, ECharts |
| 설정 | YAML: `config/equipment.yaml`, `config/plc_map.yaml`, `config/ccp_std.yaml`, `config/scenarios.yaml` |

### 1.2 실행 모드

| 모드 | 설명 |
|---|---|
| `sim` | 모든 장비가 가상이다 (기본값) |
| `hybrid` | 반입된 장비만 실제 포트·IP로 연결하고, 나머지는 가상으로 둔다 |
| `live` | 실제 PLC·Edge에 붙고, 트윈은 대시보드와 비교 검증에만 쓴다 |

설비마다 `endpoint`만 바꾸면 가상과 실물이 전환되어야 한다.

---

## 2. 수집 대상 장비

### 2.1 장비 목록

| 설비 코드 | 장비 | 공정 | 수량 근거 | 모델 | 통신 | 연결 위치 | 수집 주기 |
|---|---|---|---|---|---|---|---|
| `SAL-01` | 염도센서 #1 (절임통 1~4) | 세척/절임 | 2식 `[설계]` | 미기재 | RS-485 Modbus RTU `[가정]` | Master M1, slave 1 | 5 s `[가정]` |
| `SAL-02` | 염도센서 #2 (절임통 5~8) | 세척/절임 | 〃 | 미기재 | 〃 | Master M1, slave 2 | 5 s |
| `THD-01`~`03` | 온습도센서 (입고) | 입고/보관 | 10식 `[설계]` | THD-WD1-T `[설계]` | RS-485 `[설계]`, Modbus RTU `[가정]` | Slave S1, slave 1~3 `[가정]` | 10 s |
| `THD-04`~`06` | 온습도센서 (전처리) | 절단/전처리 | 〃 | 〃 | 〃 | Slave S1, slave 4~6 | 10 s |
| `THD-07` | 온습도센서 (세척) | 세척/절임 | 〃 | 〃 | 〃 | Master M1, slave 7 | 10 s |
| `THD-08` | 온습도센서 (절임) | 세척/절임 | 〃 | 〃 | 〃 | Master M1, slave 8 | 10 s |
| `THD-09` | 온습도센서 (혼합) | 혼합(버무림) | 〃 | 〃 | 〃 | Master M1, slave 9 | 10 s |
| `THD-10` | 온습도센서 (포장출고) | 포장/출고 | 〃 | 〃 | 〃 | Master M1, slave 10 | 10 s |
| `TC-01` | 온도조절기 (숙성 냉장고) | 냉장·숙성 | 4식 `[설계]` | FOX-2003CC `[설계]` | RS-485 `[설계]`, Modbus RTU `[가정]` | Master M2, slave 1 | 10 s |
| `TC-02` | 온도조절기 (원품 냉장고) | 입고/보관 | 〃 | 〃 | 〃 | Master M2, slave 2 | 10 s |
| `TC-03` | 온도조절기 (탈수 냉장고) | 탈수 | 〃 | 〃 | 〃 | Master M2, slave 3 | 10 s |
| `TC-04` | 온도조절기 (냉동고) `[가정]` | 입고/보관 | 〃 | 〃 | 〃 | Master M2, slave 4 | 10 s |
| `MD-01` | 금속검출기 | 금속검출 | 대수 미확인, 1대 `[가정]` | 미기재 | RS-485 `[설계]`, Modbus RTU `[가정]` | Master M2, slave 11 | 1 s `[가정]` |
| `SAN-01` | 소독수 공급장치 + Interface Module | 세척/절임 | 1식 `[설계]` | XBL-EMTA600 `[설계]` | Ethernet(TCP/IP) `[설계]`, Modbus TCP `[가정]` | Master Ethernet | 5 s |
| `PKG-01` | 아이스박스자동포장기 | 포장/출고 | 1대 `[설계]` | KF 100 `[설계]` | Ethernet · OPC-UA `[설계]` | Edge 직접 | 구독(변화 시) + 10 s |
| `SCALE-01` | 중량 저울 | 포장/출고 | 미확인, 1대 `[가정]` | 미기재 | RS-232 ASCII `[가정]` | Edge 직접 `[설계]` | 요청/응답 1 s |
| `FILL-01` | 충진기 | 혼합(버무림) | 1대(기존) `[설계]` | 미기재 | Modbus TCP `[가정]` | Edge 직접 `[설계]` | 5 s |
| `STUFF-01` | 속넣기기계 | 혼합(버무림) | 1대(기존) `[설계]` | 미기재 | Modbus TCP `[가정]` | Edge 직접 `[설계]` | 5 s |

합계는 22개다(설계 확정 19 + 미확정 가정 3). 설비 코드는 `BAS_EQUIP.EQUIP_CODE`와 같게 쓰고, PLC 태그와 1:1로 매핑한다 `[설계]`.

### 2.2 RS-485 버스

| 버스 | 소속 | 포트 (sim) | 통신 설정 `[가정]` | 연결 장비 |
|---|---|---|---|---|
| M1 | PLC Master | `/dev/ttyV0` | 9600, 8N1 | SAL-01·02, THD-07~10 |
| M2 | PLC Master | `/dev/ttyV2` | 9600, 8N1 | TC-01~04, MD-01 |
| S1 | PLC Slave | `/dev/ttyV4` | 9600, 8N1 | THD-01~06 |

한 버스 안에서는 **순차 폴링**만 한다. 한 번에 요청 하나이며, 실제 RS-485 반이중 동작과 같다.

---

## 3. 장비별 프로토콜·레지스터 `[가정]`

> 센서 모델은 `[설계]`지만 레지스터 주소는 제조사 매뉴얼로 확정해야 한다. 아래는 트윈용 가정값이다.

### 3.1 염도센서 SAL-01·02 (Modbus RTU)

| 레지스터 | 항목 | 형식 | 스케일 | 단위 |
|---|---|---|---|---|
| IR 30001 | 염도 | uint16 | ÷100 | % |
| IR 30002 | 염수 온도 | int16 | ÷10 | ℃ |
| IR 30003 | 측정 중 절임통 번호 | uint16 | ×1 | 1~8 |
| IR 30004 | 센서 상태 (0 정상, 1 교정필요, 2 오류) | uint16 | — | — |

센서 1식이 절임통 4기를 담당하고 측정 대상을 2분마다 바꾼다는 가정이다(Q3). 측정값은 `IR 30003`의 절임통에 해당하는 `SLT_TANK_OPR`로 분배한다.

### 3.2 온습도센서 THD-01~10 (Modbus RTU)

| 레지스터 | 항목 | 형식 | 스케일 | 단위 |
|---|---|---|---|---|
| IR 30001 | 온도 | int16 | ÷10 | ℃ |
| IR 30002 | 습도 | uint16 | ÷10 | %RH |

### 3.3 온도조절기 TC-01~04 (Modbus RTU)

| 레지스터 | 항목 | 형식 | 스케일 | 단위 |
|---|---|---|---|---|
| IR 30001 | 현재 온도(PV) | int16 | ÷10 | ℃ |
| HR 40001 | 설정 온도(SV) | int16 | ÷10 | ℃ |
| IR 30002 | 출력 상태 (bit0 냉동기, bit1 제상, bit2 경보) | uint16 | — | — |

설정 온도는 **읽기만** 한다. 설정 변경은 현장 조절기에서 사람이 하고, 트윈은 그 변화를 수집한다(TD2 검증방안: "설정값 변경 시 수집값 반영 확인").

### 3.4 금속검출기 MD-01 (Modbus RTU)

| 레지스터 | 항목 | 형식 |
|---|---|---|
| IR 30001 | 최근 판정 (0 OK, 1 NG) | uint16 |
| IR 30002-30003 | 누적 검사 수량 | uint32 |
| IR 30004-30005 | 누적 불합격 수량 | uint32 |
| IR 30006 | 가동 상태 (0 정지, 1 가동) | uint16 |

### 3.5 소독수 공급장치 SAN-01 (Modbus TCP, XBL-EMTA600 경유)

| 레지스터 | 항목 | 형식 | 스케일 | 단위 |
|---|---|---|---|---|
| HR 40001 | 소독수 농도 | uint16 | ÷100 | ppm |
| HR 40002 | 접촉 시간 | uint16 | ÷10 | 분 |
| HR 40003 | 유량 대비 투입비율 | uint16 | ÷100 | % |
| HR 40004 | 가동 상태 | uint16 | — | — |

XBL-EMTA600은 LS산전 Ethernet 모듈이다. 실제로는 XGT 전용 프로토콜(FEnet)일 수도 있다. 이 경우 드라이버만 교체한다.

### 3.6 아이스박스자동포장기 PKG-01 (OPC-UA)

| 노드 ID | 항목 | 형식 |
|---|---|---|
| `ns=2;s=KF100.PackCount` | 포장 완료 누적 수량 (박스) | UInt32 |
| `ns=2;s=KF100.Running` | 가동/정지 | Boolean |
| `ns=2;s=KF100.RunMinutes` | 누적 가동시간 (분) | Double |
| `ns=2;s=KF100.AlarmCode` | 설비 알람 코드 (0 없음) | UInt16 |

엔드포인트(sim)는 `opc.tcp://127.0.0.1:4840`이다. Edge는 구독(subscription)으로 값 변화를 받고, 10초마다 연결을 확인한다.

### 3.7 중량 저울 SCALE-01 (RS-232 ASCII)

Edge가 `Q\r\n`을 보내면 저울이 한 줄로 응답한다. 500 ms 안에 응답이 없으면 타임아웃이다.

```
ST,GS,+0010.250kg\r\n
```

필드는 안정(`ST`)/불안정(`US`)/과부하(`OL`), 총중량(`GS`)/순중량(`NT`), 중량 순이다. 안정 값만 채택하고, 형식이 틀린 줄은 `FRAME_ERROR`로 센다.

### 3.8 충진기 FILL-01 · 속넣기기계 STUFF-01 (Modbus TCP)

| 레지스터 | 항목 | 형식 | 스케일 |
|---|---|---|---|
| HR 40001 | 작업 속도 | uint16 | ×1 (개/분) |
| HR 40002 | 세팅 양 | uint16 | ÷10 (g) |
| HR 40003 | 가동 상태 | uint16 | — |
| HR 40004-40005 | 누적 처리 수량 | uint32 | ×1 |

---

## 4. PLC 트윈

### 4.1 동작

| ID | 요구사항 |
|---|---|
| PLC-01 | 버스(M1, M2, S1)마다 스캔 태스크 1개가 장비를 순차 폴링한다 (Modbus RTU master) |
| PLC-02 | 타임아웃 300 ms, 재시도 2회. 모두 실패하면 해당 장비의 통신 상태를 갱신한다 |
| PLC-03 | 읽은 원시값을 **스케일 변환 없이** 장비별 D영역 블록에 기록한다. 스케일 변환은 Edge가 한다 |
| PLC-04 | Master는 SAN-01을 Modbus TCP로 읽어 D영역에 기록한다 |
| PLC-05 | D영역을 Modbus TCP 서버로 공개해 Edge가 읽게 한다(Holding Register = D주소). 포트는 Master 5020, Slave 5021 |
| PLC-06 | Master–Slave 연동: Slave의 하트비트를 Master `D0902`에 미러링한다. 끊기면 Master 진단 영역에 표시한다 |
| PLC-07 | **쓰기 명령을 받지 않는다.** Edge·외부에서 온 Write 요청은 거부하고 로그로 남긴다 `[설계]` |
| PLC-08 | 스캔 주기와 스캔 시간(버스 1회 순회 시간)을 진단 영역에 기록한다 |

### 4.2 D영역 메모리 맵 `[가정]`

장비마다 10워드 블록을 쓴다.

| 오프셋 | 내용 |
|---|---|
| +0 | 통신 상태 (0 정상, 1 지연, 2 끊김, 3 오류) |
| +1 | 연속 실패 횟수 |
| +2 ~ +7 | 장비 레지스터 값 (3장 순서대로, 32비트 값은 2워드) |
| +8 | 갱신 카운터 (성공 시 +1, 65535 다음 0) |
| +9 | 예약 |

**PLC Master**

| 시작 주소 | 장비 | 시작 주소 | 장비 |
|---|---|---|---|
| D0100 | SAL-01 | D0200 | TC-01 |
| D0110 | SAL-02 | D0210 | TC-02 |
| D0120 | THD-07 | D0220 | TC-03 |
| D0130 | THD-08 | D0230 | TC-04 |
| D0140 | THD-09 | D0300 | MD-01 |
| D0150 | THD-10 | D0400 | SAN-01 |

**PLC Slave**

| 시작 주소 | 장비 |
|---|---|
| D0100 ~ D0150 | THD-01 ~ THD-06 (10워드 간격) |

**진단 영역 (Master·Slave 공통)**

| 주소 | 내용 |
|---|---|
| D0900 | PLC 하트비트 (1초마다 +1) |
| D0901 | 버스별 상태 비트 (bit0 M1/S1, bit1 M2, bit2 Ethernet 장비) |
| D0902 | (Master만) Slave 하트비트 미러 |
| D0903 | 마지막 버스 스캔 시간 (ms) |
| D0904 | 정상 장비 수 |

기동할 때 메모리 맵을 검증한다. 블록이 겹치거나, 한 태그가 두 설비에 걸리거나, `BAS_EQUIP` 설비 코드와 1:1이 아니면 기동을 거부하고 해당 주소를 오류로 보여준다.

---

## 5. Edge Collector 트윈

### 5.1 동작 `[설계]` 기반

| ID | 요구사항 |
|---|---|
| EDG-01 | PLC Master·Slave D영역을 Modbus TCP로 블록 단위로 읽는다 (1 s 주기) |
| EDG-02 | PKG-01은 OPC-UA, SCALE-01은 RS-232, FILL-01·STUFF-01은 Modbus TCP로 직접 수집한다 |
| EDG-03 | 원시값을 스케일 변환하고 단위를 붙여 **표준 메시지**(5.2)로 만든다 |
| EDG-04 | 노이즈 필터: 물리 범위를 벗어난 값(예: 습도 > 100%), 직전 값에서 급변한 값(설정 가능)은 버리고 `FILTERED`로 센다 `[설계]` |
| EDG-05 | 갱신 카운터(+8)가 바뀌지 않았으면 새 값으로 보지 않는다. 카운터가 주기 × 3 동안 그대로면 `STALE`로 본다 |
| EDG-06 | 변화 발생 시 또는 설비별 최소 주기마다 메시지를 만든다 (deadband 설정 가능) |
| EDG-07 | 메시지를 먼저 로컬 버퍼(SQLite)에 쓰고 전송한다. MES가 수신 확인(ack)하면 지운다 |
| EDG-08 | MES 연결이 끊기면 계속 버퍼에 쌓는다. 복구되면 오래된 순서로 재전송하고, 재전송분은 `RESEND_YN=Y`로 보낸다 `[설계]` |
| EDG-09 | 버퍼 보존 기간은 72시간 `[가정]`(Q2). 넘은 건은 삭제하고 삭제 건수를 기록한다 |
| EDG-10 | 금속검출 NG는 버퍼 순서와 상관없이 즉시 전송한다 (우선 큐) |
| EDG-11 | 설비 제어 명령을 만들지 않는다 `[설계]` |

### 5.2 표준 메시지 (= `IF_SENSOR_RAW` 한 행)

```json
{
  "equip_code": "SAN-01",
  "tag_addr": "MASTER.D0402",
  "data_type": "농도(ppm)",
  "raw_value": "10.35",
  "unit_cd": "PPM",
  "comm_type": "Ethernet(TCP/IP)",
  "target_table": "WSH_SANITIZER_LOG",
  "resend_yn": "N",
  "collect_dt": "2026-09-21T13:00:05+09:00",
  "msg_id": "edge01-000184523"
}
```

| 필드 | `IF_SENSOR_RAW` 컬럼 | 비고 |
|---|---|---|
| equip_code | EQUIP_ID (MES에서 `BAS_EQUIP`로 변환) | |
| tag_addr | TAG_ADDR | `MASTER.Dxxxx`, `SLAVE.Dxxxx`, `OPCUA.<node>`, `SERIAL.SCALE-01` 등 |
| data_type | DATA_TYPE | 온도/습도/농도(ppm)/염도/검출결과/수량/가동상태 `[설계]` |
| raw_value | RAW_VALUE | 문자열 |
| unit_cd | UNIT_CD | |
| comm_type | COMM_TYPE | RS-485 / Ethernet(TCP/IP) / OPC-UA / RS-232 `[가정]` |
| target_table | TARGET_TABLE | 6.2 분배 규칙 |
| resend_yn | RESEND_YN | |
| collect_dt | COLLECT_DT | Edge 수집 시각. 전송 시각이 아니다 |
| msg_id | (추가) | 중복 적재 방지용. MES는 같은 msg_id를 한 번만 적재한다 |

전송은 `POST /api/if/sensor-raw`로 하고, 한 번에 최대 500건을 묶어 보낸다. MQTT(`jjk/edge01/raw`)는 옵션이다.

---

## 6. MES 스텁

### 6.1 구현 테이블 (TD5 중 수집 관련 13개)

| 테이블 | 용도 |
|---|---|
| `BAS_EQUIP` | 설비탱크마스터. EQUIP_CODE, PLC_TAG, COMM_TYPE, COLLECT_ITEM |
| `BAS_CCP_STD` | 공정CCP기준. 알람 기준값 (`config/ccp_std.yaml`로 초기화) |
| `IF_SENSOR_RAW` | 설비센서수집원장 |
| `SLT_TANK_OPR` | 절임통운영실적. 절임통 8기의 더미 운영 데이터 |
| `SLT_SALINITY_LOG` | 염도측정이력 |
| `WSH_SANITIZER_LOG` | 소독수농도이력 |
| `AGE_ENV_LOG` / `AGE_ENV_ALARM` | 냉장고온습도이력 / 온습도이탈알람 |
| `QUA_METAL_LOG` | 금속검출이력 |
| `PKG_TAPING_LOG` | 자동테이핑기실적 |
| `PKG_WEIGHT_INSP` | 중량검사실적 |
| `MIX_FILLER_LOG` | 속넣기충진기수집데이터 |
| `EQP_RUN_LOG` | 설비가동상태이력 |

`WORK_ORDER_ID`, `LOT_NO`, `ITEM_ID`처럼 업무 데이터가 필요한 FK는 스텁이 만든 더미 작업지시 1건에 연결한다.

### 6.2 분배 규칙

| 원천 | TARGET_TABLE | 비고 |
|---|---|---|
| SAL-01·02 | `SLT_SALINITY_LOG` | 측정 중 절임통 번호로 `TANK_OPR_ID`를 찾는다. COLLECT_TYPE=PLC 자동 |
| THD-01~10 | `AGE_ENV_LOG` | TEMP_VALUE, HUMID_VALUE. COMM_TYPE=`RS-485 → PLC → 수집서버` |
| TC-01~04 | `AGE_ENV_LOG` | TEMP_VALUE, SET_TEMP |
| SAN-01 | `WSH_SANITIZER_LOG` | PPM_VALUE, CONTACT_TIME, DOSING_RATE |
| MD-01 | `QUA_METAL_LOG` | 검사 수량이 늘어날 때마다 1행. DETECT_RESULT, INSPECT_QTY, NG_QTY |
| PKG-01 | `PKG_TAPING_LOG`, `EQP_RUN_LOG` | 가동 상태가 바뀌면 `EQP_RUN_LOG` 구간을 열고 닫는다 |
| SCALE-01 | `PKG_WEIGHT_INSP` | 기준 중량 대비 판정 (합격/미달/초과) |
| FILL-01·STUFF-01 | `MIX_FILLER_LOG`, `EQP_RUN_LOG` | WORK_SPEED, SET_VOLUME |

### 6.3 기준 이탈 알람

| 항목 | 기준 | 근거 | 조건 |
|---|---|---|---|
| 소독수 농도 | 10 ppm | `[설계]` AD1·TD2 | 10 ppm 미만 1분 지속 `[가정]` |
| 절임 염도 | 절임 조건 9 / 12 / 13 % | `[설계]` AD1 | 목표 ±1.0 %p 이탈 `[가정]` |
| 냉장 온도 | `BAS_CCP_STD` | 값 미기재 | -1 ~ 5 ℃ 벗어남 5분 지속 `[가정]` |
| 냉동 온도 | `BAS_CCP_STD` | 값 미기재 | -18 ℃ 초과 10분 지속 `[가정]` |
| 금속검출 | NG | `[설계]` "기준 초과 시 즉시 알람" | NG 수신 즉시 |
| 포장 중량 | 기준 중량 ±2 % `[가정]` | | 미달·초과 판정 시 |
| 통신 | — | | 장비 끊김, PLC 하트비트 정지, Edge–MES 끊김 |

기준값은 모두 `config/ccp_std.yaml` → `BAS_CCP_STD`에서 읽는다. 코드에 하드코딩하지 않는다. 알람이 나면 해당 테이블의 `ALARM_YN=Y`로 기록하고, 온습도는 `AGE_ENV_ALARM`에도 남긴다.

---

## 7. 공정 모델 (Field Simulator)

| 장비 | 값 생성 규칙 |
|---|---|
| SAL | 절임 조건(9·12·13%)에서 시작해 경과시간에 따라 서서히 떨어진다(배추 흡수). 절임 24h/48h `[설계]`가 끝나면 새 배치로 초기화한다 |
| THD | 공정 구역별 기본값(예: 입고 8 ℃/85 %, 세척 15 ℃/90 %) + 일중 변동 + 노이즈 |
| TC | SV 근처에서 냉동기 ON/OFF 히스테리시스로 PV가 오르내린다. 문 열림 이벤트 때 상승했다가 회복한다 |
| SAN | 10.5 ppm 근처에서 변동하고, 가끔 투입비율 저하로 농도가 떨어진다 |
| MD | 가동 중 초당 약 0.3개 검사, NG 확률 0.2 % |
| PKG | 가동 중 분당 약 1박스 (1일 약 1천 박스 `[설계]` 기준), 가끔 정지 |
| SCALE | 기준 중량(예: 10 kg) ± 정규분포 |
| FILL/STUFF | 세팅값 고정, 속도는 작업자 교대 시 바뀐다 |

난수 시드를 설정할 수 있어 같은 시나리오를 재현할 수 있다.

---

## 8. 고장·장애 주입

| 유형 | 대상 | 효과 |
|---|---|---|
| `sensor_disconnect` | 장비 1대 | 응답 없음 |
| `sensor_delay(ms)` | 장비 1대 | 응답 지연 |
| `crc_error(비율)` | RTU 장비 | 응답 CRC 손상 |
| `value_spike(항목, 값)` | 장비 1대 | 값 강제 (알람 시험용) |
| `value_freeze` | 장비 1대 | 값 고정 (갱신 카운터는 증가) |
| `bus_cut` | M1 / M2 / S1 | 버스 전체 응답 없음 (단선) |
| `plc_down` | Master / Slave | PLC Modbus TCP 서버 정지, 하트비트 정지 |
| `master_slave_link_down` | — | Master–Slave 연동 끊김 |
| `opcua_down` | PKG-01 | OPC-UA 서버 정지 |
| `mes_link_down` | Edge–MES | 전송 실패 → 버퍼 누적 |
| `edge_restart` | Edge | 프로세스 재시작 (버퍼가 디스크에 남는지 확인) |

주입에는 지속 시간을 줄 수 있다. `config/scenarios.yaml`에 프리셋을 둔다.
- "HACCP 소독수 이탈": SAN-01 `value_spike(ppm, 8.5)` 3분
- "냉장고 문 열림": TC-01 `value_spike(pv, 7.0)` 6분
- "Master 버스 M2 단선": `bus_cut(M2)` 2분
- "MES 회선 10분 장애": `mes_link_down` 10분

---

## 9. 대시보드

| ID | 화면 | 요구사항 |
|---|---|---|
| UI-01 | 상단 요약 | 전체 22개 중 정상 수, 전체 수집 성공률, Edge 버퍼 대기 건수, 활성 알람 수, MES 연결 상태 |
| UI-02 | 수집 토폴로지 | 센서 → 버스(M1/M2/S1) → PLC Master/Slave → Edge → MES 트리. 노드·링크별 색: 초록 정상, 노랑 지연, 빨강 끊김, 보라 오류, 회색 비활성. 장애 구간이 한눈에 보여야 한다 |
| UI-03 | 공정 현황 | 공정 흐름도(입고/보관 → … → 냉장·숙성) 위에 장비 카드와 대표값을 놓는다. 절임통 8기는 별도 그리드로 염도·경과시간을 보여준다 |
| UI-04 | 수집 현황 표 | 설비 코드, 장비, 통신, 연결 위치, 주기, 성공률(1분/1시간), 평균 응답시간, 마지막 수신, 오류 유형별 건수, `[가정]` 여부 |
| UI-05 | 장비 상세 | 태그 목록, 실시간 값, 품질(GOOD/STALE/FILTERED), 최근 1시간 추이, 원시 프레임 로그(최근 50건, 16진) |
| UI-06 | PLC 메모리 | Master·Slave 탭. D0100~D0999 그리드에서 바뀐 셀을 강조하고, 마우스를 올리면 설비 코드·항목을 보여준다. 진단 영역 따로 표시 |
| UI-07 | Edge 버퍼 | 대기 건수 추이, 전송 성공·실패, 재전송 건수, 가장 오래된 대기 메시지 시각, 보존 기간 초과 삭제 건수 |
| UI-08 | 수집 원장 | `IF_SENSOR_RAW` 최근 행 조회(설비·기간·RESEND_YN 필터), 분배된 공정 테이블 행 수 |
| UI-09 | 알람 | 활성 알람(확인 처리), 이력(기간·공정·유형 필터), CCP 기준값 표시 |
| UI-10 | 시뮬레이션 제어 | 장비·버스·구간 선택 → 고장 유형·지속시간 → 적용/해제, 시나리오 프리셋 실행 |

실시간 갱신은 WebSocket 푸시로 한다. 끊기면 화면에 표시하고 자동 재연결한다. 현황판(65인치)용으로 UI-02·03을 전체화면 순환하는 모드를 둔다.

---

## 10. API

### 10.1 MES 스텁 REST

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/if/sensor-raw` | Edge 수집 메시지 적재 (배치, msg_id 중복 무시). 응답으로 적재된 msg_id 목록 |
| GET | `/api/equip` | `BAS_EQUIP` 목록 + 현재 수집 상태 |
| GET | `/api/equip/{code}` | 장비 상세 + 진단 지표 |
| GET | `/api/equip/{code}/frames?limit=50` | 최근 원시 프레임 |
| GET | `/api/raw?equip=&from=&to=&resend=` | `IF_SENSOR_RAW` 조회 |
| GET | `/api/tables/{table}?limit=` | 분배 테이블 조회 (6.1 목록만) |
| GET | `/api/plc/{master\|slave}/memory?start=D0100&count=900` | PLC D영역 스냅샷 |
| GET | `/api/edge/buffer` | 버퍼 상태 |
| GET | `/api/topology` | 수집 토폴로지와 노드·링크 상태 |
| GET | `/api/alarms?active=true` / POST `/api/alarms/{id}/ack` | 알람 |
| GET | `/api/summary` | 상단 요약 |
| POST | `/api/sim/faults` / DELETE `/api/sim/faults/{id}` | 고장 주입·해제 |
| GET | `/api/sim/scenarios` / POST `/api/sim/scenarios/{name}/run` | 시나리오 |

### 10.2 WebSocket `/ws`

```json
{"type":"value","equip":"SAL-01","item":"염도","value":12.4,"unit":"%","quality":"GOOD","tank":3,"ts":"..."}
{"type":"link","from":"BUS.M2","to":"PLC.MASTER","status":"DOWN","ts":"..."}
{"type":"equip_status","equip":"TC-01","status":"OK","ts":"..."}
{"type":"plc_mem","plc":"MASTER","changes":[{"addr":"D0402","value":1035}],"ts":"..."}
{"type":"edge_buffer","pending":1234,"resent":0,"oldest":"...","ts":"..."}
{"type":"alarm","id":"A-0031","state":"RAISED","equip":"SAN-01","message":"소독수 농도 8.5ppm (기준 10ppm)","ts":"..."}
{"type":"summary","total":22,"ok":21,"success_rate":0.996,"active_alarms":1,"mes_link":"UP"}
```

값 메시지는 장비별로 초당 최대 5건으로 묶어 보낸다.

---

## 11. 설정 파일 예시

`config/equipment.yaml`

```yaml
plcs:
  MASTER: { model: XBC-DN32H, modbus_tcp: "127.0.0.1:5020" }
  SLAVE:  { model: XBC-DN32H, modbus_tcp: "127.0.0.1:5021" }

buses:
  M1: { plc: MASTER, port: "/dev/ttyV0", baudrate: 9600, parity: N, timeout_ms: 300 }
  M2: { plc: MASTER, port: "/dev/ttyV2", baudrate: 9600, parity: N, timeout_ms: 300 }
  S1: { plc: SLAVE,  port: "/dev/ttyV4", baudrate: 9600, parity: N, timeout_ms: 300 }

equipment:
  - code: SAL-01
    name: 염도센서 1
    process: 세척/절임
    via: { bus: M1, slave: 1 }
    plc_block: MASTER.D0100
    poll_ms: 5000
    assumed: [protocol, registers, poll_ms, tank_mapping]
    items:
      - { name: 염도, reg: IR30001, type: uint16, scale: 0.01, unit: "%", data_type: 염도, target: SLT_SALINITY_LOG }
      - { name: 염수온도, reg: IR30002, type: int16, scale: 0.1, unit: "℃", data_type: 온도 }
      - { name: 측정절임통, reg: IR30003, type: uint16 }
    sim: { model: brine_sensor, tanks: [1, 2, 3, 4], switch_sec: 120 }

  - code: PKG-01
    name: 아이스박스자동포장기 KF 100
    process: 포장/출고
    via: { edge: opcua, endpoint: "opc.tcp://127.0.0.1:4840" }
    items:
      - { name: 포장완료수량, node: "ns=2;s=KF100.PackCount", unit: 박스, data_type: 수량, target: PKG_TAPING_LOG }
      - { name: 가동상태, node: "ns=2;s=KF100.Running", data_type: 가동상태, target: EQP_RUN_LOG }
    sim: { model: taping_machine, boxes_per_min: 1.0 }
```

`config/ccp_std.yaml`

```yaml
- { item: 소독수농도, equip: SAN-01, low: 10.0, unit: ppm, hold_sec: 60, basis: 설계 }
- { item: 냉장온도, equip: [TC-01, TC-02, TC-03], low: -1.0, high: 5.0, unit: "℃", hold_sec: 300, basis: 가정 }
- { item: 냉동온도, equip: TC-04, high: -18.0, unit: "℃", hold_sec: 600, basis: 가정 }
- { item: 절임염도, equip: [SAL-01, SAL-02], target_by_recipe: [9, 12, 13], band: 1.0, unit: "%", basis: 설계+가정 }
- { item: 금속검출, equip: MD-01, ng_immediate: true, basis: 설계 }
```

---

## 12. 비기능 요구사항

| 항목 | 기준 |
|---|---|
| 지연 | 센서 값 변화 → 대시보드 표시 2 s 이내 (정상 조건) |
| 무손실 | MES 장애 10분 후 복구 시 `IF_SENSOR_RAW` 누락 0건, 중복 0건 |
| 격리 | 한 버스·장비 오류가 다른 버스 수집에 영향 없음 |
| 확장 | 장비 추가는 YAML만으로, 새 프로토콜은 드라이버 클래스 1개로 |
| 교체 | `endpoint` 변경만으로 가상 ↔ 실물 전환 |
| 실행 | `make run` 한 번으로 ①~⑤ 전체 기동 (macOS 기준, `socat` 필요) |
| 로그 | 구조화 로그(JSON), 설비 코드·계층 포함 |
| 안전 | 코드베이스 어디에도 설비 쓰기(Write) 경로가 없어야 한다. 테스트로 확인한다 |

---

## 13. 디렉터리 구조

```
PLC Simulator/
├── intro.md  problem.md  spec.md
├── config/          equipment.yaml  plc_map.yaml  ccp_std.yaml  scenarios.yaml
├── field/           # ① 가상 장비
│   ├── models/      # brine_sensor, thd, fox_controller, metal_detector, sanitizer, taping_machine, scale, filler
│   └── servers/     # modbus_rtu, modbus_tcp, opcua, serial_ascii
├── plc/             # ② PLC 트윈 (bus_scanner, memory, modbus_server, diagnostics)
├── edge/            # ③ Edge 트윈 (drivers, normalizer, filter, buffer, sender)
├── mes/             # ④ MES 스텁 (FastAPI, schema.sql, distributor, alarms)
├── dashboard/       # ⑤ React
├── scripts/         # 가상 시리얼 포트 생성, 전체 기동
└── tests/
```

---

## 14. 수용 기준

| # | 시나리오 | 기대 결과 |
|---|---|---|
| AC-01 | 전체 기동 후 2분 | 22개 모두 정상, 수집 성공률 ≥ 99 %, `IF_SENSOR_RAW`에 22개 설비 행 존재 |
| AC-02 | Master D영역 대조 | `D0100` 값 ÷ 100 = SAL-01 염도 = `SLT_SALINITY_LOG.SALINITY_VALUE` 최신값 |
| AC-03 | `bus_cut(M2)` | TC-01~04, MD-01만 30 s 이내 끊김. M1·S1 장비와 SAN-01은 정상. 토폴로지에서 M2 링크 빨강 |
| AC-04 | `plc_down(SLAVE)` | THD-01~06 STALE, Master `D0902` 정지 감지, 토폴로지에서 Slave 노드 빨강 |
| AC-05 | SAN-01 농도 8.5 ppm 3분 | 1분 경과 시 알람, `WSH_SANITIZER_LOG.ALARM_YN=Y`, 1분 전에는 알람 없음 |
| AC-06 | TC-01 PV 7 ℃ 6분 | 5분 경과 시 알람, `AGE_ENV_ALARM` 1행 생성 |
| AC-07 | MD-01 NG 발생 | 2 s 이내 알람, `QUA_METAL_LOG.DETECT_RESULT='NG'`, NG_QTY 증가 |
| AC-08 | PKG-01 정지 → 가동 | `EQP_RUN_LOG` 비가동 구간 1행(START_DT, END_DT, STOP_MINUTES) 생성 |
| AC-09 | `mes_link_down` 10분 후 복구 | 버퍼 증가 → 복구 후 5분 이내 0, 누락·중복 0건, 복구분 `RESEND_YN=Y` |
| AC-10 | `edge_restart` (버퍼 쌓인 상태) | 재시작 후 버퍼 유지, 전송 재개 |
| AC-11 | 습도 150 % 값 주입 | `FILTERED`로 버려지고 `IF_SENSOR_RAW`에 적재되지 않음 |
| AC-12 | PLC에 Modbus Write 요청 | 거부되고 로그 기록, 메모리 변화 없음 |
| AC-13 | 메모리 블록 겹치게 설정 | 기동 거부, 겹친 주소 표시 |
| AC-14 | 같은 시드로 시나리오 2회 | 수집값 시퀀스 동일 |

---

## 15. 단계별 진행

| 단계 | 내용 | 결과물 |
|---|---|---|
| 1 | THD 1대 → 버스 S1 → PLC Slave → Edge → MES 스텁 | 엔드투엔드 1줄, `IF_SENSOR_RAW` 적재 |
| 2 | RS-485 장비 전체와 PLC Master/Slave, 메모리 맵 | 17개 수집 |
| 3 | SAN(Modbus TCP), PKG(OPC-UA), SCALE(RS-232), FILL·STUFF | 22개 수집 |
| 4 | Edge 필터·버퍼·재전송, MES 분배·알람 | AC-05~11 |
| 5 | 대시보드 UI-01~10 | 화면 |
| 6 | 고장 주입·시나리오, 수용 테스트 | AC-01~14 통과 |
| 7 | 현장 실사 반영(`[가정]` 해소), `hybrid` 모드로 실장비 연결 | 실장비 1대 이상 연결 |

---

## 16. 현장 실사 체크리스트

- [ ] 염도센서 모델, Modbus 레지스터 맵, 절임통 8기 매핑 방식 (Q3)
- [ ] THD-WD1-T, FOX-2003CC 통신 매뉴얼 (Modbus RTU 여부, 레지스터, 통신 속도)
- [ ] 금속검출기 대수·모델·RS-485 지원 여부 (Q4)
- [ ] 중량 저울 모델·통신 포트 (Q5), 충진기·속넣기기계 통신 인터페이스 (Q6)
- [ ] XBL-EMTA600 경유 소독수 공급장치의 통신 방식 (Modbus TCP / XGT 전용)
- [ ] KF 100 OPC-UA 노드 목록, 엔드포인트, 보안 정책
- [ ] PLC Master/Slave 실제 D영역 주소 배정, 버스 구성, 온습도센서 배분 (Q10)
- [ ] 설비별 수집 주기 (Q1), Edge 버퍼 보존 기간 (Q2)
- [ ] 냉장고 대수·온도조절기 배치 (Q7), HACCP 관리계획서의 CCP 한계기준 (Q8)
- [ ] 설비망·사무망 분리 여부 (Q9)
