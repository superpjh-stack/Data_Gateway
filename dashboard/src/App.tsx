import { useEffect } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { connectWs } from './lib/ws'
import Alarms from './pages/Alarms'
import Collection from './pages/Collection'
import EdgeBuffer from './pages/EdgeBuffer'
import EquipDetail from './pages/EquipDetail'
import Kiosk from './pages/Kiosk'
import Overview from './pages/Overview'
import PlcMemory from './pages/PlcMemory'
import Process from './pages/Process'
import RawLedger from './pages/RawLedger'
import Simulation from './pages/Simulation'

export default function App() {
  useEffect(() => connectWs(), [])
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/kiosk" element={<Kiosk />} />
        <Route
          path="*"
          element={
            <Layout>
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/process" element={<Process />} />
                <Route path="/collection" element={<Collection />} />
                <Route path="/equip/:code" element={<EquipDetail />} />
                <Route path="/plc" element={<PlcMemory />} />
                <Route path="/edge" element={<EdgeBuffer />} />
                <Route path="/raw" element={<RawLedger />} />
                <Route path="/alarms" element={<Alarms />} />
                <Route path="/sim" element={<Simulation />} />
                <Route path="*" element={<div className="dim">페이지를 찾을 수 없습니다</div>} />
              </Routes>
            </Layout>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
