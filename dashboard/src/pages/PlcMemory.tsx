import { Fragment, useEffect, useRef, useState } from 'react'
import { Card, ErrorLine, PageTitle, Skeleton, StatusBadge } from '../components/ui'
import { fmtTime } from '../lib/format'
import { usePoll } from '../lib/hooks'
import P from './pages.module.css'

interface Label {
  code: string
  field: string
  kind: 'status' | 'value' | 'counter' | 'diag'
  type?: string
  scale?: number
  unit?: string
  word?: number
  words?: number
}

interface Mem {
  plc: string
  start: number
  words: number[]
  running: boolean
  labels: Record<string, Label>
  diag: Record<string, unknown>
  write_rejections: { ts: string; fc: number; name: string; peer: string; pdu: string }[]
}

const addr = (n: number) => `D${String(n).padStart(4, '0')}`
const STATUS_NAME = ['OK', 'DELAY', 'DOWN', 'ERROR']

/** UI-06 PLC 메모리 (D영역). 블록이 있는 행만 보여주고, 바뀐 셀은 잠깐 강조한다. */
export default function PlcMemory() {
  const [plc, setPlc] = useState('MASTER')
  const { data, error, reload } = usePoll<Mem>(`/api/plc/${plc}/memory?start=100&count=900`, 1000)
  const prev = useRef<number[] | null>(null)
  const [changed, setChanged] = useState<Set<number>>(new Set())
  useEffect(() => {
    if (!data) return
    const p = prev.current
    const next = new Set<number>()
    if (p && p.length === data.words.length) data.words.forEach((w, i) => w !== p[i] && next.add(data.start + i))
    prev.current = data.words
    setChanged(next)
  }, [data])
  useEffect(() => {
    prev.current = null
  }, [plc])

  const rows: number[] = []
  if (data) {
    for (let r = data.start; r < data.start + data.words.length; r += 10) {
      if (Array.from({ length: 10 }, (_, i) => data.labels[addr(r + i)]).some(Boolean)) rows.push(r)
    }
  }
  const word = (n: number) => (data ? data.words[n - data.start] : 0)
  return (
    <>
      <PageTitle sub="블록 10워드: +0 상태 · +1 연속실패 · +2~+7 값(원시) · +8 갱신카운터 (가정)">PLC 메모리</PageTitle>
      <div className={P.tabs} role="tablist">
        {['MASTER', 'SLAVE'].map((id) => (
          <button key={id} role="tab" aria-selected={plc === id} className={plc === id ? P.tabOn : P.tab} onClick={() => setPlc(id)}>
            PLC {id === 'MASTER' ? 'Master' : 'Slave'}
          </button>
        ))}
      </div>
      <ErrorLine error={error} onRetry={reload} />
      {!data ? (
        <Skeleton height={400} />
      ) : (
        <div className={P.twoCol}>
          <Card title={`${plc} D영역`} extra={<StatusBadge status={data.running ? 'OK' : 'DOWN'} />}>
            <div className={P.memGrid}>
              <span className={P.memHead} />
              {Array.from({ length: 10 }, (_, i) => (
                <span key={i} className={P.memHead}>+{i}</span>
              ))}
              {rows.map((r) => {
                const first = data.labels[addr(r)]
                return (
                  <Fragment key={r}>
                    {first && first.kind !== 'diag' && <span className={P.memLabel}>{first.code}</span>}
                    {first?.kind === 'diag' && <span className={P.memLabel}>진단 영역</span>}
                    <span className={P.memAddr}>{addr(r)}</span>
                    {Array.from({ length: 10 }, (_, i) => {
                      const n = r + i
                      const lb = data.labels[addr(n)]
                      const w = word(n)
                      const cls = [P.memCell, changed.has(n) ? 'flash' : '', lb?.kind === 'status' && lb.field === '통신상태' ? P[`memStatus${w}`] : '']
                        .filter(Boolean)
                        .join(' ')
                      return (
                        <span key={`${n}-${changed.has(n) ? w : ''}`} className={cls} title={tooltip(n, w, lb)} style={lb ? undefined : { color: 'var(--border)' }}>
                          {lb?.kind === 'status' && lb.field === '통신상태' ? STATUS_NAME[w] ?? w : w}
                        </span>
                      )
                    })}
                  </Fragment>
                )
              })}
            </div>
          </Card>
          <div className={P.stack}>
            <Card title="진단">
              <div className={P.statusList}>
                {Object.entries(data.diag).map(([k, v]) => (
                  <Fragment key={k}>
                    <span className="dim">{DIAG_LABEL[k] ?? k}</span>
                    <span className="num" style={{ textAlign: 'right' }}>{String(v ?? '—')}</span>
                  </Fragment>
                ))}
              </div>
            </Card>
            <Card title="거부된 쓰기 요청" extra={<small>FC 05/06/15/16 → 예외 01</small>}>
              {data.write_rejections.length === 0 ? (
                <span className="dim">없음 — 설비 쓰기 경로 차단됨</span>
              ) : (
                data.write_rejections.slice().reverse().map((w) => (
                  <div key={`${w.ts}-${w.fc}`} className="num" style={{ fontSize: '0.8rem' }}>
                    {fmtTime(w.ts)} FC{w.fc} {w.name} <span className="dim">{w.peer}</span>
                  </div>
                ))
              )}
            </Card>
          </div>
        </div>
      )}
    </>
  )
}

const DIAG_LABEL: Record<string, string> = {
  id: 'PLC',
  running: '가동',
  heartbeat: 'D0900 하트비트',
  bus_bits: 'D0901 버스 이상 비트',
  slave_hb_mirror: 'D0902 Slave 하트비트',
  scan_ms: 'D0903 스캔시간(ms)',
  ok_count: 'D0904 정상 장비 수',
  slave_link: 'Slave 링크',
  write_rejections: '거부된 쓰기',
}

function tooltip(n: number, w: number, lb?: Label) {
  if (!lb) return `${addr(n)} · 미사용`
  let eng = ''
  if (lb.kind === 'value' && lb.words === 1 && lb.scale !== undefined) {
    const raw = lb.type === 'int16' && w & 0x8000 ? w - 0x10000 : w
    eng = ` → ${+(raw * lb.scale).toFixed(4)} ${lb.unit ?? ''}`
  }
  return `${addr(n)} · ${lb.code} ${lb.field} 원시값 ${w}${eng}`
}
