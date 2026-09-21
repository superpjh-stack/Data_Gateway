import { describe, expect, it } from 'vitest'
import { ago, digitsFor, fmtDuration, fmtNum, fmtPct, fmtTime, hms, statusMeta, unitLabel } from '../src/lib/format'
import { activeAlarms, reduce, useTwin, type TwinState } from '../src/lib/store'
import type { Alarm } from '../src/lib/types'

const base = () => useTwin.getState() as TwinState

describe('format', () => {
  it('상태는 색·아이콘·라벨을 함께 가진다', () => {
    expect(statusMeta('DOWN')).toMatchObject({ icon: '✕', label: '끊김' })
    expect(statusMeta('weird').label).toBe('확인중')
    expect(statusMeta(null).icon).toBe('?')
  })
  it('스케일에 맞춰 자릿수를 정한다', () => {
    expect(digitsFor({ scale: 0.01, type: 'uint16' })).toBe(2)
    expect(digitsFor({ scale: 0.1, type: 'int16' })).toBe(1)
    expect(digitsFor({ scale: 1, type: 'uint32' })).toBe(0)
    expect(fmtNum(12.345, 2)).toBe('12.35')
    expect(fmtNum(null)).toBe('—')
    expect(fmtPct(0.9964)).toBe('99.6%')
  })
  it('시각은 로캘과 무관하게 HH:MM:SS', () => {
    expect(hms(new Date(2026, 8, 21, 7, 5, 9))).toBe('07:05:09')
    expect(fmtTime(null)).toBe('—')
    expect(fmtDuration(125)).toBe('02:05')
    expect(fmtDuration(null)).toBe('무기한')
    expect(ago(new Date(Date.now() - 90_000).toISOString())).toBe('1분 전')
  })
  it('단위 코드를 표시용으로 바꾼다', () => {
    expect(unitLabel('DEGC')).toBe('℃')
    expect(unitLabel('PPM')).toBe('ppm')
    expect(unitLabel('XYZ')).toBe('XYZ')
  })
})

describe('store.reduce', () => {
  const alarm = (id: number, state: Alarm['state']): Alarm => ({
    alarm_id: id, category: 'CCP', rule_id: 'CCP-SAN', item: '소독수농도', equip_code: 'SAN-01', severity: 'HIGH',
    message: 'm', value: '8.5', value_key: '', state, raised_dt: '2026-09-21T10:00:00+09:00', acked_dt: null, cleared_dt: null,
  })

  it('스냅샷으로 상태를 복원한다', () => {
    const next = reduce(base(), {
      type: 'snapshot',
      summary: { total: 22, ok: 21 },
      topology: { nodes: [{ id: 'THD-01', kind: 'device', status: 'OK' }, { id: 'M1', kind: 'bus', status: 'OK' }], links: [] },
      alarms: [alarm(1, 'RAISED')],
      values: { 'THD-01': { values: { temp: 9 }, ts: 'x' } },
    })
    expect(next.status).toEqual({ 'THD-01': 'OK' })
    expect(next.alarms?.[1].state).toBe('RAISED')
    expect(next.values?.['THD-01'].values.temp).toBe(9)
  })

  it('값 메시지는 이전 항목과 합쳐진다', () => {
    const s1 = { ...base(), ...reduce(base(), { type: 'value', equip: 'TC-01', values: { pv: 2 }, ts: 'a' }) } as TwinState
    const s2 = reduce(s1, { type: 'value', equip: 'TC-01', values: { sv: 3 }, ts: 'b' })
    expect(s2.values?.['TC-01'].values).toEqual({ pv: 2, sv: 3 })
  })

  it('새 알람만 lastAlarmId를 바꾸고, 해제된 알람은 활성 목록에서 빠진다', () => {
    const s1 = { ...base(), ...reduce(base(), { type: 'alarm', ...alarm(7, 'RAISED') }) } as TwinState
    expect(s1.lastAlarmId).toBe(7)
    const s2 = { ...s1, ...reduce(s1, { type: 'alarm', ...alarm(7, 'CLEARED') }) } as TwinState
    expect(activeAlarms(s2.alarms).map((a) => a.alarm_id)).not.toContain(7)
  })

  it('버퍼 이력은 최근 10분만 남긴다', () => {
    const old = { ...base(), bufferHistory: [{ t: Date.now() - 11 * 60_000, pending: 5 }] } as TwinState
    const next = reduce(old, { type: 'edge_buffer', pending_items: 3 })
    expect(next.bufferHistory).toHaveLength(1)
    expect(next.bufferHistory?.[0].pending).toBe(3)
  })
})
