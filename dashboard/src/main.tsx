import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/600.css'
import './styles/global.css'
import App from './App'

try {
  document.documentElement.dataset.theme = localStorage.getItem('twin.theme') ?? 'dark'
} catch {
  document.documentElement.dataset.theme = 'dark'
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
