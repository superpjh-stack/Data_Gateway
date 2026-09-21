import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { post } from '../lib/api'
import { fmtPct, hms, SEVERITY_LABEL } from '../lib/format'
import { readPref, useNow, writePref } from '../lib/hooks'
import { activeAlarms, useTwin } from '../lib/store'
import L from './Layout.module.css'
import { ui } from './ui'

const NAV = [
  { to: '/', icon: '◎', label: '개요' },
  { to: '/process', icon: '▤', label: '공정' },
  { to: '/collection', icon: '≡', label: '수집현황' },
  { to: '/plc', icon: '▦', label: 'PLC 메모리' },
  { to: '/edge', icon: '⇅', label: 'Edge 버퍼' },
  { to: '/raw', icon: '☰', label: '수집원장' },
  { to: '/alarms', icon: '!', label: '알람' },
  { to: '/sim', icon: '⚙', label: '시뮬레이션' },
]

function TopBar() {
  const summary = useTwin((st) => st.summary)
  const ws = useTwin((st) => st.ws)
  const now = useNow()
  const okColor = summary && summary.ok < summary.total ? 'var(--delay)' : 'var(--ok)'
  const mesOk = summary?.mes_link === 'OK'
  return (
    <header className={L.top}>
      <div className={L.brand}>
        임진강김치 수집 트윈 <small>PLC 데이터수집 디지털 트윈</small>
      </div>
      <div className={L.kpis} aria-live="polite">
        <div className={L.topKpi}>
          <span>정상 장비</span>
          <b style={{ color: okColor }} data-testid="kpi-ok">
            {summary ? `${summary.ok}/${summary.total}` : '—'}
          </b>
        </div>
        <div className={L.topKpi}>
          <span>수집 성공률(1분)</span>
          <b>{fmtPct(summary?.success_rate)}</b>
        </div>
        <div className={L.topKpi}>
          <span>Edge 버퍼</span>
          <b style={{ color: summary?.buffer_pending ? 'var(--delay)' : undefined }}>{summary?.buffer_pending ?? '—'}</b>
        </div>
        <div className={L.topKpi}>
          <span>활성 알람</span>
          <b style={{ color: summary?.active_alarms ? 'var(--down)' : undefined }}>{summary?.active_alarms ?? '—'}</b>
        </div>
        <div className={L.topKpi}>
          <span>MES 연결</span>
          <b style={{ color: mesOk ? 'var(--ok)' : 'var(--down)' }}>{mesOk ? '● 정상' : summary ? '✕ 끊김' : '—'}</b>
        </div>
        <div className={L.topKpi}>
          <span>실시간</span>
          <b style={{ color: ws === 'open' ? 'var(--ok)' : 'var(--down)' }} data-testid="ws-state">
            {ws === 'open' ? '● 연결' : ws === 'connecting' ? '… 연결 중' : '✕ 재연결 중'}
          </b>
        </div>
      </div>
      <span className={L.clock}>{hms(new Date(now))}</span>
    </header>
  )
}

function AlarmBanner() {
  const alarms = useTwin((st) => st.alarms)
  const lastId = useTwin((st) => st.lastAlarmId)
  const nav = useNavigate()
  const active = activeAlarms(alarms).filter((a) => a.state === 'RAISED')
  if (!active.length) return null
  const top = [...active].sort((a, b) => sev(b.severity) - sev(a.severity) || b.alarm_id - a.alarm_id)[0]
  return (
    <div key={lastId ?? 0} className={`${L.banner} ${L.bannerPulse}`} role="alert">
      <b style={{ color: 'var(--down)' }}>✕ {SEVERITY_LABEL[top.severity]}</b>
      <span className={L.bannerMsg}>
        <b>{top.equip_code}</b> {top.message}
      </span>
      {active.length > 1 && <span className={L.bannerMore}>외 {active.length - 1}건</span>}
      <button className={ui.btn} onClick={() => post(`/api/alarms/${top.alarm_id}/ack`)}>
        확인
      </button>
      <button className={ui.btn} onClick={() => nav('/alarms')}>
        알람 보기
      </button>
    </div>
  )
}

function sev(s: string) {
  return { LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3 }[s] ?? 0
}

export function useTheme() {
  const [theme, setTheme] = useState(() => readPref('twin.theme', 'dark'))
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    writePref('twin.theme', theme)
  }, [theme])
  return [theme, setTheme] as const
}

export function Layout({ children, kiosk = false }: { children: ReactNode; kiosk?: boolean }) {
  const [theme, setTheme] = useTheme()
  return (
    <div className={`${L.shell} ${kiosk ? L.kiosk : ''}`}>
      <TopBar />
      {!kiosk && (
        <nav className={L.side} aria-label="주 메뉴">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => (isActive ? L.active : L.navLink)}>
              <span className={L.navIcon} aria-hidden>
                {n.icon}
              </span>
              <span className={L.navLabel}>{n.label}</span>
            </NavLink>
          ))}
          <div className={L.sideFoot}>
            <NavLink to="/kiosk" className={L.navLink}>
              <span className={L.navIcon}>⛶</span>
              <span className={L.navLabel}>현황판 모드</span>
            </NavLink>
            <button className={ui.btn} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label="테마 전환">
              ◐ <span>{theme === 'dark' ? '라이트 테마' : '다크 테마'}</span>
            </button>
          </div>
        </nav>
      )}
      <main className={L.main}>
        <AlarmBanner />
        {children}
      </main>
    </div>
  )
}
