import { Link } from 'react-router-dom'
import { AssumedBadge, Card, ErrorLine, PageTitle, Skeleton, StatusBadge } from '../components/ui'
import { Value } from '../components/Value'
import { fmtNum, PROCESS_ORDER } from '../lib/format'
import { usePoll } from '../lib/hooks'
import { useTwin } from '../lib/store'
import type { Equip } from '../lib/types'
import P from './pages.module.css'

interface Tank {
  tank: number
  target: number | null
  plan_hours: number | null
  elapsed_h: number | null
  salinity: number | null
  alarm: boolean
  sensor: string | null
  measuring: boolean
}

// 카드에 보일 대표 항목
const HEADLINE: Record<string, string[]> = {
  염도센서: ['salinity', 'tank_no'],
  온습도센서: ['temp', 'humid'],
  온도조절기: ['pv', 'sv'],
  금속검출기: ['inspect_cnt', 'ng_cnt'],
  '소독수 Interface Module': ['ppm', 'contact_min'],
  자동포장기: ['pack_count', 'running'],
  중량저울: ['weight'],
  충진기: ['speed', 'set_volume'],
  속넣기기계: ['speed', 'set_volume'],
}

/** UI-03 공정 현황: 공정 흐름 위의 장비 카드 + 절임통 8기 */
export default function Process() {
  const { data: equips, error, reload } = usePoll<Equip[]>('/api/equip', 5000)
  const { data: tanks } = usePoll<Tank[]>('/api/tanks', 3000)
  return (
    <>
      <PageTitle sub="입고/보관 → 절단/전처리 → 세척/절임 → 세척/선별 → 탈수 → 혼합(버무림) → 금속검출 → 포장/출고 → 냉장·숙성">공정 현황</PageTitle>
      <ErrorLine error={error} onRetry={reload} />
      {!equips ? (
        <Skeleton height={200} />
      ) : (
        <div className={P.flow}>
          {PROCESS_ORDER.map((proc, i) => (
            <div key={proc} className={P.proc}>
              <div className={P.procHead}>
                <span>
                  {i + 1}. {proc}
                </span>
                {i < PROCESS_ORDER.length - 1 && <span className={P.procArrow}>→</span>}
              </div>
              {equips.filter((e) => e.process === proc).map((e) => (
                <EquipCard key={e.code} e={e} />
              ))}
              {equips.every((e) => e.process !== proc) && <span className="dim" style={{ fontSize: '0.75rem' }}>수집 대상 없음</span>}
            </div>
          ))}
        </div>
      )}
      <div style={{ height: 12 }} />
      <Card title="절임통 8기" extra={<small>염도센서 2식이 4기씩 순환 측정 (가정 Q3) · 목표 ±1.0%p</small>}>
        {!tanks ? (
          <Skeleton height={140} />
        ) : (
          <div className={P.tanks}>
            {tanks.map((t) => (
              <div key={t.tank} className={t.alarm ? P.tankAlarm : P.tank} data-testid={`tank-${t.tank}`}>
                <span className={P.tankNo}>
                  {t.tank}번 통 {t.measuring && <span style={{ color: 'var(--accent)' }} title="측정 중">●</span>}
                </span>
                <span className="dim">{t.sensor}</span>
                <span>
                  현재 <b className="num">{fmtNum(t.salinity, 2)}</b>
                  <span className="unit">%</span>
                </span>
                <span className="dim">목표 {fmtNum(t.target, 0)}%</span>
                <span className="dim">
                  경과 <span className="num">{fmtNum(t.elapsed_h, 1)}</span>h / {fmtNum(t.plan_hours, 0)}h
                </span>
                {t.alarm ? <span style={{ color: 'var(--delay)' }}>▲ 기준 이탈</span> : <span />}
                <div className={P.bar}>
                  <span style={{ width: `${Math.min(100, ((t.elapsed_h ?? 0) / (t.plan_hours || 1)) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  )
}

function EquipCard({ e }: { e: Equip }) {
  const status = useTwin((s) => s.status[e.code]) ?? e.status
  const live = useTwin((s) => s.values[e.code]?.values)
  const values = { ...e.values, ...(live ?? {}) }
  const keys = HEADLINE[e.type] ?? e.items.slice(0, 2).map((i) => i.key)
  const bad = status !== 'OK'
  return (
    <Link to={`/equip/${e.code}`} className={bad ? P.equipBad : P.equipCard} data-testid={`card-${e.code}`}>
      <div className={P.equipTop}>
        <span className={P.code}>{e.code}</span>
        <StatusBadge status={status} compact />
      </div>
      <span className="dim" style={{ fontSize: '0.75rem' }}>
        {e.name} <AssumedBadge items={e.assumed} />
      </span>
      {keys.map((k) => {
        const it = e.items.find((i) => i.key === k)
        if (!it) return null
        const v = values[k]
        const text = k === 'running' ? (v ? '가동' : '정지') : undefined
        return (
          <span key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="dim">{it.name}</span>
            {text ? <b>{text}</b> : <Value v={v} item={it} />}
          </span>
        )
      })}
    </Link>
  )
}
