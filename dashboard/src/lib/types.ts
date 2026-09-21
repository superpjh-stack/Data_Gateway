export type Status = 'OK' | 'DELAY' | 'DOWN' | 'ERROR' | 'STALE' | 'INACTIVE' | 'UNKNOWN'

export interface Diag {
  status: Status
  success_1m: number | null
  success_1h: number | null
  avg_rtt_ms: number | null
  last_ok: string | null
  consecutive_fail: number
  errors: Record<string, number>
  polls_1m: number
}

export interface ItemDef {
  key: string
  name: string
  unit: string
  reg: string | null
  node: string | null
  type: string
  scale: number
  data_type: string
}

export interface Equip {
  code: string
  name: string
  process: string
  type: string
  model: string | null
  comm_type: string
  kind: string
  poll_ms: number
  status: Status
  diag: Diag | null
  values: Record<string, number>
  last_ts: string | null
  extra: Record<string, unknown>
  assumed: string[]
  items: ItemDef[]
  target: string
  parent: string
  plc: string | null
  label: string
  plc_block: string | null
}

export interface Summary {
  total: number
  ok: number
  by_status: Record<string, number>
  success_rate: number | null
  buffer_pending: number
  active_alarms: number
  mes_link: string
  plcs: Record<string, string>
  faults: number
  uptime_s: number
}

export interface TopoNode {
  id: string
  kind: 'device' | 'bus' | 'plc' | 'edge' | 'mes'
  label: string
  name: string
  status: Status
  process?: string
  comm?: string
}

export interface TopoLink {
  from: string
  to: string
  status: Status
  comm: string
  kind?: string
}

export interface Topology {
  nodes: TopoNode[]
  links: TopoLink[]
}

export interface Alarm {
  alarm_id: number
  category: 'CCP' | 'COMM'
  rule_id: string
  item: string
  equip_code: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  message: string
  value: string | null
  value_key: string | null
  state: 'RAISED' | 'ACKED' | 'CLEARED'
  raised_dt: string
  acked_dt: string | null
  cleared_dt: string | null
}

export interface BufferStats {
  pending_samples: number
  pending_items: number
  oldest: string | null
  sent_total: number
  resent_total: number
  purged_total: number
  seq: number
}

export interface Fault {
  id: string
  target: string
  type: string
  label: string
  params: Record<string, unknown>
  remaining_s: number | null
}

export interface FaultType {
  type: string
  label: string
  params: string[]
  targets: string[]
  instant: boolean
  keys?: Record<string, string[]>
}

export interface CcpRule {
  id: string
  item: string
  equip: string[]
  key: string
  low: number | null
  high: number | null
  band: number | null
  band_pct: number | null
  std: number | null
  ng_immediate: boolean
  unit: string
  hold_sec: number
  severity: string
  basis: string
}

export interface ValueMsg {
  values: Record<string, number>
  ts: string
  [k: string]: unknown
}
