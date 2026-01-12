import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { ChartData } from '../store'
import './KLineChart.css'

interface Props {
    data: ChartData
}

export function KLineChart({ data }: Props) {
    const chartRef = useRef<HTMLDivElement>(null)
    const chartInstance = useRef<echarts.ECharts | null>(null)

    useEffect(() => {
        if (!chartRef.current) return

        // 初始化图表
        if (!chartInstance.current) {
            chartInstance.current = echarts.init(chartRef.current, 'dark')
        }

        const chart = chartInstance.current

        // 准备数据
        const dates = data.prices.map(p => p.date)
        const ohlc = data.prices.map(p => [p.open, p.close, p.low, p.high])
        const volumes = data.prices.map(p => p.volume)

        const option: echarts.EChartsOption = {
            backgroundColor: 'transparent',
            title: {
                text: `${data.name} (${data.ticker})`,
                subtext: data.prediction
                    ? `预测: ${data.prediction.target_low}% ~ ${data.prediction.target_high}% (置信度 ${data.prediction.confidence}%)`
                    : '30日走势 + T+5预测',
                left: 10,
                textStyle: { color: '#e1e4e8', fontSize: 14 },
                subtextStyle: { color: '#81c784', fontSize: 12 }
            },
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' },
                backgroundColor: '#21252b',
                borderColor: '#2d3139',
                textStyle: { color: '#e1e4e8' }
            },
            grid: [
                { left: 50, right: 20, top: 70, height: '55%' },
                { left: 50, right: 20, top: '75%', height: '15%' }
            ],
            xAxis: [
                {
                    type: 'category',
                    data: dates,
                    axisLine: { lineStyle: { color: '#2d3139' } },
                    axisLabel: { color: '#8b949e', fontSize: 10 }
                },
                {
                    type: 'category',
                    gridIndex: 1,
                    data: dates,
                    axisLine: { lineStyle: { color: '#2d3139' } },
                    axisLabel: { show: false }
                }
            ],
            yAxis: [
                {
                    type: 'value',
                    scale: true,
                    splitLine: { lineStyle: { color: '#2d3139' } },
                    axisLabel: { color: '#8b949e' }
                },
                {
                    type: 'value',
                    gridIndex: 1,
                    splitLine: { show: false },
                    axisLabel: { show: false }
                }
            ],
            series: [
                {
                    type: 'candlestick',
                    data: ohlc,
                    itemStyle: {
                        color: '#ef5350',
                        color0: '#26a69a',
                        borderColor: '#ef5350',
                        borderColor0: '#26a69a'
                    }
                },
                {
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: volumes,
                    itemStyle: { color: '#4fc3f7', opacity: 0.5 }
                }
            ],
            dataZoom: [
                {
                    type: 'inside',
                    xAxisIndex: [0, 1],
                    start: 50,
                    end: 100
                }
            ]
        }

        chart.setOption(option)

        // 响应式
        const handleResize = () => chart.resize()
        window.addEventListener('resize', handleResize)

        return () => {
            window.removeEventListener('resize', handleResize)
        }
    }, [data])

    // 清理
    useEffect(() => {
        return () => {
            chartInstance.current?.dispose()
        }
    }, [])

    return (
        <div className="kline-chart">
            <div ref={chartRef} className="chart-container" />
        </div>
    )
}
