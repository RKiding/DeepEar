import { useDashboardStore, type HistoryItem } from '../store'
import { useState } from 'react'
import { Clock, RotateCcw, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import './HistoryPanel.css'

interface Props {
    onSelectRun: (runId: string) => void
    onRerun: (runId: string) => void
    onDelete: (runId: string) => void
}

export function HistoryPanel({ onSelectRun, onRerun, onDelete }: Props) {
    const { queryGroups, history } = useDashboardStore()
    const [expandedQueries, setExpandedQueries] = useState<Set<string>>(new Set())
    const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
    const [viewMode, setViewMode] = useState<'grouped' | 'list'>('grouped')

    const toggleQuery = (query: string) => {
        const next = new Set(expandedQueries)
        if (next.has(query)) {
            next.delete(query)
        } else {
            next.add(query)
        }
        setExpandedQueries(next)
    }

    const handleDelete = (runId: string) => {
        if (showDeleteConfirm === runId) {
            onDelete(runId)
            setShowDeleteConfirm(null)
        } else {
            setShowDeleteConfirm(runId)
        }
    }

    const formatDuration = (seconds: number | null) => {
        if (!seconds) return '-'
        if (seconds < 60) return `${seconds}s`
        return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    }

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'completed': return <span className="status-badge completed">✓</span>
            case 'failed': return <span className="status-badge failed">✗</span>
            case 'running': return <span className="status-badge running">●</span>
            default: return null
        }
    }

    return (
        <div className="history-panel">
            <div className="history-header">
                <span className="history-title">📜 历史记录</span>
                <div className="view-toggle">
                    <button
                        className={viewMode === 'grouped' ? 'active' : ''}
                        onClick={() => setViewMode('grouped')}
                    >
                        分组
                    </button>
                    <button
                        className={viewMode === 'list' ? 'active' : ''}
                        onClick={() => setViewMode('list')}
                    >
                        列表
                    </button>
                </div>
            </div>

            <div className="history-content">
                {viewMode === 'grouped' ? (
                    // 按 Query 分组视图
                    queryGroups.length === 0 ? (
                        <div className="history-empty">暂无历史记录</div>
                    ) : (
                        queryGroups.map((group) => (
                            <div key={group.query} className="query-group">
                                <div
                                    className="query-group-header"
                                    onClick={() => toggleQuery(group.query)}
                                >
                                    {expandedQueries.has(group.query) ?
                                        <ChevronDown size={16} /> :
                                        <ChevronRight size={16} />
                                    }
                                    <span className="query-text">{group.query}</span>
                                    <span className="run-count">{group.run_count} 次</span>
                                </div>

                                {expandedQueries.has(group.query) && (
                                    <div className="query-runs">
                                        {group.runs.map((run) => (
                                            <HistoryRow
                                                key={run.run_id}
                                                item={run}
                                                onSelect={onSelectRun}
                                                onRerun={onRerun}
                                                onDelete={handleDelete}
                                                showDeleteConfirm={showDeleteConfirm === run.run_id}
                                                formatDuration={formatDuration}
                                                getStatusBadge={getStatusBadge}
                                            />
                                        ))}
                                        <button
                                            className="rerun-latest-btn"
                                            onClick={() => onRerun(group.runs[0].run_id)}
                                        >
                                            <RotateCcw size={14} />
                                            一键更新
                                        </button>
                                    </div>
                                )}
                            </div>
                        ))
                    )
                ) : (
                    // 列表视图
                    history.length === 0 ? (
                        <div className="history-empty">暂无历史记录</div>
                    ) : (
                        history.map((item) => (
                            <HistoryRow
                                key={item.run_id}
                                item={item}
                                onSelect={onSelectRun}
                                onRerun={onRerun}
                                onDelete={handleDelete}
                                showDeleteConfirm={showDeleteConfirm === item.run_id}
                                formatDuration={formatDuration}
                                getStatusBadge={getStatusBadge}
                                showQuery
                            />
                        ))
                    )
                )}
            </div>
        </div>
    )
}

interface HistoryRowProps {
    item: HistoryItem
    onSelect: (runId: string) => void
    onRerun: (runId: string) => void
    onDelete: (runId: string) => void
    showDeleteConfirm: boolean
    formatDuration: (seconds: number | null) => string
    getStatusBadge: (status: string) => React.ReactNode
    showQuery?: boolean
}

function HistoryRow({
    item, onSelect, onRerun, onDelete, showDeleteConfirm,
    formatDuration, getStatusBadge, showQuery
}: HistoryRowProps) {
    return (
        <div className="history-row" onClick={() => onSelect(item.run_id)}>
            <div className="row-main">
                {getStatusBadge(item.status)}
                <div className="row-info">
                    {showQuery && <div className="row-query">{item.query || '自动扫描'}</div>}
                    <div className="row-meta">
                        <Clock size={12} />
                        <span>{item.time_since_last_run || '-'}</span>
                        <span>·</span>
                        <span>{formatDuration(item.duration_seconds)}</span>
                        <span>·</span>
                        <span>{item.signal_count} 信号</span>
                    </div>
                </div>
            </div>
            <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                <button className="action-btn" onClick={() => onRerun(item.run_id)} title="重新运行">
                    <RotateCcw size={14} />
                </button>
                <button
                    className={`action-btn delete ${showDeleteConfirm ? 'confirm' : ''}`}
                    onClick={() => onDelete(item.run_id)}
                    title={showDeleteConfirm ? '确认删除' : '删除'}
                >
                    <Trash2 size={14} />
                </button>
            </div>
        </div>
    )
}
