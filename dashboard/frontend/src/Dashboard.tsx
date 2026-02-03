import { useEffect, useState, useCallback } from 'react'
import { useDashboardStore } from './store'
import { useWebSocket } from './useWebSocket'
import { ConsolePanel } from './components/ConsolePanel'
import { HistoryPanel } from './components/HistoryPanel'
import { HotNewsPanel } from './components/HotNewsPanel'
import { SignalCard } from './components/SignalCard'
import { KLineChart } from './components/KLineChart'
import { Send, Wifi, WifiOff, Loader2, BarChart3, Target, TrendingUp, GitCompare, Square, FileX, LogOut, Download, Share2 } from 'lucide-react'
import { ComparisonView } from './components/ComparisonView'
import { ReportRenderer } from './components/ReportRenderer'
import { PhaseIndicator } from './components/PhaseIndicator'
import { ChartModal } from './components/ChartModal'
import type { RunData } from './types/RunData'
import './App.css'

const API_BASE = import.meta.env.DEV ? 'http://localhost:8765' : ''

export function Dashboard() {
    const [queryInput, setQueryInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [showParams, setShowParams] = useState(false)
    const [selectedSources, setSelectedSources] = useState<string[]>(['financial'])
    const [wide, setWide] = useState(10)
    const [depth, setDepth] = useState<string>('auto')
    const [concurrency, setConcurrency] = useState(1)
    const { sendCommand } = useWebSocket()

    const {
        connected,
        runId,
        status,
        signals,
        charts,
        query,
        setRunning,
        setQuery,
        compareTabs,
        activeTabIndex,
        setActiveTab,
        addCompareTab,
        removeCompareTab,
        history,
        phase,
        progress,
        consoleCollapsed,
        token, // Get token
        logout, // Get logout
        user
    } = useDashboardStore()

    const [viewMode, setViewMode] = useState<'dashboard' | 'report' | 'comparison'>('dashboard')
    const [currentRunData, setCurrentRunData] = useState<RunData | null>(null)
    const [parentRunData, setParentRunData] = useState<RunData | null>(null)
    const [selectedTicker, setSelectedTicker] = useState<string | null>(null)

    const SOURCE_OPTIONS = [
        { id: 'all', label: '全量' },
        { id: 'financial', label: '财经聚合' },
        { id: 'social', label: '社交聚合' },
        { id: 'tech', label: '科技聚合' },
        { id: 'cls', label: '财联社' },
        { id: 'wallstreetcn', label: '华尔街见闻' },
        { id: 'xueqiu', label: '雪球' },
        { id: 'weibo', label: '微博' },
        { id: 'zhihu', label: '知乎' },
        { id: 'baidu', label: '百度' },
        { id: 'toutiao', label: '头条' },
        { id: 'douyin', label: '抖音' },
        { id: '36kr', label: '36氪' },
        { id: 'ithome', label: 'IT之家' },
        { id: 'v2ex', label: 'V2EX' },
        { id: 'juejin', label: '掘金' },
        { id: 'hackernews', label: 'HN' }
    ]

    const toggleSource = (id: string) => {
        setSelectedSources((prev) => {
            const next = new Set(prev)
            if (next.has(id)) {
                next.delete(id)
            } else {
                next.add(id)
            }
            if (next.size === 0) next.add('financial')
            return Array.from(next)
        })
    }

    const resolveSourcesPayload = () => {
        if (selectedSources.includes('all')) return ['all']
        if (selectedSources.includes('financial')) return ['financial']
        if (selectedSources.includes('social')) return ['social']
        if (selectedSources.includes('tech')) return ['tech']
        return selectedSources
    }

    // Fetch structured run data for rendering - wrapped in useCallback to fix stale closures
    const fetchRunData = useCallback(async (runIdToFetch: string) => {
        if (!token) return;
        try {
            const res = await fetch(`${API_BASE}/api/run/${runIdToFetch}/data`, {
                headers: { 'Authorization': `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                setCurrentRunData(data)

                // Also fetch parent run data if exists
                const latestHistory = useDashboardStore.getState().history
                const run = latestHistory.find(r => r.run_id === runIdToFetch)
                if (run?.parent_run_id) {
                    const parentRes = await fetch(`${API_BASE}/api/run/${run.parent_run_id}/data`, {
                        headers: { 'Authorization': `Bearer ${token}` }
                    })
                    if (parentRes.ok) {
                        setParentRunData(await parentRes.json())
                    }
                    // Auto-switch to comparison view when loading a tracked update
                    setViewMode('comparison')
                } else {
                    setParentRunData(null)
                }
            }
        } catch (e) {
            console.error('Failed to fetch run data:', e)
        }
    }, [token])

    const handleStartRun = async () => {
        if (loading || status === 'running') return

        setLoading(true)
        try {
            const res = await fetch(`${API_BASE}/api/run`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    query: queryInput.trim() || null,
                    sources: resolveSourcesPayload(),
                    wide,
                    depth,
                    concurrency
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

    const handleCancelRun = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/run/cancel`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                if (!data.success) {
                    console.warn(data.message)
                }
            }
        } catch (e) {
            console.error('Cancel failed:', e)
        }
    }

    const handleSelectRun = (runId: string) => {
        const run = useDashboardStore.getState().history.find(r => r.run_id === runId)
        addCompareTab(runId, run?.query || runId)
        setActiveTab(compareTabs.length)

        sendCommand('get_run_details', { run_id: runId })
        fetchRunData(runId)
        setViewMode('dashboard')
    }

    const handleRerun = async (runId: string) => {
        try {
            const res = await fetch(`${API_BASE}/api/run/${runId}/rerun`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            })
            if (res.ok) {
                const data = await res.json()
                setRunning(data.run_id)
            }
        } catch (e) {
            alert('重新运行失败')
        }
    }

    const handleUpdateRun = async (runId: string) => {
        const userInput = window.prompt("请输入追踪更新的指令 (可选):", "Update based on latest market data")
        if (userInput === null) return

        try {
            setLoading(true)
            const res = await fetch(`${API_BASE}/api/run/${runId}/update`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ query: userInput })
            })
            if (res.ok) {
                const data = await res.json()
                if (data?.run_id) {
                    setRunning(data.run_id)
                    const baseRun = history.find(r => r.run_id === runId)
                    if (baseRun?.query) setQuery(baseRun.query)
                }
            } else {
                const err = await res.json()
                alert(err.detail || '启动更新失败')
            }
        } catch (e) {
            alert('更新请求失败: ' + (e as Error).message)
        } finally {
            setLoading(false)
        }
    }

    const handleDelete = async (runId: string) => {
        try {
            await fetch(`${API_BASE}/api/run/${runId}?confirm=true`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` }
            })
            sendCommand('get_history')
            sendCommand('get_query_groups')
        } catch (e) {
            alert('删除失败')
        }
    }

    const activeRunId = compareTabs[activeTabIndex]?.runId
    const effectiveRunId = activeRunId || runId || null
    const activeRun = history.find(r => r.run_id === activeRunId)

    useEffect(() => {
        if (status === 'running') {
            setCurrentRunData(null)
            return
        }

        if (!effectiveRunId) return
        fetchRunData(effectiveRunId)
    }, [status, effectiveRunId, fetchRunData])

    return (
        <div className="app">
            <header className="header">
                <div className="logo">
                    <div className="logo-icon">
                        <img src="/alphaear.svg" alt="AlphaEar" width={24} height={24} />
                    </div>
                    <span className="logo-text">AlphaEar</span>
                </div>
                <div className="header-right">
                    {user && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <div style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
                                User: <strong style={{ color: 'var(--color-primary)' }}>{user.username}</strong>
                            </div>
                        </div>
                    )}
                    <button onClick={logout} className="toggle-btn" title="Logout" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <LogOut size={16} />
                    </button>
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
                        <><Loader2 size={16} className="spin" /> 运行中...</>
                    ) : (
                        <>
                            <Send size={16} />
                            开始分析
                        </>
                    )}
                </button>
                {status === 'running' && (
                    <button className="cancel-btn" onClick={handleCancelRun} title="取消运行">
                        <Square size={16} />
                        取消
                    </button>
                )}
                <button
                    className="param-btn"
                    onClick={() => setShowParams((v) => !v)}
                    disabled={status === 'running'}
                >
                    参数
                </button>
            </div>

            {showParams && (
                <div className="param-panel">
                    <div className="param-group">
                        <div className="param-label">热点来源</div>
                        <div className="param-chips">
                            {SOURCE_OPTIONS.map((s) => (
                                <button
                                    key={s.id}
                                    className={`param-chip ${selectedSources.includes(s.id) ? 'active' : ''}`}
                                    onClick={() => toggleSource(s.id)}
                                >
                                    {s.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="param-row">
                        <div className="param-group">
                            <div className="param-label">宽度 (wide)</div>
                            <input
                                type="number"
                                min={1}
                                max={30}
                                value={wide}
                                onChange={(e) => setWide(Math.max(1, Number(e.target.value) || 1))}
                                className="param-input"
                            />
                        </div>
                        <div className="param-group">
                            <div className="param-label">深度 (depth)</div>
                            <select
                                className="param-input"
                                value={depth}
                                onChange={(e) => setDepth(e.target.value)}
                            >
                                <option value="auto">auto</option>
                                <option value="5">5</option>
                                <option value="10">10</option>
                                <option value="15">15</option>
                                <option value="20">20</option>
                            </select>
                        </div>
                    </div>

                    <div className="param-row" style={{ marginTop: '12px' }}>
                        <div className="param-group">
                            <div className="param-label">并发数 (Concurrency)</div>
                            <input
                                type="number"
                                min={1}
                                max={15}
                                value={concurrency}
                                onChange={(e) => setConcurrency(Math.max(1, Math.min(15, Number(e.target.value) || 5)))}
                                className="param-input"
                                title="设置信号分析的并发线程数 (1-15)"
                            />
                            <div className="param-help" style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                                建议根据机器性能设置 (默认: 1, 推荐: 3-5)
                            </div>
                        </div>
                    </div>
                </div>
            )}

            <main className={`main-content ${consoleCollapsed ? 'console-collapsed' : ''}`}>
                <aside className="sidebar">
                    <HotNewsPanel
                        onPickQuery={(q) => {
                            setQueryInput(q)
                            setViewMode('dashboard')
                        }}
                    />
                    <HistoryPanel
                        onSelectRun={handleSelectRun}
                        onRerun={handleRerun}
                        onUpdate={handleUpdateRun}
                        onDelete={handleDelete}
                    />
                </aside>

                <section className={`console-section ${consoleCollapsed ? 'collapsed' : ''}`}>
                    {!consoleCollapsed && (status === 'running' || status === 'completed') && !activeRunId && (
                        <PhaseIndicator phase={phase} progress={progress} status={status} />
                    )}
                    <ConsolePanel />
                </section>

                <section className="report-section">
                    <div className="report-header">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                            <h2><BarChart3 size={18} style={{ marginRight: 8, verticalAlign: 'middle' }} />分析报告</h2>
                            <div className="view-toggles">
                                <button
                                    className={`toggle-btn ${viewMode === 'dashboard' ? 'active' : ''}`}
                                    onClick={() => setViewMode('dashboard')}
                                >
                                    仪表盘
                                </button>
                                <button
                                    className={`toggle-btn ${viewMode === 'report' ? 'active' : ''}`}
                                    onClick={() => setViewMode('report')}
                                >
                                    完整报告
                                </button>
                                <button
                                    className={`toggle-btn ${viewMode === 'comparison' ? 'active' : ''}`}
                                    onClick={() => setViewMode('comparison')}
                                    disabled={!activeRunId && !status}
                                >
                                    <GitCompare size={14} style={{ marginRight: 4 }} />
                                    对比
                                </button>
                            </div>
                        </div>
                    </div>
                    <div className="report-content">
                        {viewMode === 'dashboard' ? (
                            <div className="dashboard-view">
                                {(() => {
                                    const displaySignals = currentRunData?.signals || signals
                                    const displayCharts = currentRunData?.charts || charts
                                    const chartList = Object.values(displayCharts)

                                    if (displaySignals.length === 0 && chartList.length === 0 && status !== 'running') {
                                        return (
                                            <div className="report-empty">
                                                <div className="empty-icon"><TrendingUp size={48} /></div>
                                                <div>运行分析后，报告将在此处生成</div>
                                            </div>
                                        )
                                    }

                                    return (
                                        <div className="dashboard-grid">
                                            {/* Sources Summary Stats */}
                                            {(displaySignals.length > 0) && (() => {
                                                const sourcesStats = displaySignals.reduce((acc, sig) => {
                                                    (sig.sources || []).forEach(src => {
                                                        const name = src.source_name || src.title || 'Unknown'
                                                        acc[name] = (acc[name] || 0) + 1
                                                    })
                                                    return acc
                                                }, {} as Record<string, number>)
                                                const sourceList = Object.entries(sourcesStats).sort((a, b) => b[1] - a[1])

                                                if (sourceList.length === 0) return null

                                                // Import Newspaper icon at top level, but for now inline usage is fine if imported
                                                return (
                                                    <div className="sources-summary">
                                                        <div className="sources-label"><TrendingUp size={16} /> 来源分布:</div>
                                                        {sourceList.map(([name, count]) => (
                                                            <div key={name} className="source-stat">
                                                                <span>{name}</span>
                                                                <strong>{count}</strong>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )
                                            })()}

                                            {displaySignals.length > 0 && (
                                                <div className="signals-section">
                                                    <h3 className="section-title"><Target size={16} /> 识别信号 ({displaySignals.length})</h3>
                                                    <div className="signals-list">
                                                        {displaySignals.map((signal, i) => (
                                                            <SignalCard
                                                                key={signal.signal_id || i}
                                                                signal={signal}
                                                                onShowChart={(t) => (displayCharts[t] || charts[t]) && setSelectedTicker(t)}
                                                            />
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {chartList.length > 0 && (
                                                <div className="charts-section">
                                                    <h3 className="section-title"><TrendingUp size={16} /> K线概览</h3>
                                                    <div className="charts-grid">
                                                        {chartList.filter(chart => chart && chart.prices && chart.prices.length > 0).map((chart) => (
                                                            <div key={chart.ticker} className="chart-preview" onClick={() => setSelectedTicker(chart.ticker)}>
                                                                <KLineChart data={chart} />
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )
                                })()}
                            </div>
                        ) : viewMode === 'comparison' ? (
                            (currentRunData && parentRunData) ? (
                                <ComparisonView
                                    oldRun={parentRunData}
                                    newRun={currentRunData}
                                />
                            ) : (
                                <div className="report-placeholder">
                                    {currentRunData && !activeRun?.parent_run_id ? (
                                        <div className="empty-state-message" style={{ textAlign: 'center', color: '#64748B' }}>
                                            <FileX size={48} style={{ opacity: 0.5, marginBottom: 16 }} />
                                            <p>当前分析无对比基准 (Initial Run)</p>
                                            <p className="sub-text">请使用"更新"功能来基于此次运行生成对比报告</p>
                                            <button
                                                className="btn-secondary"
                                                style={{ marginTop: 16 }}
                                                onClick={() => setViewMode('dashboard')}
                                            >
                                                返回仪表盘
                                            </button>
                                        </div>
                                    ) : (
                                        <>
                                            <Loader2 size={32} className="spin" style={{ color: '#3B82F6', marginBottom: 16 }} />
                                            <p>正在加载对比数据...</p>
                                        </>
                                    )}
                                </div>
                            )
                        ) : (
                            status === 'running' ? (
                                <div className="report-placeholder">
                                    <Loader2 size={32} className="spin" style={{ color: '#3B82F6', marginBottom: 16 }} />
                                    <p>正在生成分析报告...</p>
                                    <p className="sub-text">请等待分析完成，或在左侧查看实时信号与日志</p>
                                </div>
                            ) : (
                                currentRunData && (
                                    <>
                                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginBottom: '16px' }}>
                                            <button
                                                className="btn-secondary"
                                                style={{ padding: '6px 14px', height: '32px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
                                                onClick={() => {
                                                    const url = `${window.location.protocol}//${window.location.host}/api/run/${currentRunData.run_id}/export?view=true`;
                                                    navigator.clipboard.writeText(url).then(() => alert('报告预览/分享链接已复制到剪贴板'));
                                                }}
                                                title="复制下载链接"
                                            >
                                                <Share2 size={14} /> 分享
                                            </button>
                                            <button
                                                className="btn-secondary"
                                                style={{
                                                    padding: '6px 14px',
                                                    height: '32px',
                                                    fontSize: '13px',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '6px',
                                                    backgroundColor: '#2563eb',
                                                    color: 'white',
                                                    border: 'none',
                                                    boxShadow: '0 1px 2px rgba(0,0,0,0.1)'
                                                }}
                                                onClick={() => window.open(`/api/run/${currentRunData.run_id}/export`, '_blank')}
                                            >
                                                <Download size={14} /> 导出完整报告
                                            </button>
                                        </div>
                                        <ReportRenderer
                                            data={currentRunData}
                                            query={activeRun?.query || query || undefined}
                                        />
                                    </>
                                )
                            )
                        )}

                    </div>

                    {compareTabs.length > 0 && (
                        <div className="report-tabs">
                            {compareTabs.map((tab, idx) => (
                                <div
                                    key={`${tab.runId}-${idx}`}
                                    className={`report-tab ${idx === activeTabIndex ? 'active' : ''}`}
                                    onClick={() => {
                                        setActiveTab(idx)
                                        handleSelectRun(tab.runId)
                                    }}
                                >
                                    <span className="tab-title">{tab.query || tab.runId}</span>
                                    <span
                                        className="tab-close"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            removeCompareTab(idx)
                                        }}
                                    >
                                        ×
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </section>

                {selectedTicker && (
                    <ChartModal
                        data={(currentRunData?.charts?.[selectedTicker]) || charts[selectedTicker] || null}
                        onClose={() => setSelectedTicker(null)}
                    />
                )}
            </main>
        </div>
    )
}
