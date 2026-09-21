import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

/** 주기적으로 GET 하는 훅. interval이 0이면 한 번만 읽는다. */
export function usePoll<T>(path: string | null, interval = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)

  const load = useCallback(async () => {
    if (!path) return
    try {
      const d = await api<T>(path)
      if (alive.current) {
        setData(d)
        setError(null)
      }
    } catch (e) {
      if (alive.current) setError((e as Error).message)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [path])

  useEffect(() => {
    alive.current = true
    setLoading(true)
    load()
    if (!interval) return () => void (alive.current = false)
    const id = setInterval(load, interval)
    return () => {
      alive.current = false
      clearInterval(id)
    }
  }, [load, interval])

  return { data, error, loading, reload: load }
}

/** 1초마다 갱신되는 현재 시각. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

/** 값이 바뀔 때마다 증가하는 키 — 플래시 애니메이션 재시작용. */
export function useFlashKey(value: unknown) {
  const [key, setKey] = useState(0)
  const prev = useRef(value)
  useEffect(() => {
    if (prev.current !== value) {
      prev.current = value
      setKey((k) => k + 1)
    }
  }, [value])
  return key
}

export function readPref(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

export function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* 저장소 사용 불가 — 무시 */
  }
}
