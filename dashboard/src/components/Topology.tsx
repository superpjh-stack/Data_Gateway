import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { statusMeta } from '../lib/format'
import type { TopoNode, Topology as Topo } from '../lib/types'

const ROW = 30
const COLS = { device: 20, bus: 330, plc: 520, edge: 720, mes: 900 }
const W = 1020
const NODE_W = { device: 190, bus: 110, plc: 130, edge: 130, mes: 100 }

interface Placed extends TopoNode {
  x: number
  y: number
  w: number
}

/** 수집 토폴로지(UI-02): 센서 → 버스 → PLC → Edge → MES. 링크 색은 출발 쪽 상태를 따른다. */
export function Topology({ topo, compact = false }: { topo: Topo; compact?: boolean }) {
  const nav = useNavigate()
  const layout = useMemo(() => place(topo), [topo])
  const h = layout.height
  return (
    <svg viewBox={`0 0 ${W} ${h}`} width="100%" role="img" aria-label="수집 토폴로지" style={{ maxHeight: compact ? '78vh' : undefined }}>
      {topo.links.map((lk) => {
        const a = layout.byId[lk.from]
        const b = layout.byId[lk.to]
        if (!a || !b) return null
        const aux = lk.kind === 'aux'
        const color = statusMeta(lk.status).color
        const x1 = aux ? a.x + a.w / 2 : a.x + a.w
        const y1 = aux ? a.y - 12 : a.y
        const x2 = aux ? b.x + b.w / 2 : b.x
        const y2 = aux ? b.y + 12 : b.y
        const mx = (x1 + x2) / 2
        const d = aux ? `M${x1},${y1} L${x2},${y2}` : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
        const bad = lk.status !== 'OK'
        return (
          <g key={`${lk.from}-${lk.to}`}>
            <path d={d} fill="none" stroke={color} strokeWidth={bad ? 2.2 : 1.2} strokeDasharray={aux || lk.status === 'STALE' ? '4 4' : undefined} opacity={bad ? 1 : 0.55} />
            {aux && (
              <text x={x1 + 6} y={(y1 + y2) / 2} fontSize={10} fill="var(--text-dim)">
                하트비트 D0902
              </text>
            )}
          </g>
        )
      })}
      {layout.nodes.map((n) => {
        const m = statusMeta(n.status)
        const bad = n.status !== 'OK'
        return (
          <g
            key={n.id}
            transform={`translate(${n.x},${n.y - 11})`}
            style={{ cursor: n.kind === 'device' ? 'pointer' : 'default' }}
            onClick={n.kind === 'device' ? () => nav(`/equip/${n.id}`) : undefined}
            tabIndex={n.kind === 'device' ? 0 : undefined}
            onKeyDown={n.kind === 'device' ? (e) => e.key === 'Enter' && nav(`/equip/${n.id}`) : undefined}
            role={n.kind === 'device' ? 'link' : undefined}
            aria-label={`${n.label} ${n.name} ${m.label}`}
            data-node={n.id}
            data-status={n.status}
          >
            <rect width={n.w} height={22} rx={5} fill="var(--surface)" stroke={bad ? m.color : 'var(--border)'} strokeWidth={bad ? 1.6 : 1} />
            <text x={8} y={15} fontSize={11} fill={m.color}>
              {m.icon}
            </text>
            <text x={22} y={15} fontSize={11} fontFamily="var(--mono)" fill="var(--text)" fontWeight={600}>
              {n.label}
            </text>
            {n.kind === 'device' && (
              <text x={86} y={15} fontSize={10} fill="var(--text-dim)">
                {truncate(n.name, 13)}
              </text>
            )}
            {n.kind !== 'device' && n.kind !== 'bus' && (
              <text x={n.w - 6} y={15} fontSize={10} fill={m.color} textAnchor="end">
                {m.label}
              </text>
            )}
          </g>
        )
      })}
      {['센서·설비', '버스·연결', 'PLC 제어반', 'Edge', 'MES'].map((t, i) => (
        <text key={t} x={[COLS.device, COLS.bus, COLS.plc, COLS.edge, COLS.mes][i]} y={14} fontSize={11} fill="var(--text-dim)">
          {t}
        </text>
      ))}
    </svg>
  )
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function place(topo: Topo) {
  const byId: Record<string, Placed> = {}
  const parentOf: Record<string, string> = {}
  for (const lk of topo.links) if (!lk.kind) parentOf[lk.from] = lk.to
  const devices = topo.nodes.filter((n) => n.kind === 'device')
  const buses = topo.nodes.filter((n) => n.kind === 'bus')
  const plcs = topo.nodes.filter((n) => n.kind === 'plc')
  // 장비는 부모(버스 → PLC 순) 기준으로 묶어 세로로 쌓는다
  const groupOrder = [...buses.map((b) => b.id), 'EDGE']
  const plcOrder = plcs.map((p) => p.id)
  groupOrder.sort((a, b) => rank(parentOf[a], plcOrder) - rank(parentOf[b], plcOrder))
  let y = 34
  for (const g of groupOrder) {
    const kids = devices.filter((d) => parentOf[d.id] === g)
    for (const d of kids) {
      byId[d.id] = { ...d, x: COLS.device, y, w: NODE_W.device }
      y += ROW
    }
    y += 8
  }
  const height = y + 10
  const avg = (ids: string[]) => {
    const ys = ids.map((i) => byId[i]?.y).filter((v): v is number => v !== undefined)
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : height / 2
  }
  for (const b of buses) {
    byId[b.id] = { ...b, x: COLS.bus, y: avg(devices.filter((d) => parentOf[d.id] === b.id).map((d) => d.id)), w: NODE_W.bus }
  }
  for (const p of plcs) {
    byId[p.id] = { ...p, x: COLS.plc, y: avg(buses.filter((b) => parentOf[b.id] === p.id).map((b) => b.id)), w: NODE_W.plc }
  }
  const mid = height / 2
  for (const n of topo.nodes) {
    if (n.kind === 'edge') byId[n.id] = { ...n, x: COLS.edge, y: mid, w: NODE_W.edge }
    if (n.kind === 'mes') byId[n.id] = { ...n, x: COLS.mes, y: mid, w: NODE_W.mes }
  }
  return { byId, nodes: Object.values(byId), height }
}

function rank(plc: string | undefined, order: string[]) {
  const i = plc ? order.indexOf(plc) : -1
  return i < 0 ? 99 : i
}
