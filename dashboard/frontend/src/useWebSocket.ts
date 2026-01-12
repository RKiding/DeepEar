import { useEffect, useRef, useCallback } from 'react'
import { useDashboardStore } from './store'

const WS_URL = import.meta.env.DEV
    ? 'ws://localhost:8765/ws'
    : `ws://${window.location.host}/ws`

export function useWebSocket() {
    const wsRef = useRef<WebSocket | null>(null)
    const reconnectTimeoutRef = useRef<number | null>(null)

    const {
        setConnected,
        setRunning,
        setCompleted,
        setFailed,
        addStep,
        addSignal,
        updateChart,
        updateGraph,
        updateProgress,
        setHistory,
        setQueryGroups
    } = useDashboardStore()

    const connect = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return

        const ws = new WebSocket(WS_URL)
        wsRef.current = ws

        ws.onopen = () => {
            console.log('✅ WebSocket connected')
            setConnected(true)

            // 请求初始数据
            ws.send(JSON.stringify({ command: 'get_history' }))
            ws.send(JSON.stringify({ command: 'get_query_groups' }))
        }

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data)
                handleMessage(msg)
            } catch (e) {
                console.error('Failed to parse message:', e)
            }
        }

        ws.onclose = () => {
            console.log('❌ WebSocket disconnected')
            setConnected(false)

            // 自动重连
            reconnectTimeoutRef.current = window.setTimeout(() => {
                console.log('🔄 Attempting to reconnect...')
                connect()
            }, 3000)
        }

        ws.onerror = (error) => {
            console.error('WebSocket error:', error)
        }
    }, [setConnected])

    const handleMessage = (msg: { type: string; data: any }) => {
        switch (msg.type) {
            case 'init':
                if (msg.data.run_id && msg.data.status === 'running') {
                    setRunning(msg.data.run_id)
                    msg.data.steps?.forEach((step: any) => addStep(step))
                    msg.data.signals?.forEach((signal: any) => addSignal(signal))
                    Object.entries(msg.data.charts || {}).forEach(([ticker, data]) => {
                        updateChart(ticker, data as any)
                    })
                    if (msg.data.graph) updateGraph(msg.data.graph)
                }
                break

            case 'progress':
                updateProgress(msg.data.phase, msg.data.progress)
                break

            case 'step':
                addStep(msg.data)
                break

            case 'signal':
                addSignal(msg.data)
                break

            case 'chart':
                updateChart(msg.data.ticker, msg.data)
                break

            case 'graph':
                updateGraph(msg.data)
                break

            case 'completed':
                setCompleted()
                // 刷新历史
                wsRef.current?.send(JSON.stringify({ command: 'get_history' }))
                wsRef.current?.send(JSON.stringify({ command: 'get_query_groups' }))
                // 浏览器通知
                if (Notification.permission === 'granted') {
                    new Notification('SignalFlux 分析完成', {
                        body: `发现 ${msg.data.signal_count} 个信号`,
                        icon: '/favicon.ico'
                    })
                }
                break

            case 'error':
                setFailed(msg.data.message)
                break

            case 'history':
                setHistory(msg.data)
                break

            case 'query_groups':
                setQueryGroups(msg.data)
                break
        }
    }

    const sendCommand = useCallback((command: string, data?: any) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ command, ...data }))
        }
    }, [])

    useEffect(() => {
        connect()

        // 请求通知权限
        if (Notification.permission === 'default') {
            Notification.requestPermission()
        }

        return () => {
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current)
            }
            wsRef.current?.close()
        }
    }, [connect])

    return { sendCommand }
}
