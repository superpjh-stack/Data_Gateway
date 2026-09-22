import { useState } from 'react'
import { post } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { usePoll } from '../lib/hooks'
import { Card, ui } from './ui'

interface PurgeRow {
  PURGE_ID: number
  TRIGGER_TYPE: 'SCHEDULE' | 'MANUAL'
  STARTED_DT: string
  CUTOFF_DT: string
  DELETED_TOTAL: number
  DB_BYTES_BEFORE: number | null
  DB_BYTES_AFTER: number | null
  ELAPSED_MS: number
}

interface PurgeStatus {
  enabled: boolean
  at: string
  keep_hours: number
  next: string | null
  db_bytes: number
  history: PurgeRow[]
}

export function fmtBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

/** DB 일일 정리 현황 (D-017): 다음 정리 시각, 현재 크기, 최근 이력, 수동 실행 */
export function PurgeCard() {
  const { data, reload } = usePoll<PurgeStatus>('/api/admin/purge', 10000)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const last = data?.history[0]

  const run = async () => {
    if (!confirm) {
      setConfirm(true)
      setTimeout(() => setConfirm(false), 5000)
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await post('/api/admin/purge')
      reload()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
      setConfirm(false)
    }
  }

  return (
    <Card title="DB 일일 정리" extra={<small>config/runtime.yaml mes.purge</small>}>
      {!data ? (
        <span className="dim">불러오는 중…</span>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '4px 12px', fontSize: '0.85rem' }}>
          <span className="dim">예약</span>
          <span className="num" style={{ textAlign: 'right' }}>
            {data.enabled ? `매일 ${data.at} · ${data.keep_hours ? `최근 ${data.keep_hours}시간 보존` : '전부 정리'}` : '꺼짐'}
          </span>
          <span className="dim">다음 정리</span>
          <span className="num" style={{ textAlign: 'right' }}>{fmtDateTime(data.next)}</span>
          <span className="dim">현재 DB 크기</span>
          <span className="num" style={{ textAlign: 'right' }}>{fmtBytes(data.db_bytes)}</span>
          <span className="dim">마지막 정리</span>
          <span className="num" style={{ textAlign: 'right' }}>
            {last ? `${fmtDateTime(last.STARTED_DT)} (${last.TRIGGER_TYPE === 'MANUAL' ? '수동' : '예약'})` : '없음'}
          </span>
          {last && (
            <>
              <span className="dim">삭제 행 · 크기</span>
              <span className="num" style={{ textAlign: 'right' }}>
                {last.DELETED_TOTAL.toLocaleString('ko-KR')} · {fmtBytes(last.DB_BYTES_BEFORE)} → {fmtBytes(last.DB_BYTES_AFTER)}
              </span>
            </>
          )}
        </div>
      )}
      <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className={confirm ? ui.btnDanger : ui.btn} onClick={run} disabled={busy}>
          {busy ? '정리 중…' : confirm ? '한 번 더 누르면 삭제' : '지금 정리'}
        </button>
        {err && <span style={{ color: 'var(--down)', fontSize: '0.8rem' }}>{err}</span>}
      </div>
    </Card>
  )
}
