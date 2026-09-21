import { useEffect, useState } from 'react'
import { Layout } from '../components/Layout'
import Alarms from './Alarms'
import Overview from './Overview'
import Process from './Process'

const VIEWS = [
  { name: '수집 토폴로지', el: <Overview /> },
  { name: '공정 현황', el: <Process /> },
  { name: '알람', el: <Alarms /> },
]

/** 현황판(65인치) 모드: UI-02 → UI-03 → UI-09를 15초씩 순환 */
export default function Kiosk() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setI((x) => (x + 1) % VIEWS.length), 15000)
    return () => clearInterval(id)
  }, [])
  return (
    <Layout kiosk>
      <div className="dim" style={{ fontSize: '0.8rem', marginBottom: 6 }}>
        현황판 순환 {i + 1}/{VIEWS.length} · {VIEWS[i].name} · <a href="/">나가기</a>
      </div>
      {VIEWS[i].el}
    </Layout>
  )
}
