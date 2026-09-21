import { useMemo, useState } from 'react'
import { Card, ErrorLine, PageTitle, ui } from '../components/ui'
import { del, post } from '../lib/api'
import { fmtDuration } from '../lib/format'
import { usePoll } from '../lib/hooks'
import type { Fault, FaultType } from '../lib/types'
import P from './pages.module.css'

/** UI-10 시뮬레이션 제어: 고장 주입 · 시나리오 프리셋 · 활성 고장 */
export default function Simulation() {
  const { data: catalog } = usePoll<FaultType[]>('/api/sim/catalog')
  const { data: scenarios } = usePoll<Record<string, unknown[]>>('/api/sim/scenarios')
  const { data: faults, reload } = usePoll<Fault[]>('/api/sim/faults', 1000)
  const [type, setType] = useState('value_spike')
  const [targetSel, setTarget] = useState('')
  const [keySel, setKey] = useState('')
  const [value, setValue] = useState('8.5')
  const [ms, setMs] = useState('200')
  const [ratio, setRatio] = useState('0.3')
  const [dur, setDur] = useState('60')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const spec = useMemo(() => catalog?.find((c) => c.type === type), [catalog, type])
  // 유형이 바뀌면 대상·항목 선택을 유효한 값으로 맞춘다 (렌더 중 계산)
  const target = spec && spec.targets.includes(targetSel) ? targetSel : (spec?.targets[0] ?? '')
  const keys = spec?.keys?.[target] ?? []
  const key = keys.includes(keySel) ? keySel : (keys[0] ?? '')

  const apply = async () => {
    setErr(null)
    const params: Record<string, unknown> = {}
    if (spec?.params.includes('key')) params.key = key
    if (spec?.params.includes('value')) params.value = Number(value)
    if (spec?.params.includes('ms')) params.ms = Number(ms)
    if (spec?.params.includes('ratio')) params.ratio = Number(ratio)
    try {
      await post('/api/sim/faults', { target, type, params, duration_s: spec?.instant || !dur ? null : Number(dur) })
      setMsg(`${spec?.label} → ${target} 적용`)
      reload()
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  const run = async (name: string) => {
    await post(`/api/sim/scenarios/${encodeURIComponent(name)}/run`)
    setMsg(`시나리오 "${name}" 실행`)
    setTimeout(reload, 300)
  }
  const remove = async (id: string) => {
    await del(`/api/sim/faults/${id}`)
    reload()
  }
  return (
    <>
      <PageTitle sub="장애를 주입해 수집 경로가 어떻게 반응하는지 확인합니다. 설비로 쓰기 명령은 보내지 않습니다.">시뮬레이션 제어</PageTitle>
      <ErrorLine error={err} />
      <div className={P.stack}>
        <Card title="고장 주입">
          <div className={P.form}>
            <label className={P.field}>
              유형
              <select className={ui.input} value={type} onChange={(e) => setType(e.target.value)}>
                {(catalog ?? []).map((c) => (
                  <option key={c.type} value={c.type}>{c.label} ({c.type})</option>
                ))}
              </select>
            </label>
            <label className={P.field}>
              대상
              <select className={ui.input} value={target} onChange={(e) => setTarget(e.target.value)}>
                {(spec?.targets ?? []).map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            {spec?.params.includes('key') && (
              <label className={P.field}>
                항목
                <select className={ui.input} value={key} onChange={(e) => setKey(e.target.value)}>
                  {keys.map((k) => <option key={k}>{k}</option>)}
                </select>
              </label>
            )}
            {spec?.params.includes('value') && (
              <label className={P.field}>
                값
                <input className={ui.input} style={{ width: 90 }} value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" />
              </label>
            )}
            {spec?.params.includes('ms') && (
              <label className={P.field}>
                지연(ms)
                <input className={ui.input} style={{ width: 90 }} value={ms} onChange={(e) => setMs(e.target.value)} inputMode="numeric" />
              </label>
            )}
            {spec?.params.includes('ratio') && (
              <label className={P.field}>
                비율(0~1)
                <input className={ui.input} style={{ width: 90 }} value={ratio} onChange={(e) => setRatio(e.target.value)} inputMode="decimal" />
              </label>
            )}
            {!spec?.instant && (
              <label className={P.field}>
                지속(초, 비우면 무기한)
                <input className={ui.input} style={{ width: 110 }} value={dur} onChange={(e) => setDur(e.target.value)} inputMode="numeric" />
              </label>
            )}
            <button className={ui.btnPrimary} onClick={apply} disabled={!target}>
              {spec?.instant ? '실행' : '적용'}
            </button>
          </div>
          {msg && <div className="dim" style={{ marginTop: 8 }}>✓ {msg}</div>}
        </Card>
        <Card title="시나리오 프리셋" extra={<small>config/scenarios.yaml</small>}>
          <div className={P.presets}>
            {Object.keys(scenarios ?? {}).map((name) => (
              <button key={name} className={ui.btn} onClick={() => run(name)}>{name}</button>
            ))}
          </div>
        </Card>
        <Card title="활성 고장" extra={faults?.length ? <button className={ui.btnDanger} onClick={async () => { await del('/api/sim/faults'); reload() }}>모두 해제</button> : undefined}>
          {!faults?.length ? (
            <span className="dim">주입된 고장이 없습니다</span>
          ) : (
            faults.map((f) => (
              <div key={f.id} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border)' }} data-testid="active-fault">
                <span className="num dim">{f.id}</span>
                <b className="num">{f.target}</b>
                <span>{f.label}</span>
                <span className="num dim">{Object.entries(f.params).map(([k, v]) => `${k}=${v}`).join(' ')}</span>
                <span className="num" style={{ marginLeft: 'auto' }}>남은 {fmtDuration(f.remaining_s)}</span>
                <button className={ui.btn} onClick={() => remove(f.id)}>해제</button>
              </div>
            ))
          )}
        </Card>
      </div>
    </>
  )
}
