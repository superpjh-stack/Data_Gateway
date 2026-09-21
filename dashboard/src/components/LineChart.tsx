import ReactECharts from 'echarts-for-react'
import { useMemo } from 'react'

export interface Series {
  name: string
  data: [number, number][]
  unit?: string
}

function cssVar(name: string, fallback: string) {
  if (typeof window === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

// 계열 색은 상태색(초록·노랑·빨강·보라)과 겹치지 않는 파랑·청록 계열 위주로 고른다
const PALETTE = ['#58A6FF', '#39C5CF', '#DB61A2', '#E3B341', '#8B949E']

/** 시계열 라인 차트. 기준선(limits)은 점선으로 그린다. */
export function LineChart({ series, height = 260, limits = [], theme }: {
  series: Series[]
  height?: number
  limits?: { value: number; label: string }[]
  theme?: string
}) {
  const option = useMemo(() => {
    const text = cssVar('--text-dim', '#8a96a3')
    const border = cssVar('--border', '#2a333d')
    return {
      animation: false,
      color: PALETTE,
      grid: { left: 48, right: 16, top: 28, bottom: 28 },
      legend: { top: 0, textStyle: { color: text }, icon: 'roundRect', itemWidth: 12, itemHeight: 4 },
      tooltip: { trigger: 'axis', valueFormatter: (v: number) => (typeof v === 'number' ? v.toLocaleString('ko-KR') : v) },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: border } },
        axisLabel: { color: text, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: text },
        splitLine: { lineStyle: { color: border, opacity: 0.6 } },
      },
      series: series.map((s, i) => ({
        name: s.unit ? `${s.name} (${s.unit})` : s.name,
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 1.6 },
        data: s.data,
        markLine:
          i === 0 && limits.length
            ? {
                symbol: 'none',
                silent: true,
                lineStyle: { type: 'dashed', color: text },
                label: { color: text, formatter: '{b}' },
                data: limits.map((l) => ({ yAxis: l.value, name: l.label })),
              }
            : undefined,
      })),
    }
    // theme은 CSS 변수 재조회를 위한 의존성
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, limits, theme])
  return <ReactECharts option={option} style={{ height }} notMerge lazyUpdate />
}
