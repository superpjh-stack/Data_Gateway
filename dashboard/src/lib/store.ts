import { create } from 'zustand'
import type { Alarm, BufferStats, Status, Summary, Topology, ValueMsg } from './types'

export type WsState = 'connecting' | 'open' | 'closed'

interface BufferPoint {
  t: number
  pending: number
}

export interface TwinState {
  ws: WsState
  summary: Summary | null
  topology: Topology | null
  alarms: Record<number, Alarm>
  values: Record<string, ValueMsg>
  valueAt: Record<string, number>
  status: Record<string, Status>
  buffer: (BufferStats & { mes_link?: string }) | null
  bufferHistory: BufferPoint[]
  lastAlarmId: number | null
  setWs: (s: WsState) => void
  apply: (msg: WsMessage) => void
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WsMessage = { type: string; [k: string]: any }

const HISTORY_MS = 10 * 60 * 1000

export function reduce(state: TwinState, msg: WsMessage): Partial<TwinState> {
  switch (msg.type) {
    case 'snapshot': {
      const alarms: Record<number, Alarm> = {}
      for (const a of msg.alarms as Alarm[]) alarms[a.alarm_id] = a
      const values: Record<string, ValueMsg> = {}
      for (const [code, v] of Object.entries(msg.values as Record<string, ValueMsg>)) values[code] = v
      const status: Record<string, Status> = {}
      for (const n of (msg.topology as Topology).nodes) if (n.kind === 'device') status[n.id] = n.status
      return { summary: msg.summary, topology: msg.topology, alarms, values, status }
    }
    case 'summary': {
      const { type: _t, ...rest } = msg
      return { summary: rest as Summary }
    }
    case 'topology':
      return { topology: { nodes: msg.nodes, links: msg.links } }
    case 'equip_status':
      return { status: { ...state.status, [msg.equip]: msg.status } }
    case 'value': {
      const prev = state.values[msg.equip]?.values ?? {}
      const { type: _t, equip, ...rest } = msg
      return {
        values: { ...state.values, [equip]: { ...rest, values: { ...prev, ...msg.values } } as ValueMsg },
        valueAt: { ...state.valueAt, [equip]: Date.now() },
      }
    }
    case 'alarm': {
      const { type: _t, ...a } = msg
      const isNew = !state.alarms[a.alarm_id] && a.state === 'RAISED'
      return { alarms: { ...state.alarms, [a.alarm_id]: a as Alarm }, lastAlarmId: isNew ? a.alarm_id : state.lastAlarmId }
    }
    case 'edge_buffer': {
      const now = Date.now()
      const hist = [...state.bufferHistory.filter((p) => now - p.t < HISTORY_MS), { t: now, pending: msg.pending_items }]
      const { type: _t, ...rest } = msg
      return { buffer: rest as BufferStats, bufferHistory: hist }
    }
    default:
      return {}
  }
}

export const useTwin = create<TwinState>((set, get) => ({
  ws: 'connecting',
  summary: null,
  topology: null,
  alarms: {},
  values: {},
  valueAt: {},
  status: {},
  buffer: null,
  bufferHistory: [],
  lastAlarmId: null,
  setWs: (ws) => set({ ws }),
  apply: (msg) => set(reduce(get(), msg)),
}))

export function activeAlarms(alarms: Record<number, Alarm>): Alarm[] {
  return Object.values(alarms)
    .filter((a) => a.state !== 'CLEARED')
    .sort((a, b) => b.alarm_id - a.alarm_id)
}
