import { digitsFor, fmtNum, unitLabel } from '../lib/format'
import { useFlashKey } from '../lib/hooks'
import type { ItemDef } from '../lib/types'

/** 숫자 값 + 흐린 단위. 값이 바뀌면 잠깐 플래시한다. */
export function Value({ v, item, unit, digits }: { v: number | undefined | null; item?: ItemDef; unit?: string; digits?: number }) {
  const key = useFlashKey(v)
  const d = digits ?? digitsFor(item)
  const u = unitLabel(unit ?? item?.unit)
  return (
    <span key={key} className="num flash" style={{ borderRadius: 3, padding: '0 2px' }}>
      {fmtNum(v ?? null, d)}
      {u && <span className="unit">{u}</span>}
    </span>
  )
}
