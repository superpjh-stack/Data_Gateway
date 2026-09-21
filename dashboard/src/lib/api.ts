/** REST 호출. 실패하면 서버 메시지를 담은 Error를 던진다. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* 본문 없음 */
    }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })
