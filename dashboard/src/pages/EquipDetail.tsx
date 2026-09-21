import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { LineChart, type Series } from '../components/LineChart'
import { AssumedBadge, Card, DataTable, ErrorLine, PageTitle, Skeleton, StatusBadge } from '../components/ui'
import { Value } from '../components/Value'
import { ago, fmtNum, fmtPct, fmtTime, unitLabel } from '../lib/format'
import { usePoll, useNow } from '../lib/hooks'
import { useTwin } from '../lib/store'
import type { CcpRule, Equip } from '../lib/types'
import P from './pages.module.css'

interface Frame {
  ts: string
  tx: string
  rx: string
  result: string
  rtt_ms: number | null
}

const NUMERIC_CHART_SKIP = new Set(['tank_no', 'sensor_state', 'out_state', 'result', 'run', 'running', 'alarm_code'])

/** UI-05 장비 상세 */
export default function EquipDetail() {
  const { code = '' } = useParams()
  const { data: e, error, reload } = usePoll<Equip>(`/api/equip/${code}`, 2000)
  const { data: frames } = usePoll<Frame[]>(`/api/equip/${code}/frames`, 2000)
  const { data: hist } = usePoll<{ series: Record<string, [string, number][]> }>(`/api/equip/${code}/history?minutes=60`, 10000)
  const { data: ccp } = usePoll<CcpRule[]>('/api/ccp')
  const status = useTwin((s) => s.status[code])
  const live = useTwin((s) => s.values[code])
  const now = useNow()
  const values = { ...(e?.values ?? {}), ...(live?.values ?? {}) }

  const series: Series[] = useMemo(() => {
    if (!e || !hist) return []
    return e.items
      .filter((it) => !NUMERIC_CHART_SKIP.has(it.key) && hist.series[it.key])
      .slice(0, 3)
      .map((it) => ({ name: it.name, unit: unitLabel(it.unit), data: hist.series[it.key].map(([t, v]) => [new Date(t).getTime(), v]) }))
  }, [e, hist])

  const limits = useMemo(() => {
    const out: { value: number; label: string }[] = []
    for (const r of ccp ?? []) {
      if (!r.equip.includes(code)) continue
      if (r.low !== null) out.push({ value: r.low, label: `하한 ${r.low}` })
      if (r.high !== null) out.push({ value: r.high, label: `상한 ${r.high}` })
    }
    return out
  }, [ccp, code])

  if (!e) {
    return (
      <>
        <PageTitle>{code}</PageTitle>
        <ErrorLine error={error} onRetry={reload} />
        <Skeleton height={300} />
      </>
    )
  }
  const d = e.diag
  return (
    <>
      <PageTitle sub={<Link to="/collection">← 수집 현황</Link>}>
        <span className="num">{e.code}</span> {e.name} <StatusBadge status={status ?? e.status} /> <AssumedBadge items={e.assumed} />
      </PageTitle>
      <div className={P.kpiRow} style={{ marginBottom: 12 }}>
        <Card><Info label="통신" value={`${e.comm_type}${e.model ? ` · ${e.model}` : ''}`} /></Card>
        <Card><Info label="연결" value={e.label} /></Card>
        <Card><Info label="PLC 블록" value={e.plc_block ?? '—(Edge 직결)'} /></Card>
        <Card><Info label="주기" value={`${e.poll_ms / 1000}s`} /></Card>
        <Card><Info label="성공률 1분 / 1시간" value={`${fmtPct(d?.success_1m)} / ${fmtPct(d?.success_1h)}`} /></Card>
        <Card><Info label="평균 응답" value={`${fmtNum(d?.avg_rtt_ms, 1)} ms`} /></Card>
        <Card><Info label="마지막 수신" value={ago(d?.last_ok, now)} /></Card>
        <Card><Info label="적재 테이블" value={e.target} /></Card>
      </div>
      {e.assumed.length > 0 && (
        <Card title="현장 확인 필요(가정)" className="">
          <span className="dim">{e.assumed.join(' · ')}</span>
        </Card>
      )}
      <div style={{ height: 12 }} />
      <div className={P.twoCol} style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)' }}>
        <Card title="태그">
          <DataTable
            rows={e.items}
            rowKey={(it) => it.key}
            columns={[
              { key: 'name', label: '항목', render: (it) => it.name },
              { key: 'v', label: '값', right: true, render: (it) => (it.key === 'running' ? (values[it.key] ? '가동' : '정지') : <Value v={values[it.key]} item={it} />) },
              { key: 'dt', label: '데이터 종류', render: (it) => <span className="dim">{it.data_type}</span> },
              { key: 'addr', label: '레지스터/노드', render: (it) => <span className="num dim">{it.reg ?? it.node ?? 'ASCII'}</span> },
              { key: 'type', label: '형식', render: (it) => <span className="num dim">{it.type} ×{it.scale}</span> },
            ]}
          />
          <div className="dim" style={{ marginTop: 8, fontSize: '0.8rem' }}>
            마지막 적재 {fmtTime(live?.ts ?? e.last_ts)} · 오류 누계 타임아웃 {d?.errors.timeout ?? 0} · CRC {d?.errors.crc ?? 0} · 예외 {d?.errors.exception ?? 0} · 프레임 {d?.errors.frame ?? 0}
          </div>
        </Card>
        <Card title="최근 1시간 추이" extra={<small>IF_SENSOR_RAW 기준, 10초마다 갱신</small>}>
          {series.length ? <LineChart series={series} limits={limits} /> : <Skeleton height={260} />}
        </Card>
      </div>
      <div style={{ height: 12 }} />
      <Card title="원시 프레임" extra={<small>최근 50건 · 16진</small>}>
        <div className={P.frames}>
          <DataTable
            rows={frames ?? []}
            rowKey={(f) => `${f.ts}-${f.tx}-${f.result}`}
            columns={[
              { key: 'ts', label: '시각', render: (f) => fmtTime(f.ts) },
              { key: 'tx', label: '요청', render: (f) => f.tx },
              { key: 'rx', label: '응답', render: (f) => f.rx },
              { key: 'r', label: '결과', render: (f) => <span style={{ color: f.result === 'OK' ? 'var(--ok)' : 'var(--down)' }}>{f.result}</span> },
              { key: 'rtt', label: '응답(ms)', right: true, render: (f) => fmtNum(f.rtt_ms, 1) },
            ]}
          />
        </div>
      </Card>
    </>
  )
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="dim" style={{ fontSize: '0.75rem' }}>{label}</span>
      <span className="num" style={{ fontSize: '0.9rem' }}>{value}</span>
    </div>
  )
}
