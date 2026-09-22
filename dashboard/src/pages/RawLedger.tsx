import { useState } from 'react'
import { PurgeCard } from '../components/PurgeCard'
import { Card, DataTable, ErrorLine, PageTitle, Skeleton, ui } from '../components/ui'
import { fmtTime, unitLabel } from '../lib/format'
import { usePoll } from '../lib/hooks'
import type { Equip } from '../lib/types'
import P from './pages.module.css'

interface RawRow {
  RAW_ID: number
  EQUIP_CODE: string
  TAG_ADDR: string
  DATA_TYPE: string
  RAW_VALUE: string
  UNIT_CD: string | null
  COMM_TYPE: string
  TARGET_TABLE: string | null
  RESEND_YN: string
  COLLECT_DT: string
  MSG_ID: string
  ITEM_KEY: string
  RECEIVED_DT: string
}

/** UI-08 수집 원장 (IF_SENSOR_RAW) */
export default function RawLedger() {
  const [equip, setEquip] = useState('')
  const [resend, setResend] = useState('')
  const [paused, setPaused] = useState(false)
  const qs = new URLSearchParams({ limit: '200', ...(equip && { equip }), ...(resend && { resend }) })
  const { data, error, reload } = usePoll<RawRow[]>(`/api/raw?${qs}`, paused ? 0 : 2000)
  const { data: equips } = usePoll<Equip[]>('/api/equip')
  const { data: stats } = usePoll<{ counts: Record<string, number>; ingested: number; duplicates: number; last_ingest: string | null }>(
    '/api/tables/stats',
    3000,
  )
  return (
    <>
      <PageTitle sub="Edge 표준 메시지 = IF_SENSOR_RAW 한 행 (TD5 설비센서수집원장)">수집 원장</PageTitle>
      <ErrorLine error={error} onRetry={reload} />
      <div className={P.twoCol}>
        <Card>
          <div className={ui.toolbar}>
            <select className={ui.input} value={equip} onChange={(e) => setEquip(e.target.value)} aria-label="설비">
              <option value="">설비 전체</option>
              {(equips ?? []).map((e) => <option key={e.code}>{e.code}</option>)}
            </select>
            <select className={ui.input} value={resend} onChange={(e) => setResend(e.target.value)} aria-label="재전송">
              <option value="">RESEND_YN 전체</option>
              <option value="Y">Y (버퍼 복구분)</option>
              <option value="N">N</option>
            </select>
            <button className={ui.btn} onClick={() => setPaused((p) => !p)}>{paused ? '▶ 자동 갱신' : '❚❚ 일시정지'}</button>
            <span className="dim">최근 200행</span>
          </div>
          {!data ? (
            <Skeleton height={400} />
          ) : (
            <DataTable
              rows={data}
              rowKey={(r) => r.RAW_ID}
              columns={[
                { key: 'id', label: 'RAW_ID', right: true, render: (r) => <span className="num">{r.RAW_ID}</span>, sort: (r) => r.RAW_ID },
                { key: 'eq', label: '설비', render: (r) => <b className="num">{r.EQUIP_CODE}</b>, sort: (r) => r.EQUIP_CODE },
                { key: 'tag', label: 'TAG_ADDR', render: (r) => <span className="num dim">{r.TAG_ADDR}</span> },
                { key: 'dt', label: 'DATA_TYPE', render: (r) => r.DATA_TYPE },
                { key: 'v', label: 'RAW_VALUE', right: true, render: (r) => <span className="num">{r.RAW_VALUE}<span className="unit">{unitLabel(r.UNIT_CD ?? '')}</span></span> },
                { key: 'c', label: 'COMM_TYPE', render: (r) => <span className="dim">{r.COMM_TYPE}</span> },
                { key: 't', label: 'TARGET_TABLE', render: (r) => <span className="num dim">{r.TARGET_TABLE}</span> },
                { key: 'r', label: 'RESEND', render: (r) => <span style={{ color: r.RESEND_YN === 'Y' ? 'var(--delay)' : undefined }}>{r.RESEND_YN}</span>, sort: (r) => r.RESEND_YN },
                { key: 'cd', label: 'COLLECT_DT', render: (r) => <span className="num">{fmtTime(r.COLLECT_DT)}</span>, sort: (r) => r.COLLECT_DT },
                { key: 'msg', label: 'MSG_ID', render: (r) => <span className="num dim">{r.MSG_ID}</span> },
              ]}
            />
          )}
        </Card>
        <div className={P.stack}>
        <Card title="분배 테이블 행 수">
          {!stats ? (
            <Skeleton height={200} />
          ) : (
            <div className={P.statusList}>
              {Object.entries(stats.counts).map(([t, n]) => (
                <span key={t} style={{ display: 'contents' }}>
                  <span className="num" style={{ fontSize: '0.8rem' }}>{t}</span>
                  <span className="num" style={{ textAlign: 'right' }}>{n.toLocaleString('ko-KR')}</span>
                </span>
              ))}
              <span className="dim">중복 수신(무시)</span>
              <span className="num" style={{ textAlign: 'right' }}>{stats.duplicates}</span>
              <span className="dim">마지막 적재</span>
              <span className="num" style={{ textAlign: 'right' }}>{fmtTime(stats.last_ingest)}</span>
            </div>
          )}
        </Card>
        <PurgeCard />
        </div>
      </div>
    </>
  )
}
