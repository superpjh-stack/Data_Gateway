import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AssumedBadge, Card, DataTable, ErrorLine, PageTitle, Skeleton, StatusBadge, ui, type Column } from '../components/ui'
import { ago, fmtNum, fmtPct, PROCESS_ORDER, statusMeta } from '../lib/format'
import { usePoll, useNow } from '../lib/hooks'
import { useTwin } from '../lib/store'
import type { Equip } from '../lib/types'

/** UI-04 수집 현황 표 */
export default function Collection() {
  const { data, error, reload } = usePoll<Equip[]>('/api/equip', 2000)
  const live = useTwin((s) => s.status)
  const now = useNow()
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [st, setSt] = useState('')
  const [comm, setComm] = useState('')
  const [proc, setProc] = useState('')
  const rows = useMemo(
    () =>
      (data ?? [])
        .map((e) => ({ ...e, status: live[e.code] ?? e.status }))
        .filter((e) => (!st || e.status === st) && (!comm || e.comm_type === comm) && (!proc || e.process === proc))
        .filter((e) => !q || `${e.code} ${e.name} ${e.model ?? ''}`.toLowerCase().includes(q.toLowerCase())),
    [data, live, q, st, comm, proc],
  )
  const comms = [...new Set((data ?? []).map((e) => e.comm_type))]
  const cols: Column<Equip>[] = [
    { key: 'status', label: '상태', render: (e) => <StatusBadge status={e.status} />, sort: (e) => statusMeta(e.status).label },
    { key: 'code', label: '설비 코드', render: (e) => <b className="num">{e.code}</b>, sort: (e) => e.code },
    { key: 'name', label: '장비', render: (e) => <>{e.name} {e.model && <span className="dim">{e.model}</span>}</>, sort: (e) => e.name },
    { key: 'process', label: '공정', render: (e) => e.process, sort: (e) => PROCESS_ORDER.indexOf(e.process) },
    { key: 'comm', label: '통신', render: (e) => e.comm_type, sort: (e) => e.comm_type },
    { key: 'conn', label: '연결', render: (e) => <span className="num">{e.label}{e.plc_block && <span className="dim"> · {e.plc_block}</span>}</span> },
    { key: 'poll', label: '주기', right: true, render: (e) => <span className="num">{fmtNum(e.poll_ms / 1000, e.poll_ms < 1000 ? 1 : 0)}s</span>, sort: (e) => e.poll_ms },
    { key: 's1m', label: '성공률 1분', right: true, render: (e) => <span className="num">{fmtPct(e.diag?.success_1m)}</span>, sort: (e) => e.diag?.success_1m ?? -1 },
    { key: 's1h', label: '1시간', right: true, render: (e) => <span className="num">{fmtPct(e.diag?.success_1h)}</span>, sort: (e) => e.diag?.success_1h ?? -1 },
    { key: 'rtt', label: '평균 응답', right: true, render: (e) => <span className="num">{fmtNum(e.diag?.avg_rtt_ms, 1)}<span className="unit">ms</span></span>, sort: (e) => e.diag?.avg_rtt_ms ?? -1 },
    { key: 'last', label: '마지막 수신', right: true, render: (e) => <span className="num">{ago(e.diag?.last_ok, now)}</span>, sort: (e) => e.diag?.last_ok ?? '' },
    {
      key: 'err', label: '타임아웃/CRC/예외/프레임', right: true,
      render: (e) => <span className="num">{['timeout', 'crc', 'exception', 'frame'].map((k) => e.diag?.errors?.[k] ?? 0).join(' / ')}</span>,
      sort: (e) => Object.values(e.diag?.errors ?? {}).reduce((a, b) => a + b, 0),
    },
    { key: 'assumed', label: '가정', render: (e) => <AssumedBadge items={e.assumed} />, sort: (e) => e.assumed.length },
  ]
  return (
    <>
      <PageTitle sub={`${rows.length} / ${data?.length ?? 0}개 표시`}>수집 현황</PageTitle>
      <ErrorLine error={error} onRetry={reload} />
      <Card>
        <div className={ui.toolbar}>
          <input className={ui.input} placeholder="설비 코드·이름 검색" value={q} onChange={(e) => setQ(e.target.value)} aria-label="검색" />
          <select className={ui.input} value={st} onChange={(e) => setSt(e.target.value)} aria-label="상태 필터">
            <option value="">상태 전체</option>
            {['OK', 'DELAY', 'DOWN', 'ERROR', 'STALE'].map((s) => (
              <option key={s} value={s}>{statusMeta(s).label}</option>
            ))}
          </select>
          <select className={ui.input} value={comm} onChange={(e) => setComm(e.target.value)} aria-label="통신 필터">
            <option value="">통신 전체</option>
            {comms.map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className={ui.input} value={proc} onChange={(e) => setProc(e.target.value)} aria-label="공정 필터">
            <option value="">공정 전체</option>
            {PROCESS_ORDER.map((p) => <option key={p}>{p}</option>)}
          </select>
        </div>
        {!data ? <Skeleton height={400} /> : <DataTable rows={rows} columns={cols} rowKey={(e) => e.code} onRowClick={(e) => nav(`/equip/${e.code}`)} />}
      </Card>
    </>
  )
}
