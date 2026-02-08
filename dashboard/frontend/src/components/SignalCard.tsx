import type { Signal } from '../store'
import { useState } from 'react'
import { ChevronDown, ChevronUp, BarChart2 } from 'lucide-react'
import { ISQRadar } from './ISQRadar'
import './SignalCard.css'

interface Props {
    signal: Signal
    onShowChart?: (ticker: string) => void
}

export function SignalCard({ signal, onShowChart }: Props) {
    const [expanded, setExpanded] = useState(false)

    // Check if summary is long enough to need truncation
    const isLongSummary = signal.summary.length > 80

    return (
        <div className="signal-card">
            <div className="signal-header">
                <h3 className="signal-title">{signal.title}</h3>
                <div className="signal-tags">
                    {signal.industry_tags.map((tag) => (
                        <span key={tag} className="tag">{tag}</span>
                    ))}
                </div>
            </div>

            <div className={`signal-summary-container ${expanded ? 'expanded' : ''}`}>
                <p className="signal-summary">
                    {expanded || !isLongSummary ? signal.summary : `${signal.summary.slice(0, 80)}...`}
                </p>
                {isLongSummary && (
                    <button
                        className="expand-btn"
                        onClick={(e) => {
                            e.stopPropagation()
                            setExpanded(!expanded)
                        }}
                    >
                        {expanded ? <><ChevronUp size={12} /> 收起</> : <><ChevronDown size={12} /> 展开</>}
                    </button>
                )}
            </div>

            <div className="isq-radar-wrapper">
                <ISQRadar
                    sentiment={signal.sentiment_score}
                    confidence={signal.confidence}
                    intensity={signal.intensity}
                    expectationGap={signal.expectation_gap}
                    timeliness={signal.timeliness}
                />
            </div>

            <div className="signal-tickers">
                {signal.impact_tickers.map((ticker) => (
                    <span
                        key={ticker.ticker}
                        className={`ticker-chip ${onShowChart ? 'clickable' : ''}`}
                        onClick={() => onShowChart?.(ticker.ticker)}
                        title="点击查看图表"
                    >
                        {onShowChart && <BarChart2 size={12} style={{ marginRight: 4 }} />}
                        <span className="ticker-name">{ticker.name}</span>
                        <span className="ticker-code">{ticker.ticker}</span>
                    </span>
                ))}
            </div>

            {signal.transmission_chain.length > 0 && (
                <div className="transmission-chain">
                    {signal.transmission_chain.map((node, i) => (
                        <span key={i} className="chain-node">
                            {i > 0 && <span className="chain-arrow">→</span>}
                            <span className={`node-badge ${node.impact_type}`}>
                                {node.node_name}
                            </span>
                        </span>
                    ))}
                </div>
            )}

            {/* Signal Sources References */}
            {signal.sources && signal.sources.length > 0 && (
                <div className="signal-sources">
                    <div className="sources-label">相关报道 / 来源</div>
                    <div className="sources-list">
                        {signal.sources.map((src, i) => (
                            <a
                                key={i}
                                href={src.url}
                                target="_blank"
                                rel="noreferrer"
                                className="source-link"
                                onClick={(e) => e.stopPropagation()}
                            >
                                {src.source_name && (
                                    <span className="source-tag">{src.source_name}</span>
                                )}
                                <span className="source-text">{src.title}</span>
                            </a>
                        ))}
                    </div>
                </div>
            )}

            {signal.search_results && signal.search_results.length > 0 && (
                <div className="signal-sources">
                    <div className="sources-label">相关搜索</div>
                    <div className="sources-list">
                        {signal.search_results.map((src, i) => (
                            <a
                                key={i}
                                href={src.url}
                                target="_blank"
                                rel="noreferrer"
                                className="source-link"
                                onClick={(e) => e.stopPropagation()}
                            >
                                {(src.source_name || src.source) && (
                                    <span className="source-tag">{src.source_name || src.source}</span>
                                )}
                                <span className="source-text">{src.title}</span>
                            </a>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
