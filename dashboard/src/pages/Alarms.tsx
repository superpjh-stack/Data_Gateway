import { useState } from 'react'
import { Card, DataTable, ErrorLine, PageTitle, Skeleton, ui } from '../components/ui'
import { post } from '../lib/api'
import { ago, fmtDateTime, SEVERITY_LABEL } from '../lib/format'
import { usePoll, useNow } from '../lib/hooks'
import { activeAlarms, useTwin } from '../lib/store'
import type { Alarm, CcpRule } from '../lib/types'
import P from './pages.module.css'

const STATE_LABEL: Record<string, string> = { RAISED: '발생', ACKED: '확인', CLEARED: '해제' }
const SEV_COLOR: Record<string, string> = { LOW: 'var(--text-dim)', MEDIUM: 'var(--delay)', HIGH: 'var(--down)', CRITICAL: 'var(--down)' }

/** UI-09 알람: 활성 알람 · 이력 · CCP 기준 */
export default function Alarms() {
  const live = useTwin((s) => s.alarms)
  const now = useNow()
  const [cat, setCat] = useState('')
  const [equip, setEquip] = useState('')
  const qs = new URLSearchParams({ limit: '300', ...(cat && { category: cat }), ...(equip && { equip }) })
  const { data: hist, error, reload } = usePoll<Alarm[]>(`/api/alarms?${qs}`, 3000)
  const { data: ccp } = usePoll<CcpRule[]>('/api/ccp')
  const active = activeAlarms(live)
  const ack = async (id: number) => {
    await post(`/api/alarms/${id}/ack`)
    reload()
  }
  return (
    <>
      <PageTitle sub={`활성 ${active.length}건`}>알람</PageTitle>
      <ErrorLine error={error} onRetry={reload} />
      <div className={P.stack}>
        {active.length === 0 ? (
          <Card><span className="dim">● 활성 알람이 없습니다</span></Card>
        ) : (
          active.map((a) => (
            <div key={a.alarm_id} className={a.state === 'ACKED' ? P.alarmAcked : P.alarmCard} data-testid="active-alarm">
              <span>
                <b style={{ color: SEV_COLOR[a.severity] }}>{SEVERITY_LABEL[a.severity]}</b>{' '}
                <span className="dim">{a.category === 'CCP' ? 'CCP' : '통신'}</span> · <b className="num">{a.equip_code}</b> {a.message}
              </span>
              <span>
                {a.state === 'RAISED' ? (
                  <button className={ui.btn} onClick={() => ack(a.alarm_id)}>확인</button>
                ) : (
                  <span className="dim">확인됨 · 정상 복귀 대기</span>
                )}
              </span>
              <span className="dim num" style={{ fontSize: '0.8rem' }}>
                발생 {fmtDateTime(a.raised_dt)} ({ago(a.raised_dt, now)}){a.value && ` · 값 ${a.value}`}
              </span>
            </div>
          ))
        )}
        <div className={P.twoCol}>
          <Card title="이력">
            <div className={ui.toolbar}>
              <select className={ui.input} value={cat} onChange={(e) => setCat(e.target.value)} aria-label="분류">
                <option value="">분류 전체</option>
                <option value="CCP">CCP 기준 이탈</option>
                <option value="COMM">통신</option>
              </select>
              <input className={ui.input} placeholder="설비 코드" value={equip} onChange={(e) => setEquip(e.target.value.toUpperCase())} aria-label="설비" />
            </div>
            {!hist ? (
              <Skeleton height={300} />
            ) : (
              <DataTable
                rows={hist}
                rowKey={(a) => a.alarm_id}
                columns={[
                  { key: 'id', label: '#', right: true, render: (a) => <span className="num">{a.alarm_id}</span>, sort: (a) => a.alarm_id },
                  { key: 'raised', label: '발생', render: (a) => <span className="num">{fmtDateTime(a.raised_dt)}</span>, sort: (a) => a.raised_dt },
                  { key: 'cat', label: '분류', render: (a) => a.category, sort: (a) => a.category },
                  { key: 'sev', label: '심각도', render: (a) => <span style={{ color: SEV_COLOR[a.severity] }}>{SEVERITY_LABEL[a.severity]}</span> },
                  { key: 'eq', label: '설비', render: (a) => <b className="num">{a.equip_code}</b>, sort: (a) => a.equip_code },
                  { key: 'msg', label: '내용', render: (a) => a.message },
                  { key: 'st', label: '상태', render: (a) => STATE_LABEL[a.state], sort: (a) => a.state },
                  { key: 'clr', label: '해제', render: (a) => <span className="num dim">{fmtDateTime(a.cleared_dt)}</span> },
                ]}
              />
            )}
          </Card>
          <Card title="CCP 기준" extra={<small>config/ccp_std.yaml → BAS_CCP_STD</small>}>
            {(ccp ?? []).map((r) => (
              <div key={r.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: '0.85rem' }}>
                <b>{r.item}</b>{' '}
                <span className={r.basis === '설계' ? 'dim' : undefined} style={r.basis === '가정' ? { border: '1px dashed var(--delay)', color: 'var(--delay)', borderRadius: 4, padding: '0 4px', fontSize: '0.7rem' } : { fontSize: '0.7rem' }}>
                  {r.basis}
                </span>
                <div className="dim num" style={{ fontSize: '0.78rem' }}>
                  {r.equip.join(', ')} · {describe(r)}
                </div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  )
}

function describe(r: CcpRule) {
  const parts: string[] = []
  if (r.low !== null) parts.push(`≥ ${r.low}${r.unit}`)
  if (r.high !== null) parts.push(`≤ ${r.high}${r.unit}`)
  if (r.band !== null) parts.push(`목표 ±${r.band}${r.unit}`)
  if (r.band_pct !== null) parts.push(`${r.std}${r.unit} ±${r.band_pct}%`)
  if (r.ng_immediate) parts.push('NG 즉시')
  if (r.hold_sec) parts.push(`${r.hold_sec}초 지속`)
  return parts.join(' · ')
}
