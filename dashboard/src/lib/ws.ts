import { useTwin, type WsMessage } from './store'

/** WebSocket 연결을 유지한다. 끊기면 1→2→4…10 s 간격으로 재연결하고, 서버가 보내는 스냅샷으로 상태를 복원한다. */
export function connectWs(): () => void {
  let ws: WebSocket | null = null
  let delay = 1000
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    useTwin.getState().setWs('connecting')
    ws = new WebSocket(`${proto}://${location.host}/ws`)
    ws.onopen = () => {
      delay = 1000
      useTwin.getState().setWs('open')
    }
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data as string) as WsMessage | WsMessage[]
      const apply = useTwin.getState().apply
      if (Array.isArray(data)) data.forEach(apply)
      else apply(data)
    }
    ws.onclose = () => {
      useTwin.getState().setWs('closed')
      if (stopped) return
      timer = setTimeout(open, delay)
      delay = Math.min(delay * 2, 10000)
    }
    ws.onerror = () => ws?.close()
  }
  open()
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
    ws?.close()
  }
}
