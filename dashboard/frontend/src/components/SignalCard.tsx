import type { Signal } from '../store'
import './SignalCard.css'

interface Props {
    signal: Signal
}

export function SignalCard({ signal }: Props) {
    const sentimentClass = signal.sentiment_score > 0.3 ? 'positive' :
        signal.sentiment_score < -0.3 ? 'negative' : 'neutral'

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

            <p className="signal-summary">{signal.summary}</p>

            <div className="signal-metrics">
                <div className="metric">
                    <span className="metric-label">情绪</span>
                    <span className={`metric-value ${sentimentClass}`}>
                        {(signal.sentiment_score * 100).toFixed(0)}%
                    </span>
                </div>
                <div className="metric">
                    <span className="metric-label">确定性</span>
                    <span className="metric-value">
                        {(signal.confidence * 100).toFixed(0)}%
                    </span>
                </div>
                <div className="metric">
                    <span className="metric-label">强度</span>
                    <span className="metric-value">{signal.intensity}/5</span>
                </div>
                <div className="metric">
                    <span className="metric-label">预期差</span>
                    <span className="metric-value">
                        {(signal.expectation_gap * 100).toFixed(0)}%
                    </span>
                </div>
                <div className="metric">
                    <span className="metric-label">时效</span>
                    <span className="metric-value">{signal.expected_horizon}</span>
                </div>
            </div>

            <div className="signal-tickers">
                {signal.impact_tickers.map((ticker) => (
                    <span key={ticker.ticker} className="ticker-chip">
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
        </div>
    )
}
