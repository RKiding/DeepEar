import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Signal } from './store'
import { SignalCard } from './components/SignalCard'
import './LiteDashboard.css'

type LitePayload = {
  generated_at?: string
  count?: number
  run_id?: string
  signals?: Signal[]
}

const formatTime = (value?: string) => {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN')
}

export const LiteDashboard = () => {
  const UPDATE_INTERVAL_HOURS = 4
  const navigate = useNavigate()
  const [payload, setPayload] = useState<LitePayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    fetch('/latest.json', { cache: 'no-store' })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`加载失败: ${res.status}`)
        }
        return res.json() as Promise<LitePayload>
      })
      .then((data) => {
        if (mounted) setPayload(data)
      })
      .catch((err) => {
        if (mounted) setError(err.message || '加载失败')
      })
    return () => {
      mounted = false
    }
  }, [])

  const signals = useMemo(() => payload?.signals ?? [], [payload])

  return (
    <div className="lite-page">
      <header className="lite-header">
        <div>
          <div className="lite-title">AlphaEar Lite</div>
          <div className="lite-subtitle">自动扫描 | 信号关联 | 新闻链接</div>
        </div>
        <div className="lite-meta">
          <div>更新时间：{formatTime(payload?.generated_at)}</div>
          <div>信号数：{payload?.count ?? signals.length}</div>
          <div>建议更新频率：{UPDATE_INTERVAL_HOURS} 小时</div>
        </div>
      </header>

      {error && <div className="lite-error">{error}</div>}

      <main className="lite-list">
        {signals.length === 0 && !error && (
          <div className="lite-empty">暂无数据，请先生成 latest.json</div>
        )}

        {signals.map((signal, index) => (
          <div key={signal.signal_id || index} className="lite-signal-block">
            <SignalCard
              signal={signal}
              onShowChart={(ticker) => navigate(`/lite/chart/${ticker}`)}
            />
          </div>
        ))}

      </main>
    </div>
  )
}
