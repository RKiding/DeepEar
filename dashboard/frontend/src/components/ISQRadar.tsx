import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

interface Props {
  sentiment: number
  confidence: number
  intensity: number
  expectationGap: number
  timeliness: number
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

export const ISQRadar = ({ sentiment, confidence, intensity, expectationGap, timeliness }: Props) => {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current) return

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, 'dark')
    }

    const chart = chartInstance.current

    const normalizedSentiment = clamp((sentiment + 1) / 2, 0, 1)
    const normalizedIntensity = clamp(intensity / 5, 0, 1)

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      radar: {
        indicator: [
          { name: '情绪', max: 1 },
          { name: '确定性', max: 1 },
          { name: '强度', max: 1 },
          { name: '预期差', max: 1 },
          { name: '时效', max: 1 }
        ],
        radius: 55,
        axisName: { color: '#94A3B8', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.2)' } },
        splitArea: { areaStyle: { color: ['rgba(15, 23, 42, 0.2)'] } },
        axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.3)' } }
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: [
                normalizedSentiment,
                clamp(confidence, 0, 1),
                normalizedIntensity,
                clamp(expectationGap, 0, 1),
                clamp(timeliness, 0, 1)
              ],
              areaStyle: { color: 'rgba(139, 92, 246, 0.35)' },
              lineStyle: { color: '#8B5CF6' },
              symbolSize: 4
            }
          ]
        }
      ]
    }

    chart.setOption(option)

    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [sentiment, confidence, intensity, expectationGap, timeliness])

  useEffect(() => () => chartInstance.current?.dispose(), [])

  return <div className="isq-radar" ref={chartRef} />
}
