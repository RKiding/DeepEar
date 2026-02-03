import { useMemo, useState } from 'react'
import type { RunData } from '../types/RunData'
import { SignalCard } from './SignalCard'
import { KLineChart } from './KLineChart'
import { BarChart3, Target, TrendingUp, GitMerge, ChevronDown, ChevronRight, List, Info, Sparkles, FileText, Share, Printer, X } from 'lucide-react'
import './ReportRenderer.css'

interface Props {
    data: RunData
    query?: string
}

export function ReportRenderer({ data, query }: Props) {
    const [expandedSections, setExpandedSections] = useState<Set<string>>(
        new Set(['signals', 'charts'])
    )
    const [viewMode, setViewMode] = useState<'structured' | 'full'>('structured')
    const [showShareModal, setShowShareModal] = useState(false)
    const [captcha, setCaptcha] = useState({ a: 0, b: 0, ans: 0, input: '' })

    const initCaptcha = () => {
        const a = Math.floor(Math.random() * 10) + 1
        const b = Math.floor(Math.random() * 10) + 1
        setCaptcha({ a, b, ans: a + b, input: '' })
    }

    const handleShareClick = () => {
        initCaptcha()
        setShowShareModal(true)
    }

    const verifyAndPrint = () => {
        if (parseInt(captcha.input) === captcha.ans) {
            setShowShareModal(false)
            setTimeout(() => window.print(), 100)
        } else {
            alert("验证码错误")
            initCaptcha()
        }
    }

    const chartList = Object.values(data.charts || {})
    const structured = data.report_structured
    const reportSignals = structured?.signals || []
    const topSignals = useMemo(() => {
        const list = [...reportSignals]
        return list
            .sort((a, b) => (b?.confidence || 0) - (a?.confidence || 0))
            .slice(0, 3)
    }, [reportSignals])

    const toggleSection = (section: string) => {
        const newSet = new Set(expandedSections)
        if (newSet.has(section)) {
            newSet.delete(section)
        } else {
            newSet.add(section)
        }
        setExpandedSections(newSet)
    }

    const cleanedSectionText = (content: string) => {
        return content
            .split('\n')
            .filter((line) => {
                const trimmed = line.trim()
                if (!trimmed) return false
                if (trimmed === '[TOC]') return false
                if (trimmed.startsWith('|')) return false
                if (/^[-]{3,}$/.test(trimmed)) return false
                return true
            })
            .slice(0, 6)
            .join('\n')
    }

    // Extract body content from HTML report
    const extractHtmlBody = (html: string): string => {
        if (!html) return ''
        // Extract content between <body> and </body>, or content within .container
        const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i)
        if (bodyMatch) {
            let content = bodyMatch[1]
            // Remove the container wrapper div if present
            const containerMatch = content.match(/<div class="container"[^>]*>([\s\S]*?)<\/div>\s*$/i)
            if (containerMatch) {
                content = containerMatch[1]
            }
            // Remove inline styles that might conflict
            content = content.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
            return content
        }
        return html
    }

    const htmlContent = useMemo(() => {
        if (data.report_content) {
            return extractHtmlBody(data.report_content)
        }
        return ''
    }, [data.report_content])

    const transmissionChains = useMemo(() => {
        const source = reportSignals.length ? reportSignals : data.signals || []
        return source
            .map((s: any) => s?.transmission_chain || [])
            .filter((chain: any[]) => Array.isArray(chain) && chain.length > 0)
            .slice(0, 3)
    }, [reportSignals, data.signals])

    return (
        <div className="report-renderer report-layout">
            <aside className="report-sidebar">
                <div className="sidebar-title"><List size={14} /> 目录</div>
                <nav className="report-toc">
                    <a href="#overview">概览</a>
                    {htmlContent && <a href="#full-report" onClick={() => setViewMode('full')}>完整报告</a>}
                    <a href="#signals">核心信号</a>
                    <a href="#charts">行情图表</a>
                    {transmissionChains.length > 0 && <a href="#graph">传导链条</a>}
                </nav>
                {htmlContent && (
                    <div className="view-mode-toggle">
                        <button
                            className={viewMode === 'structured' ? 'active' : ''}
                            onClick={() => setViewMode('structured')}
                        >
                            结构化
                        </button>
                        <button
                            className={viewMode === 'full' ? 'active' : ''}
                            onClick={() => setViewMode('full')}
                        >
                            完整报告
                        </button>
                    </div>
                )}
            </aside>

            <div className="report-main">
                <div className="report-title">
                    <h1><BarChart3 size={20} style={{ marginRight: 10 }} />{structured?.title || '分析报告'}</h1>
                    <div className="report-meta">
                        <span className="run-id">Run: {data.run_id}</span>
                        {query && <span className="query">查询: {query}</span>}
                    </div>
                </div>

                <div className="report-actions" style={{ position: 'absolute', top: 20, right: 20 }}>
                    <button
                        className="btn-share"
                        onClick={handleShareClick} type="button"
                        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 6, border: '1px solid #e2e8f0', background: 'white', cursor: 'pointer' }}
                    >
                        <Share size={14} /> 分享 / 打印
                    </button>
                </div>

                {showShareModal && (
                    <div className="modal-overlay" style={{
                        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                        background: 'rgba(0,0,0,0.5)', zIndex: 9999, display: 'flex', justifyContent: 'center', alignItems: 'center'
                    }}>
                        <div className="modal-content" style={{
                            background: 'white', padding: 24, borderRadius: 12, width: 320, position: 'relative'
                        }}>
                            <button
                                onClick={() => setShowShareModal(false)}
                                style={{ position: 'absolute', top: 12, right: 12, border: 'none', background: 'none', cursor: 'pointer' }}
                            >
                                <X size={18} color="#64748b" />
                            </button>

                            <h3 style={{ marginTop: 0, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                                <Printer size={20} /> 打印/保存 PDF
                            </h3>

                            <p style={{ fontSize: 14, color: '#64748b', marginBottom: 20 }}>
                                请完成简单的验证以继续打印或保存为 PDF。
                            </p>

                            <div className="captcha-box" style={{ marginBottom: 20 }}>
                                <div style={{ marginBottom: 8, fontWeight: 500 }}>
                                    {captcha.a} + {captcha.b} = ?
                                </div>
                                <input
                                    type="number"
                                    value={captcha.input}
                                    onChange={e => setCaptcha({ ...captcha, input: e.target.value })}
                                    onKeyDown={e => e.key === 'Enter' && verifyAndPrint()}
                                    autoFocus
                                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid #cbd5e1' }}
                                    placeholder="输入结果"
                                />
                            </div>

                            <button
                                onClick={verifyAndPrint}
                                style={{ width: '100%', padding: '10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 500 }}
                            >
                                确认并打印
                            </button>
                        </div>
                    </div>
                )}

                {/* Full HTML Report View */}
                {viewMode === 'full' && htmlContent ? (
                    <section id="full-report" className="report-section full-report-section">
                        <div className="section-header">
                            <h2><FileText size={16} style={{ marginRight: 8 }} />完整研报</h2>
                        </div>
                        <div className="section-content">
                            <div
                                className="html-report-content"
                                dangerouslySetInnerHTML={{ __html: htmlContent }}
                            />
                        </div>
                    </section>
                ) : (
                    <>
                        {/* Structured View - Overview Section */}
                        <section id="overview" className="report-section">
                            <div className="section-header">
                                <h2><Info size={16} style={{ marginRight: 8 }} />概览</h2>
                            </div>
                            <div className="section-content">
                                <div className="summary-grid">
                                    <div className="summary-card">
                                        <div className="summary-label">识别信号</div>
                                        <div className="summary-value">{reportSignals.length || data.signals.length}</div>
                                    </div>
                                    <div className="summary-card">
                                        <div className="summary-label">图表数量</div>
                                        <div className="summary-value">{chartList.length}</div>
                                    </div>
                                    <div className="summary-card">
                                        <div className="summary-label">传导节点</div>
                                        <div className="summary-value">{data.graph?.nodes?.length || transmissionChains.length || 0}</div>
                                    </div>
                                </div>

                                <div className="highlight-card">
                                    <div className="highlight-title">高置信信号</div>
                                    {topSignals.length === 0 ? (
                                        <div className="empty-state">暂无信号</div>
                                    ) : (
                                        <div className="highlight-list">
                                            {topSignals.map((signal: any, i: number) => (
                                                <div key={signal?.signal_id || i} className="highlight-item">
                                                    <span className="highlight-rank">#{i + 1}</span>
                                                    <span className="highlight-title-text">{signal?.title}</span>
                                                    <span className="highlight-score">C {signal?.confidence?.toFixed(2) || '-'} / I {signal?.intensity}</span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </section>

                        {structured?.summary_bullets?.length ? (
                            <section id="insights" className="report-section">
                                <div className="section-header">
                                    <h2><Sparkles size={16} style={{ marginRight: 8 }} />报告精要</h2>
                                </div>
                                <div className="section-content">
                                    <ul className="insight-list">
                                        {structured.summary_bullets.slice(0, 8).map((item, idx) => (
                                            <li key={idx}>{item}</li>
                                        ))}
                                    </ul>
                                </div>
                            </section>
                        ) : null}

                        {structured?.sections?.length ? (() => {
                            // Filter out sections with empty or minimal content
                            const validSections = structured.sections.filter(sec => {
                                const cleaned = cleanedSectionText(sec.content)
                                // Skip if content is too short (less than 20 chars after cleaning)
                                return cleaned.trim().length > 20
                            })

                            if (validSections.length === 0) return null

                            return (
                                <section id="sections" className="report-section">
                                    <div className="section-header">
                                        <h2><FileText size={16} style={{ marginRight: 8 }} />研报章节</h2>
                                        <span className="section-count">{validSections.length} 个</span>
                                    </div>
                                    <div className="section-content">
                                        <div className="section-grid">
                                            {validSections.slice(0, 6).map((sec, idx) => (
                                                <div key={idx} className="section-card">
                                                    <div className="section-card-title">{sec.title}</div>
                                                    <div className="section-card-body">
                                                        {cleanedSectionText(sec.content)}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </section>
                            )
                        })() : null}

                        {structured?.clusters?.length ? (
                            <section id="clusters" className="report-section">
                                <div className="section-header">
                                    <h2><Target size={16} style={{ marginRight: 8 }} />主题聚类</h2>
                                </div>
                                <div className="section-content">
                                    <div className="cluster-grid">
                                        {structured.clusters.map((cluster, idx) => (
                                            <div key={idx} className="cluster-card">
                                                <div className="cluster-title">{cluster.title || `主题 ${idx + 1}`}</div>
                                                {cluster.rationale && <div className="cluster-rationale">{cluster.rationale}</div>}
                                                <div className="cluster-signals">
                                                    {(cluster.signals || []).slice(0, 4).map((s: any, i: number) => (
                                                        <div key={i} className="cluster-signal">• {s?.title}</div>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </section>
                        ) : null}

                        {structured?.clusters?.length ? (
                            <section id="signals" className="report-section">
                                <div className="section-header">
                                    <h2><Target size={16} style={{ marginRight: 8 }} />核心信号</h2>
                                    <span className="section-count">{structured.clusters.length} 个主题</span>
                                </div>
                                <div className="section-content">
                                    <div className="cluster-grid">
                                        {structured.clusters.map((cluster, idx) => (
                                            <div key={idx} className="cluster-card">
                                                <div className="cluster-title">{cluster.title || `主题 ${idx + 1}`}</div>
                                                {cluster.rationale && <div className="cluster-rationale">{cluster.rationale}</div>}
                                                <div className="cluster-signals">
                                                    {(cluster.signals || []).slice(0, 6).map((s: any, i: number) => (
                                                        <div key={i} className="cluster-signal">• {s?.title}</div>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </section>
                        ) : (
                            <section id="signals" className="report-section">
                                <div className="section-header">
                                    <h2><Target size={16} style={{ marginRight: 8 }} />核心信号</h2>
                                    <span className="section-count">{reportSignals.length || data.signals.length} 个</span>
                                </div>
                                <div className="section-content">
                                    <div className="signals-grid">
                                        {(reportSignals.length ? reportSignals : data.signals).slice(0, 6).map((signal: any, i: number) => (
                                            <SignalCard key={signal.signal_id || i} signal={signal} />
                                        ))}
                                    </div>
                                </div>
                            </section>
                        )}

                        <section id="charts" className="report-section">
                            <div
                                className="section-header"
                                onClick={() => toggleSection('charts')}
                            >
                                <h2><TrendingUp size={16} style={{ marginRight: 8 }} />行情图表</h2>
                                <span className="section-count">{chartList.length} 个</span>
                                <span className="toggle-icon">
                                    {expandedSections.has('charts') ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                </span>
                            </div>
                            {expandedSections.has('charts') && (
                                <div className="section-content">
                                    {chartList.length === 0 ? (
                                        <div className="empty-state">暂无图表数据</div>
                                    ) : (
                                        <div className="charts-grid">
                                            {chartList.filter(chart => chart && chart.prices && chart.prices.length > 0).map((chart) => (
                                                <div key={chart.ticker} className="chart-card">
                                                    <KLineChart data={chart} />
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </section>

                        {transmissionChains.length > 0 && (
                            <section id="graph" className="report-section">
                                <div className="section-header">
                                    <h2><GitMerge size={16} style={{ marginRight: 8 }} />传导链条</h2>
                                </div>
                                <div className="section-content">
                                    <div className="graph-preview">
                                        {transmissionChains.map((chain: any[], idx: number) => (
                                            <div key={idx} className="chain-flow">
                                                {chain.map((node: any, i: number) => (
                                                    <span key={`${idx}-${i}`} className="chain-node">
                                                        {i > 0 && <span className="chain-arrow">→</span>}
                                                        <span className={`node-badge ${node?.impact_type || 'factor'}`}>
                                                            {node?.node_name || node?.label || node?.name}
                                                        </span>
                                                    </span>
                                                ))}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </section>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
