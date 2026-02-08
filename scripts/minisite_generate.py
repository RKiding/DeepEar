import argparse
import json
import os
from datetime import datetime
from pathlib import Path
import sys
import shutil
from typing import List, Optional, Dict, Any, Union
from zoneinfo import ZoneInfo


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_now() -> datetime:
    tz_name = os.getenv("TZ") or os.getenv("APP_TZ")
    if tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def load_signals(limit: int, db_path: str):
    project_root = resolve_project_root()
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))
    from utils.database_manager import DatabaseManager  # pylint: disable=import-error

    db = DatabaseManager(db_path)
    try:
        signals = db.get_recent_signals(limit=limit)
    finally:
        db.close()

    items = []
    for s in signals:
        items.append(
            {
                "signal_id": s.get("signal_id"),
                "title": s.get("title"),
                "summary": s.get("summary"),
                "impact_tickers": s.get("impact_tickers", []),
                "industry_tags": s.get("industry_tags", []),
                "sources": s.get("sources", []),
                "created_at": s.get("created_at"),
                "sentiment_score": s.get("sentiment_score", 0.0),
                "confidence": s.get("confidence", 0.0),
                "expected_horizon": s.get("expected_horizon"),
                "price_in_status": s.get("price_in_status"),
                "intensity": s.get("intensity"),
                "transmission_chain": s.get("transmission_chain", []),
            }
        )

    return items


def load_latest_run_data(max_runs: int = 10, db_path: str = "data/signal_flux.db"):
    project_root = resolve_project_root()
    sys.path.insert(0, str(project_root))
    from dashboard.db import DashboardDB  # pylint: disable=import-error

    db = DashboardDB(db_path=db_path)
    try:
        history = db.get_history(limit=max_runs)
        for run in history:
            data = db.get_run_data(run.run_id)
            if data and data.get("signals"):
                return run.run_id, data
    finally:
        db.conn.close()

    return None, None


def _resolve_sources(sources: List[str]) -> List[str]:
    project_root = resolve_project_root()
    sys.path.insert(0, str(project_root / "src"))
    from main_flow import SignalFluxWorkflow  # pylint: disable=import-error

    if "all" in sources:
        return SignalFluxWorkflow.ALL_SOURCES.copy()
    if "financial" in sources:
        return SignalFluxWorkflow.FINANCIAL_SOURCES.copy()
    if "social" in sources:
        return SignalFluxWorkflow.SOCIAL_SOURCES.copy()
    if "tech" in sources:
        return SignalFluxWorkflow.TECH_SOURCES.copy()
    return sources


def _llm_filter_signals(news_list: List[Dict[str, Any]], depth: Union[int, str], query: Optional[str], reasoning_model) -> List[Dict[str, Any]]:
    project_root = resolve_project_root()
    sys.path.insert(0, str(project_root / "src"))
    from agno.agent import Agent  # pylint: disable=import-error
    from prompts.trend_agent import get_news_filter_instructions  # pylint: disable=import-error
    from utils.json_utils import extract_json  # pylint: disable=import-error

    if isinstance(depth, int) and len(news_list) <= depth and not query:
        return news_list

    news_text = "\n".join([
        f"[ID: {n.get('id', i)}] {n.get('title', '')} (情绪: {n.get('sentiment_score', 'N/A')})"
        for i, n in enumerate(news_list)
    ])

    filter_instruction = get_news_filter_instructions(len(news_list), depth, query)
    filter_agent = Agent(model=reasoning_model, markdown=False, debug_mode=True, tool_call_limit=3)
    filter_agent.instructions = [filter_instruction]

    response = filter_agent.run(f"请筛选以下新闻:\n{news_text}")
    content = response.content if hasattr(response, "content") else str(response)
    result = extract_json(content)

    if result and not result.get("has_valid_signals", True):
        return []
    if not result:
        return news_list

    selected_ids = result.get("selected_ids", [])
    id_set = set(str(sid) for sid in selected_ids)
    filtered = [n for n in news_list if str(n.get("id", "")) in id_set]

    if query:
        return filtered
    return filtered or news_list


def run_lite_analysis(
    query: Optional[str],
    sources: List[str],
    wide: int,
    depth: Union[int, str],
    max_charts: int = 6,
    db_path: str = "data/signal_flux.db",
) -> Dict[str, Any]:
    project_root = resolve_project_root()
    default_kronos = project_root / "src" / "exports" / "models" / "kronos_news_v1_20260101_0015.pt"
    if default_kronos.exists() and not os.getenv("KRONOS_NEWS_MODEL_PATH"):
        os.environ["KRONOS_NEWS_MODEL_PATH"] = str(default_kronos)
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

    from utils.database_manager import DatabaseManager  # pylint: disable=import-error
    from utils.llm.router import router  # pylint: disable=import-error
    from agents import TrendAgent, FinAgent, IntentAgent  # pylint: disable=import-error
    from utils.search_tools import SearchTools  # pylint: disable=import-error
    from utils.stock_tools import StockTools  # pylint: disable=import-error
    from dashboard.integration import WorkflowRunner  # pylint: disable=import-error

    db = DatabaseManager(db_path)
    try:
        reasoning_model = router.get_reasoning_model()
        tool_model = router.get_tool_model()

        trend_agent = TrendAgent(db, reasoning_model, tool_model=tool_model, sentiment_mode="bert")
        fin_agent = FinAgent(db, reasoning_model, tool_model=tool_model, isq_template_id="default_isq_v1")
        intent_agent = IntentAgent(reasoning_model)
        search_tools = SearchTools(db)
        stock_tools = StockTools(db, auto_update=False)
        formatter = WorkflowRunner()

        resolved_sources = _resolve_sources(sources)

        intent_info: Any = {}
        if query:
            try:
                intent_info = intent_agent.run(query)
            except Exception:
                intent_info = {}

        for source in resolved_sources:
            try:
                trend_agent.news_toolkit.fetch_hot_news(source, count=wide)
            except Exception:
                continue

        trend_agent.sentiment_toolkit.batch_update_sentiment(limit=50)

        search_signals: List[Dict[str, Any]] = []
        if query:
            search_queries = [query]
            if isinstance(intent_info, dict):
                search_queries = intent_info.get("search_queries", [query]) or [query]
            for q in search_queries[:2]:
                results = search_tools.search_list(q, max_results=5, enrich=True)
                for r in results:
                    search_signals.append(
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "source": r.get("source", "Search"),
                            "content": r.get("content"),
                            "publish_time": r.get("publish_time") or get_now().isoformat(),
                            "sentiment_score": r.get("sentiment_score", 0),
                            "id": r.get("id") or f"search_{hash(r.get('url'))}",
                        }
                    )

        db_news = db.get_daily_news(limit=50)
        raw_news = search_signals + db_news if search_signals else db_news
        if not raw_news:
            return {"signals": [], "charts": {}}

        if depth == "auto" or query:
            high_value_signals = _llm_filter_signals(raw_news, depth, query, reasoning_model)
        else:
            if isinstance(depth, int) and depth > 0:
                high_value_signals = sorted(
                    raw_news,
                    key=lambda x: abs(x.get("sentiment_score") or 0),
                    reverse=True,
                )[:depth]
            else:
                high_value_signals = raw_news

        analyzed_signals: List[Dict[str, Any]] = []
        charts: Dict[str, Any] = {}
        charted = 0
        content_cache: Dict[str, str] = {}
        search_cache: Dict[str, List[Dict[str, Any]]] = {}

        for signal in high_value_signals:
            content = signal.get("content") or ""
            signal_url = signal.get("url")
            if len(content) < 50 and signal_url:
                cached = content_cache.get(signal_url)
                if cached is None:
                    cached = trend_agent.news_toolkit.fetch_news_content(signal_url) or ""
                    content_cache[signal_url] = cached
                content = cached
            input_text = f"【{signal.get('title', '')}】\n{content[:3000]}"

            sig_obj = fin_agent.analyze_signal(input_text, news_id=signal.get("id"))
            if not sig_obj:
                continue

            if not sig_obj.sources and signal.get("url"):
                sig_obj.sources = [
                    {
                        "title": signal.get("title"),
                        "url": signal.get("url"),
                        "source_name": signal.get("source", "Unknown"),
                    }
                ]

            sig_dict = sig_obj.dict()
            analyzed_signals.append(sig_dict)

            # Per-signal search results for display in card
            try:
                query_text = sig_dict.get("title") or sig_dict.get("summary") or signal.get("title")
                if query_text:
                    cache_key = str(query_text).strip()
                    cached_results = search_cache.get(cache_key)
                    if cached_results is None:
                        results = search_tools.search_list(cache_key, max_results=5, enrich=False)
                        cached_results = [
                            {
                                "title": r.get("title"),
                                "url": r.get("url"),
                                "source": r.get("source")
                            }
                            for r in results
                            if r.get("url")
                        ]
                        search_cache[cache_key] = cached_results
                    sig_dict["search_results"] = cached_results
            except Exception:
                sig_dict["search_results"] = []

            if charted >= max_charts:
                continue

            for ticker_info in sig_dict.get("impact_tickers", [])[:3]:
                ticker = ticker_info.get("ticker") if isinstance(ticker_info, dict) else None
                if not ticker or ticker in charts:
                    continue
                df = stock_tools.get_stock_price(ticker)
                if df is None or df.empty:
                    continue
                chart_data = formatter._format_chart_from_df(
                    ticker,
                    ticker_info.get("name", ticker) if isinstance(ticker_info, dict) else ticker,
                    df,
                    news_text=content,
                    prediction_logic=sig_dict.get("summary"),
                )
                if chart_data.get("prices"):
                    charts[ticker] = chart_data
                    charted += 1

        return {
            "signals": analyzed_signals,
            "charts": charts,
        }
    finally:
        db.close()


def write_latest_json(output_path: Path, signals):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": get_now().isoformat(),
        "count": len(signals),
        "signals": signals,
    }
    write_payload(output_path, payload)


def write_payload(output_path: Path, payload: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    project_root = resolve_project_root()
    dist_path = project_root / "dashboard" / "frontend" / "dist" / "latest.json"
    if dist_path.parent.exists():
        try:
            shutil.copyfile(output_path, dist_path)
            print(f"📦 Synced latest.json -> {dist_path}")
        except Exception:
            pass


def parse_args():
    parser = argparse.ArgumentParser(description="Generate lite dashboard data")
    parser.add_argument("--run-llm", action="store_true", help="Run lightweight LLM analysis to generate signals")
    parser.add_argument("--query", type=str, default=None, help="Optional query for focused scan")
    parser.add_argument(
        "--sources",
        type=str,
        default="financial",
        help="Comma-separated sources (all, financial, social, tech, or specific sources)",
    )
    parser.add_argument("--wide", type=int, default=10, help="Fetch count per source")
    parser.add_argument("--depth", type=str, default="auto", help="Signal depth or 'auto'")
    parser.add_argument("--max-charts", type=int, default=6, help="Max charts to generate")
    parser.add_argument("--limit", type=int, default=50, help="Max signals to export")
    parser.add_argument(
        "--db-path",
        type=str,
        default=os.getenv("STOCK_DB_PATH") or "data/signal_flux.db",
        help="SQLite DB path containing cached stock list",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path (default: dashboard/frontend/public/latest.json)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = resolve_project_root()
    output_path = (
        Path(args.output)
        if args.output
        else project_root / "dashboard" / "frontend" / "public" / "latest.json"
    )

    if args.run_llm:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        depth: Union[int, str]
        if args.depth.isdigit():
            depth = int(args.depth)
        else:
            depth = args.depth

        result = run_lite_analysis(
            query=args.query,
            sources=sources or ["financial"],
            wide=args.wide,
            depth=depth,
            max_charts=args.max_charts,
            db_path=args.db_path,
        )

        payload = {
            "generated_at": get_now().isoformat(),
            "run_id": f"lite_{get_now().strftime('%Y%m%d_%H%M%S')}",
            "count": len(result.get("signals", [])),
            "signals": result.get("signals", []),
            "charts": result.get("charts", {}),
        }
        write_payload(output_path, payload)
        print(f"✅ LLM analysis exported -> {output_path}")
        return

    run_id, run_data = load_latest_run_data(db_path=args.db_path)
    if run_data:
        signals = run_data.get("signals", [])
        payload = {
            "generated_at": get_now().isoformat(),
            "run_id": run_id,
            "count": len(signals),
            "signals": signals,
            "charts": run_data.get("charts", {}),
        }
        write_payload(output_path, payload)
        print(f"✅ Exported run {run_id} with {len(signals)} signals -> {output_path}")
        return

    signals = load_signals(limit=args.limit, db_path=args.db_path)
    write_latest_json(output_path, signals)
    print(f"✅ Exported {len(signals)} signals (fallback) -> {output_path}")


if __name__ == "__main__":
    main()
