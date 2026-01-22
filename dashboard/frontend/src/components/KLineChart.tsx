import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { ChartData } from '../store'
import './KLineChart.css'

interface Props {
    data: ChartData
    yMin?: number
    yMax?: number
    group?: string
}

export function KLineChart({ data, yMin, yMax, group }: Props) {
    const chartRef = useRef<HTMLDivElement>(null)
    const chartInstance = useRef<echarts.ECharts | null>(null)

    useEffect(() => {
        if (!chartRef.current) return

        // Defensive check: if data or prices is missing, skip rendering
        if (!data || !data.prices || data.prices.length === 0) {
            console.warn('KLineChart: No price data available', data)
            return
        }

        // 初始化图表
        if (!chartInstance.current) {
            chartInstance.current = echarts.init(chartRef.current, 'dark')
        }

        const chart = chartInstance.current

        // 设置分组以实现联动
        if (group) {
            chart.group = group
            echarts.connect(group)
        }

        // 准备历史数据 - with null safety
        const validPrices = data.prices.filter(p =>
            p && p.date &&
            typeof p.open === 'number' &&
            typeof p.close === 'number' &&
            typeof p.low === 'number' &&
            typeof p.high === 'number'
        )

        if (validPrices.length === 0) {
            console.warn('KLineChart: No valid price data after filtering', data)
            return
        }

        const dates = validPrices.map(p => p.date)
        const ohlc = validPrices.map(p => [p.open, p.close, p.low, p.high])
        const volumes = validPrices.map(p => p.volume ?? 0)

        // 准备预测数据 (如果有)
        let allDates = [...dates]
        let forecastData: any[] = []
        let baseForecastData: any[] = []

        // 合并所有可能的预测日期
        const predDates = new Set<string>()
        if (data.forecast && data.forecast.length > 0) {
            data.forecast.forEach(p => predDates.add(p.date))
        }
        if (data.forecast_base && data.forecast_base.length > 0) {
            data.forecast_base.forEach(p => predDates.add(p.date))
        }

        if (predDates.size > 0) {
            const sortedPredDates = Array.from(predDates).sort()
            const newDates = sortedPredDates.filter(d => !dates.includes(d))
            allDates = [...dates, ...newDates]

            const dateToIndex = new Map(allDates.map((d, i) => [d, i]))

            // Init empty arrays aligned with allDates using undefined which ECharts handles better than null for some series types
            // actually [NaN, NaN, NaN, NaN] is safest for candlestick
            const emptyCandle = [NaN, NaN, NaN, NaN];
            forecastData = new Array(allDates.length).fill(emptyCandle);
            baseForecastData = new Array(allDates.length).fill(emptyCandle);

            // Need to copy arrays if we want to mutate specific indices without affecting all filled references
            forecastData = forecastData.map(() => [...emptyCandle]);
            baseForecastData = baseForecastData.map(() => [...emptyCandle]);

            // Fill Adjusted Forecast
            if (data.forecast) {
                data.forecast.forEach(p => {
                    const idx = dateToIndex.get(p.date)
                    if (idx !== undefined) forecastData[idx] = [p.open, p.close, p.low, p.high]
                })
            }

            // Fill Base Forecast
            if (data.forecast_base) {
                data.forecast_base.forEach(p => {
                    const idx = dateToIndex.get(p.date)
                    if (idx !== undefined) baseForecastData[idx] = [p.open, p.close, p.low, p.high]
                })
            }
        }

        // 修正主 OHLC 数据长度
        // Use emptyCandle for missing history points
        const emptyCandle = [NaN, NaN, NaN, NaN];
        const historyData = ohlc.concat(new Array(allDates.length - dates.length).fill(emptyCandle).map(() => [...emptyCandle]))
        const allVolumes = volumes.concat(new Array(allDates.length - dates.length).fill(NaN))

        const option: echarts.EChartsOption = {
            backgroundColor: 'transparent',
            // Title moved to HTML
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' },
                backgroundColor: '#21252b',
                borderColor: '#2d3139',
                textStyle: { color: '#e1e4e8' }
            },
            legend: {
                data: ['历史走势', '模型原始预测', 'LLM调优预测'],
                top: 0,
                right: 10,
                textStyle: { color: '#8b949e', fontSize: 10 },
                itemWidth: 12,
                itemHeight: 8
            },
            grid: [
                { left: 40, right: 10, top: 25, height: '60%' },
                { left: 40, right: 10, top: '72%', height: '20%' }
            ],
            xAxis: [
                {
                    type: 'category',
                    data: allDates,
                    axisLine: { lineStyle: { color: '#2d3139' } },
                    axisLabel: { color: '#8b949e', fontSize: 10 }
                },
                {
                    type: 'category',
                    gridIndex: 1,
                    data: allDates,
                    axisLine: { lineStyle: { color: '#2d3139' } },
                    axisLabel: { show: false }
                }
            ],
            yAxis: [
                {
                    type: 'value',
                    scale: true,
                    min: yMin,
                    max: yMax,
                    splitLine: { lineStyle: { color: '#2d3139' } },
                    axisLabel: { color: '#8b949e', fontSize: 10 }
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
                    name: '历史走势',
                    type: 'candlestick',
                    data: historyData,
                    itemStyle: {
                        color: '#ef5350',
                        color0: '#26a69a',
                        borderColor: '#ef5350',
                        borderColor0: '#26a69a'
                    }
                },
                {
                    name: '模型原始预测',
                    type: 'candlestick',
                    data: baseForecastData,
                    itemStyle: {
                        // Hollow candles: use transparent fill with visible border
                        color: 'rgba(255, 140, 0, 0.1)', // Very light orange fill
                        color0: 'rgba(255, 140, 0, 0.1)',
                        borderColor: '#FF8C00', // Orange border
                        borderColor0: '#FF8C00',
                        borderWidth: 2
                    }
                },
                {
                    name: 'LLM调优预测',
                    type: 'candlestick',
                    data: forecastData,
                    itemStyle: {
                        color: '#9333ea', // 紫色 (Match visualizer)
                        color0: '#9333ea',
                        borderColor: '#9333ea',
                        borderColor0: '#9333ea',
                        opacity: 0.8
                    },
                    markLine: {
                        symbol: ['none', 'none'],
                        data: [
                            {
                                name: '预测分界',
                                xAxis: dates.length - 1, // Draw line at end of history
                                lineStyle: {
                                    color: '#eab308',
                                    type: 'dashed',
                                    width: 1
                                },
                                label: { show: false }
                            }
                        ]
                    }
                },
                {
                    name: '成交量',
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: allVolumes,
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
            <div className="chart-header-html">
                <div
                    className="stock-title"
                    onClick={() => window.open(`https://xueqiu.com/S/${data.ticker}`, '_blank')}
                    title="点击前往雪球查看详情"
                >
                    <span className="stock-name">{data.name}</span>
                    <span className="stock-code">({data.ticker})</span>
                </div>
                <div className="prediction-info">
                    {data.prediction
                        ? `预测: ${data.prediction.target_low}% ~ ${data.prediction.target_high}% (置信度 ${data.prediction.confidence}%)`
                        : '价格走势'}
                </div>
            </div>
            <div ref={chartRef} className="chart-container" />
            {data.prediction_logic && (
                <div className="prediction-logic">
                    <div className="logic-title">AI 深度预测: {data.name} ({data.ticker}) 预测逻辑</div>
                    <div className="logic-content">{data.prediction_logic}</div>
                </div>
            )}
        </div>
    )
}
