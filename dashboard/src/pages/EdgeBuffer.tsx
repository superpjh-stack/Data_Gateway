import { Fragment, useMemo } from 'react'
import { LineChart } from '../components/LineChart'
import { Card, ErrorLine, Kpi, PageTitle, Skeleton, StatusBadge } from '../components/ui'
import { fmtDateTime, fmtPct, fmtTime } from '../lib/format'
import { usePoll } from '../lib/hooks'
import { useTwin } from '../lib/store'
import type { BufferStats, Diag } from '../lib/types'
import P from './pages.module.css'

interface EdgeStatus {
  id: string
  mes_link: string
  last_send_ok: string | null
  last_error: string | null
  samples_in: number
  filtered: Record<string, number>
  filtered_recent: { equip: string; key: string; value: number; ts: string }[]
  buffer: BufferStats
  plcs: Record<string, { state: string; slave_link: string | null; diag_words: number[]; link: Diag }>
}

/** UI-07 Edge 버퍼 */
export default function EdgeBuffer() {
  const { data, error, reload } = usePoll<EdgeStatus>('/api/edge/buffer', 1000)
  const hist = useTwin((s) => s.bufferHistory)
  const series = useMemo(() => [{ name: '대기 항목', data: hist.map((p) => [p.t, p.pending] as [number, number]) }], [hist])
  const b = data?.buffer
  return (
    <>
      <PageTitle sub="Mini PC T1 X300 · SQLite 로컬 버퍼 · 보존 72시간(가정 Q2)">Edge 버퍼</PageTitle>
      <ErrorLine error={error} onRetry={reload} />
      {!data || !b ? (
        <Skeleton height={300} />
      ) : (
        <>
          <Card>
            <div className={P.kpiRow}>
              <Kpi label="MES 링크" value={<StatusBadge status={data.mes_link === 'OK' ? 'OK' : 'DOWN'} />} />
              <Kpi label="대기 샘플 / 항목" value={`${b.pending_samples} / ${b.pending_items}`} color={b.pending_items ? 'var(--delay)' : undefined} />
              <Kpi label="누적 전송 항목" value={b.sent_total.toLocaleString('ko-KR')} />
              <Kpi label="재전송(RESEND_YN=Y)" value={b.resent_total.toLocaleString('ko-KR')} />
              <Kpi label="보존 초과 삭제" value={b.purged_total} color={b.purged_total ? 'var(--down)' : undefined} />
              <Kpi label="가장 오래된 대기" value={b.oldest ? fmtTime(b.oldest) : '—'} />
              <Kpi label="msg_id 발급" value={b.seq.toLocaleString('ko-KR')} />
            </div>
          </Card>
          <div style={{ height: 12 }} />
          <div className={P.twoCol}>
            <Card title="대기 항목 추이" extra={<small>최근 10분 · 이 브라우저가 연결된 동안</small>}>
              <LineChart series={series} height={240} />
              <div className="dim" style={{ fontSize: '0.8rem' }}>
                마지막 전송 성공 {fmtDateTime(data.last_send_ok)}
                {data.last_error && data.mes_link !== 'OK' && <> · 오류 {data.last_error}</>}
              </div>
            </Card>
            <div className={P.stack}>
              <Card title="PLC 읽기 (Modbus TCP)">
                <div className={P.statusList}>
                  {Object.entries(data.plcs).map(([id, p]) => (
                    <Fragment key={id}>
                      <span>{id} <span className="dim">성공률 {fmtPct(p.link.success_1m)}</span></span>
                      <StatusBadge status={p.state} />
                      {p.slave_link && (
                        <>
                          <span className="dim">Master–Slave 연동(D0902)</span>
                          <StatusBadge status={p.slave_link === 'OK' ? 'OK' : 'DOWN'} />
                        </>
                      )}
                    </Fragment>
                  ))}
                </div>
              </Card>
              <Card title="노이즈 필터 (FILTERED)" extra={<small>수집 {data.samples_in.toLocaleString('ko-KR')}샘플</small>}>
                {data.filtered_recent.length === 0 ? (
                  <span className="dim">걸러진 값 없음</span>
                ) : (
                  data.filtered_recent.slice().reverse().slice(0, 10).map((f, i) => (
                    <div key={i} className="num" style={{ fontSize: '0.8rem' }}>
                      {fmtTime(f.ts)} <b>{f.equip}</b> {f.key}={f.value}
                    </div>
                  ))
                )}
                <div className="dim" style={{ fontSize: '0.75rem', marginTop: 6 }}>
                  {Object.entries(data.filtered).map(([k, v]) => `${k} ${v}건`).join(' · ')}
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  )
}
