import { Topology } from '../components/Topology'
import { Card, PageTitle, Skeleton, StatusBadge } from '../components/ui'
import { fmtPct, fmtTime, STATUS_META } from '../lib/format'
import { activeAlarms, useTwin } from '../lib/store'
import type { Status } from '../lib/types'
import P from './pages.module.css'

/** 개요: UI-02 수집 토폴로지 + 상태 분포·PLC·최근 알람 */
export default function Overview() {
  const topo = useTwin((s) => s.topology)
  const summary = useTwin((s) => s.summary)
  const alarms = useTwin((s) => s.alarms)
  const recent = activeAlarms(alarms).slice(0, 5)
  return (
    <>
      <PageTitle sub="센서 → RS-485 버스 → PLC Master/Slave → Edge Collector → MES">수집 토폴로지</PageTitle>
      <div className={P.twoCol}>
        <Card>{topo ? <Topology topo={topo} /> : <Skeleton height={600} />}</Card>
        <div className={P.stack}>
          <Card title="장비 상태 분포">
            <div className={P.statusList}>
              {(Object.keys(STATUS_META) as Status[])
                .filter((k) => summary?.by_status?.[k])
                .map((k) => (
                  <Row key={k} label={<StatusBadge status={k} />} value={summary?.by_status[k] ?? 0} />
                ))}
              <Row label="1분 수집 성공률" value={fmtPct(summary?.success_rate)} />
              <Row label="활성 고장 주입" value={summary?.faults ?? 0} />
            </div>
          </Card>
          <Card title="PLC 제어반" extra={<small>LS산전 XBC-DN32H</small>}>
            <div className={P.statusList}>
              {Object.entries(summary?.plcs ?? {}).map(([id, st]) => (
                <Row key={id} label={id === 'MASTER' ? 'Master (세척·절임·냉장)' : 'Slave (절단/전처리)'} value={<StatusBadge status={st} />} />
              ))}
              <Row label="Edge → MES" value={<StatusBadge status={summary?.mes_link === 'OK' ? 'OK' : 'DOWN'} />} />
            </div>
          </Card>
          <Card title="활성 알람" extra={<small>{recent.length}건</small>}>
            {recent.length === 0 ? (
              <div className="dim">활성 알람이 없습니다</div>
            ) : (
              recent.map((a) => (
                <div key={a.alarm_id} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: '0.85rem' }}>
                  <span className="num dim">{fmtTime(a.raised_dt)}</span> <b>{a.equip_code}</b> {a.message}
                </div>
              ))
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <>
      <span>{label}</span>
      <span className="num" style={{ textAlign: 'right' }}>
        {value}
      </span>
    </>
  )
}
