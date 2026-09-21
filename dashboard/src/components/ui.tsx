import { useMemo, useState, type ReactNode } from 'react'
import { statusMeta } from '../lib/format'
import s from './ui.module.css'

export { s as ui }

export function StatusBadge({ status, compact = false }: { status: string | null | undefined; compact?: boolean }) {
  const m = statusMeta(status)
  return (
    <span className={s.badge} style={{ color: m.color }} title={m.label} data-status={status ?? 'UNKNOWN'}>
      <span className={s.badgeIcon} aria-hidden>
        {m.icon}
      </span>
      {!compact && m.label}
      {compact && <span className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden' }}>{m.label}</span>}
    </span>
  )
}

export function AssumedBadge({ items }: { items: string[] }) {
  if (!items.length) return null
  return (
    <span className={s.assumed} title={`현장 확인 필요: ${items.join(', ')}`}>
      가정
    </span>
  )
}

export function Card({ title, extra, children, className }: { title?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`${s.card} ${className ?? ''}`}>
      {title && (
        <h3 className={s.cardTitle}>
          <span>{title}</span>
          {extra}
        </h3>
      )}
      {children}
    </section>
  )
}

export function Kpi({ label, value, unit, color }: { label: string; value: ReactNode; unit?: string; color?: string }) {
  return (
    <div className={s.kpi}>
      <span className={s.kpiLabel}>{label}</span>
      <span className={s.kpiValue} style={color ? { color } : undefined}>
        {value}
        {unit && <span className="unit">{unit}</span>}
      </span>
    </div>
  )
}

export function Skeleton({ height = 120 }: { height?: number }) {
  return <div className={s.skeleton} style={{ height }} aria-label="불러오는 중" />
}

export function Empty({ children = '아직 수집된 데이터가 없습니다' }: { children?: ReactNode }) {
  return <div className={s.empty}>{children}</div>
}

export function ErrorLine({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null
  return (
    <div className={s.errorLine} role="alert">
      <span>불러오지 못했습니다: {error}</span>
      {onRetry && (
        <button className={s.btn} onClick={onRetry}>
          다시 시도
        </button>
      )}
    </div>
  )
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <h2 className={s.pageTitle}>
      {children}
      {sub && <small>{sub}</small>}
    </h2>
  )
}

export interface Column<T> {
  key: string
  label: string
  render: (row: T) => ReactNode
  sort?: (row: T) => string | number
  right?: boolean
  width?: number | string
}

/** 머리글을 누르면 정렬되는 표. rows가 많으면 maxRows까지만 그린다. */
export function DataTable<T>({ rows, columns, rowKey, maxRows = 1000, initialSort, onRowClick }: {
  rows: T[]
  columns: Column<T>[]
  rowKey: (r: T) => string | number
  maxRows?: number
  initialSort?: { key: string; dir: 1 | -1 }
  onRowClick?: (r: T) => void
}) {
  const [sort, setSort] = useState(initialSort ?? null)
  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sort) return rows
    const f = col.sort
    return [...rows].sort((a, b) => {
      const x = f(a)
      const y = f(b)
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir
    })
  }, [rows, columns, sort])
  const shown = sorted.slice(0, maxRows)
  return (
    <div className={s.tableWrap}>
      <table className={s.table}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`${c.sort ? s.sortable : ''} ${c.right ? s.right : ''}`}
                style={c.width ? { width: c.width } : undefined}
                onClick={c.sort ? () => setSort((p) => ({ key: c.key, dir: p?.key === c.key ? ((-p.dir) as 1 | -1) : 1 })) : undefined}
                aria-sort={sort?.key === c.key ? (sort.dir === 1 ? 'ascending' : 'descending') : undefined}
                tabIndex={c.sort ? 0 : undefined}
                onKeyDown={c.sort ? (e) => e.key === 'Enter' && setSort((p) => ({ key: c.key, dir: p?.key === c.key ? ((-p.dir) as 1 | -1) : 1 })) : undefined}
              >
                {c.label}
                {sort?.key === c.key && (sort.dir === 1 ? ' ↑' : ' ↓')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined} style={onRowClick ? { cursor: 'pointer' } : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={c.right ? s.right : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > maxRows && <div className="dim" style={{ padding: 8 }}>{sorted.length - maxRows}행 더 있음 — 필터로 좁혀 보세요</div>}
    </div>
  )
}
