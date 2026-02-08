import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface Step {
    step_type: string
    agent: string
    content: string
    timestamp: string
}

export interface Signal {
    signal_id: string
    title: string
    summary: string
    sentiment_score: number
    confidence: number
    intensity: number
    expectation_gap: number
    timeliness: number
    expected_horizon: string
    impact_tickers: Array<{ ticker: string; name: string; weight: number }>
    industry_tags: string[]
    transmission_chain: Array<{ node_name: string; impact_type: string; logic: string }>
    reasoning: string
    sources?: Array<{ title: string; url: string; source_name: string }>
    search_results?: Array<{ title: string; url: string; source?: string; source_name?: string }>
}

export interface ChartData {
    ticker: string
    name: string
    prices: Array<{
        date: string
        open: number
        high: number
        low: number
        close: number
        volume: number
    }>
    prediction?: {
        target_low: number
        target_high: number
        confidence: number
    }
    forecast?: Array<{
        date: string
        open: number
        high: number
        low: number
        close: number
        volume: number
    }>
    forecast_base?: Array<{
        date: string
        open: number
        high: number
        low: number
        close: number
        volume: number
    }>
    prediction_logic?: string
}

export interface HistoryItem {
    run_id: string
    query: string | null
    status: string
    started_at: string | null
    finished_at: string | null
    signal_count: number
    duration_seconds: number | null
    time_since_last_run: string | null
    parent_run_id?: string | null
    report_path?: string | null
}

export interface QueryGroup {
    query: string
    run_count: number
    runs: HistoryItem[]
    last_run_at: string | null
}

interface DashboardState {
    // 连接状态
    connected: boolean
    setConnected: (connected: boolean) => void

    // 当前运行
    runId: string | null
    status: 'idle' | 'running' | 'completed' | 'failed'
    phase: string
    progress: number
    query: string

    // 数据
    steps: Step[]
    signals: Signal[]
    charts: Record<string, ChartData>
    graph: { nodes: any[]; edges: any[] }

    // 历史
    history: HistoryItem[]
    queryGroups: QueryGroup[]

    // 对比模式
    compareTabs: Array<{ runId: string; query: string }>
    activeTabIndex: number

    // Actions
    setQuery: (query: string) => void
    setRunning: (runId: string) => void
    setCompleted: () => void
    setFailed: (error: string) => void
    addStep: (step: Step) => void
    addSignal: (signal: Signal) => void
    updateChart: (ticker: string, data: ChartData) => void
    updateGraph: (graph: { nodes: any[]; edges: any[] }) => void
    updateProgress: (phase: string, progress: number) => void
    setHistory: (history: HistoryItem[]) => void
    setQueryGroups: (groups: QueryGroup[]) => void
    reset: () => void

    // 对比模式
    addCompareTab: (runId: string, query: string) => void
    removeCompareTab: (index: number) => void
    setActiveTab: (index: number) => void

    // Console 折叠状态
    consoleCollapsed: boolean
    setConsoleCollapsed: (collapsed: boolean) => void

    // Auth
    user: { id: number; username: string } | null
    token: string | null
    isAuthenticated: boolean
    login: (user: { id: number; username: string }, token: string) => void
    logout: () => void
}

export const useDashboardStore = create<DashboardState>()(
    persist(
        (set) => ({
            // 初始状态
            connected: false,
            setConnected: (connected) => set({ connected }),

            runId: null,
            status: 'idle',
            phase: '',
            progress: 0,
            query: '',

            steps: [],
            signals: [],
            charts: {},
            graph: { nodes: [], edges: [] },

            history: [],
            queryGroups: [],

            compareTabs: [],
            activeTabIndex: 0,

            // Actions
            setQuery: (query) => set({ query }),

            setRunning: (runId) => set({
                runId,
                status: 'running',
                steps: [],
                signals: [],
                charts: {},
                graph: { nodes: [], edges: [] }
            }),

            setCompleted: () => set({ status: 'completed' }),

            setFailed: (_error) => set({ status: 'failed' }),

            addStep: (step) => set((state) => ({
                steps: [...state.steps, step]
            })),

            addSignal: (signal) => set((state) => ({
                signals: [...state.signals, signal]
            })),

            updateChart: (ticker, data) => set((state) => ({
                charts: { ...state.charts, [ticker]: data }
            })),

            updateGraph: (graph) => set({ graph }),

            updateProgress: (phase, progress) => set({ phase, progress }),

            setHistory: (history) => set({ history }),

            setQueryGroups: (groups) => set({ queryGroups: groups }),

            reset: () => set({
                runId: null,
                status: 'idle',
                phase: '',
                progress: 0,
                steps: [],
                signals: [],
                charts: {},
                graph: { nodes: [], edges: [] }
            }),

            // 对比模式
            addCompareTab: (runId, query) => set((state) => ({
                compareTabs: [...state.compareTabs, { runId, query }]
            })),

            removeCompareTab: (index) => set((state) => ({
                compareTabs: state.compareTabs.filter((_, i) => i !== index),
                activeTabIndex: Math.min(state.activeTabIndex, state.compareTabs.length - 2)
            })),

            setActiveTab: (index) => set({ activeTabIndex: index }),

            // Console 折叠状态
            consoleCollapsed: false,
            setConsoleCollapsed: (collapsed) => set({ consoleCollapsed: collapsed }),

            // Auth
            user: null,
            token: null,
            isAuthenticated: false,
            login: (user, token) => set({ user, token, isAuthenticated: true }),
            logout: () => set({ user: null, token: null, isAuthenticated: false })
        }),
        {
            name: 'signalflux-console',
            storage: createJSONStorage(() => sessionStorage),
            partialize: (state) => ({
                // Only persist data, not volatile status
                steps: state.steps,
                signals: state.signals,
                charts: state.charts,
                graph: state.graph,
                runId: state.runId,
                query: state.query,
                consoleCollapsed: state.consoleCollapsed,
                user: state.user,
                token: state.token,
                isAuthenticated: state.isAuthenticated
                // Intentionally NOT persisting: status, phase, progress
                // These should reset to 'idle' on page refresh to sync with backend
            })
        }
    )
)

