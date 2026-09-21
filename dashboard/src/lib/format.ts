import type { ItemDef, Status } from './types'

export const STATUS_META: Record<Status, { icon: string; label: string; color: string }> = {
  OK: { icon: '●', label: '정상', color: 'var(--ok)' },
  DELAY: { icon: '▲', label: '지연', color: 'var(--delay)' },
  DOWN: { icon: '✕', label: '끊김', color: 'var(--down)' },
  ERROR: { icon: '■', label: '오류', color: 'var(--error)' },
  STALE: { icon: '◌', label: '갱신없음', color: 'var(--inactive)' },
  INACTIVE: { icon: '–', label: '비활성', color: 'var(--inactive)' },
  UNKNOWN: { icon: '?', label: '확인중', color: 'var(--inactive)' },
}

export function statusMeta(s: string | undefined | null) {
  return STATUS_META[(s ?? 'UNKNOWN') as Status] ?? STATUS_META.UNKNOWN
}

export const UNIT_LABEL: Record<string, string> = {
  PCT: '%',
  DEGC: '℃',
  PCT_RH: '%RH',
  PPM: 'ppm',
  MIN: '분',
  EA: '개',
  BOX: '박스',
  KG: 'kg',
  G: 'g',
  EA_MIN: '개/분',
  NO: '번',
  CODE: '',
  BITS: '',
}

export function unitLabel(u: string | undefined): string {
  if (!u) return ''
  return UNIT_LABEL[u] ?? u
}

/** 레지스터 스케일에 맞는 소수 자릿수 (0.01 → 2). */
export function digitsFor(item?: Pick<ItemDef, 'scale' | 'type'>): number {
  if (!item) return 2
  if (item.type === 'float') return 2
  if (item.scale >= 1) return 0
  return Math.max(0, Math.round(-Math.log10(item.scale)))
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

const pad = (n: number) => String(n).padStart(2, '0')

/** HH:MM:SS (브라우저 로캘과 무관하게 고정). */
export function hms(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return hms(d)
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hms(d)}`
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 60) return `${s}초 전`
  if (s < 3600) return `${Math.floor(s / 60)}분 전`
  return `${Math.floor(s / 3600)}시간 전`
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return '무기한'
  const s = Math.ceil(sec)
  const m = Math.floor(s / 60)
  return `${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export const SEVERITY_LABEL: Record<string, string> = { LOW: '낮음', MEDIUM: '중간', HIGH: '높음', CRITICAL: '긴급' }

export const PROCESS_ORDER = [
  '입고/보관',
  '절단/전처리',
  '세척/절임',
  '세척/선별',
  '탈수',
  '혼합(버무림)',
  '금속검출',
  '포장/출고',
  '냉장·숙성',
]
