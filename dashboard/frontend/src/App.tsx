import { useState } from 'react'
import { useDashboardStore } from './store'
import { useWebSocket } from './useWebSocket'
import { ConsolePanel } from './components/ConsolePanel'
import { HistoryPanel } from './components/HistoryPanel'
import { SignalCard } from './components/SignalCard'
import { KLineChart } from './components/KLineChart'
import { Send, Wifi, WifiOff } from 'lucide-react'
import './App.css'

const API_BASE = import.meta.env.DEV ? 'http://localhost:8765' : ''

function App() {
  const [queryInput, setQueryInput] = useState('')
  const [loading, setLoading] = useState(false)
  const { sendCommand } = useWebSocket()

  const {
    connected,
    status,
    signals,
    charts,
    setRunning,
    query,
    setQuery
  } = useDashboardStore()

  const handleStartRun = async () => {
    if (loading || status === 'running') return

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryInput.trim() || null,
          sources: 'financial',
          wide: 10
        })
      })

      if (res.ok) {
        const data = await res.json()
        setRunning(data.run_id)
        setQuery(queryInput)
      } else {
        const err = await res.json()
        alert(err.detail || '启动失败')
      }
    } catch (e) {
      alert('请求失败: ' + (e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectRun = (runId: string) => {
    sendCommand('get_run_details', { run_id: runId })
  }

  const handleRerun = async (runId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/run/${runId}/rerun`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setRunning(data.run_id)
      }
    } catch (e) {
      alert('重新运行失败')
    }
  }

  const handleDelete = async (runId: string) => {
    try {
      await fetch(`${API_BASE}/api/run/${runId}?confirm=true`, { method: 'DELETE' })
      sendCommand('get_history')
      sendCommand('get_query_groups')
    } catch (e) {
      alert('删除失败')
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <span className="logo-icon">📡</span>
          <span className="logo-text">SignalFlux Dashboard</span>
        </div>
        <div className="header-right">
          <div className="connection-status" data-connected={connected}>
            {connected ? <Wifi size={16} /> : <WifiOff size={16} />}
            <span>{connected ? 'Connected' : 'Disconnected'}</span>
          </div>
        </div>
      </header>

      <div className="query-bar">
        <input
          type="text"
          className="query-input"
          placeholder="输入分析主题 (如: A股科技板块, 阿里外卖战)..."
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleStartRun()}
          disabled={status === 'running'}
        />
        <button
          className="run-btn"
          onClick={handleStartRun}
          disabled={loading || status === 'running'}
        >
          {status === 'running' ? (
            <>⏳ 运行中...</>
          ) : (
            <>
              <Send size={16} />
              开始分析
            </>
          )}
        </button>
      </div>

      <main className="main-content">
        <aside className="sidebar">
          <HistoryPanel
            onSelectRun={handleSelectRun}
            onRerun={handleRerun}
            onDelete={handleDelete}
          />
        </aside>

        <section className="console-section">
          <ConsolePanel />
        </section>

        <section className="report-section">
          <div className="report-header">
            <h2>📊 分析报告</h2>
            {query && <span className="current-query">{query}</span>}
          </div>

          <div className="report-content">
            {signals.length === 0 && Object.keys(charts).length === 0 ? (
              <div className="report-empty">
                <div className="empty-icon">📈</div>
                <div>运行分析后，报告将在此处生成</div>
              </div>
            ) : (
              <>
                {signals.length > 0 && (
                  <div className="signals-section">
                    <h3>🎯 识别信号 ({signals.length})</h3>
                    {signals.map((signal, i) => (
                      <SignalCard key={signal.signal_id || i} signal={signal} />
                    ))}
                  </div>
                )}

                {Object.keys(charts).length > 0 && (
                  <div className="charts-section">
                    <h3>📈 K线与预测</h3>
                    {Object.values(charts).map((chart) => (
                      <KLineChart key={chart.ticker} data={chart} />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
