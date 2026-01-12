"""
SignalFlux Dashboard 集成层
将 Dashboard WebSocket 与真实 SignalFlux 工作流连接
"""
import asyncio
import threading
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List
from loguru import logger
from queue import Queue

class DashboardCallback:
    """
    Dashboard 回调管理器
    用于在 Agent 执行过程中实时推送状态到 Dashboard
    """
    
    def __init__(self):
        self._event_queue: Queue = Queue()
        self._enabled = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._broadcast_func: Optional[Callable] = None
    
    def enable(self, broadcast_func: Callable, loop: asyncio.AbstractEventLoop):
        """启用回调"""
        self._enabled = True
        self._broadcast_func = broadcast_func
        self._loop = loop
        logger.info("📡 Dashboard callback enabled")
    
    def disable(self):
        """禁用回调"""
        self._enabled = False
        self._broadcast_func = None
        self._loop = None
    
    def _send_event(self, event_type: str, data: dict):
        """发送事件到 Dashboard"""
        if not self._enabled or not self._broadcast_func or not self._loop:
            return
        
        try:
            # 从同步代码安全地调用异步函数
            asyncio.run_coroutine_threadsafe(
                self._broadcast_func({"type": event_type, "data": data}),
                self._loop
            )
        except Exception as e:
            logger.warning(f"Failed to send dashboard event: {e}")
    
    def phase(self, name: str, progress: int):
        """更新阶段"""
        self._send_event("progress", {"phase": name, "progress": progress})
    
    def step(self, step_type: str, agent: str, content: str, **kwargs):
        """添加步骤"""
        self._send_event("step", {
            "type": step_type,
            "agent": agent,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        })
    
    def signal(self, signal_data: dict):
        """推送信号"""
        self._send_event("signal", signal_data)
    
    def chart(self, ticker: str, data: dict):
        """推送图表数据"""
        self._send_event("chart", {"ticker": ticker, **data})
    
    def prediction(self, ticker: str, prediction: dict):
        """推送预测"""
        self._send_event("prediction", {"ticker": ticker, "prediction": prediction})
    
    def graph(self, graph_data: dict):
        """推送传导图"""
        self._send_event("graph", graph_data)

# 全局单例
dashboard_callback = DashboardCallback()


class WorkflowRunner:
    """
    工作流运行器
    在后台线程中执行 SignalFlux 工作流，同时通过 DashboardCallback 推送状态
    """
    
    def __init__(self):
        self._workflow = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def _ensure_workflow(self):
        """延迟初始化工作流（避免导入时加载模型）"""
        if self._workflow is None:
            from main_flow import SignalFluxWorkflow
            self._workflow = SignalFluxWorkflow(isq_template_id="default_isq_v1")
        return self._workflow
    
    def is_running(self) -> bool:
        return self._running
    
    def run_async(
        self,
        query: Optional[str] = None,
        sources: List[str] = None,
        wide: int = 10,
        run_state: Any = None
    ):
        """在后台线程启动工作流"""
        if self._running:
            raise RuntimeError("Workflow already running")
        
        self._running = True
        self._thread = threading.Thread(
            target=self._run_workflow,
            args=(query, sources or ["financial"], wide, run_state),
            daemon=True
        )
        self._thread.start()
    
    def _run_workflow(
        self,
        query: Optional[str],
        sources: List[str],
        wide: int,
        run_state: Any
    ):
        """实际执行工作流（在后台线程中）- 完整复制 main_flow.py 逻辑"""
        cb = dashboard_callback
        
        try:
            # ========== Step 0: 初始化 ==========
            cb.phase("初始化", 5)
            cb.step("system", "System", f"🚀 SignalFlux Workflow 启动")
            cb.step("config", "System", f"Query: {query or '自动扫描'}, Sources: {sources}")
            
            workflow = self._ensure_workflow()
            
            # ========== Step 1: Trend Discovery ==========
            cb.phase("热点扫描", 10)
            cb.step("phase", "System", "📡 --- Step 1: Trend Discovery ---")
            
            # 1.0 意图分析 (如果存在 query) - 关键步骤！
            intent_info = {}
            if query:
                cb.step("thought", "IntentAgent", f"🧠 分析查询意图: {query}")
                try:
                    intent_info = workflow.intent_agent.run(query)
                    if isinstance(intent_info, dict):
                        keywords = intent_info.get("keywords", [])
                        search_queries = intent_info.get("search_queries", [])
                        is_specific = intent_info.get("is_specific_event", False)
                        cb.step("result", "IntentAgent", f"✅ 关键词: {keywords[:3]}, 特定事件: {is_specific}")
                        cb.step("result", "IntentAgent", f"✅ 搜索词: {search_queries[:2]}")
                    else:
                        cb.step("warning", "IntentAgent", "⚠️ 意图分析返回非字典格式")
                        intent_info = {"search_queries": [query]}
                except Exception as e:
                    cb.step("error", "IntentAgent", f"❌ 意图分析失败: {str(e)[:50]}")
                    intent_info = {"search_queries": [query]}
            
            # 1.1 解析 sources
            if "financial" in sources:
                actual_sources = workflow.FINANCIAL_SOURCES.copy()
            elif "all" in sources:
                actual_sources = workflow.ALL_SOURCES.copy()
            else:
                actual_sources = sources
            
            # 1.2 多源抓取
            cb.phase("多源抓取", 15)
            successful_sources = []
            for source in actual_sources[:5]:  # 限制源数量
                cb.step("tool_call", "TrendAgent", f"fetch_hot_news('{source}', count={wide})")
                try:
                    result = workflow.trend_agent.news_toolkit.fetch_hot_news(source, count=wide)
                    if result and len(result) > 0:
                        successful_sources.append(source)
                        cb.step("result", "TrendAgent", f"✅ {source}: 获取 {len(result)} 条")
                    else:
                        cb.step("result", "TrendAgent", f"⚠️ {source}: 无数据")
                except Exception as e:
                    cb.step("error", "TrendAgent", f"❌ {source}: {str(e)[:50]}")
            
            # 1.3 主动搜索 (关键！有 query 时执行网络搜索)
            search_signals = []
            if query and isinstance(intent_info, dict):
                search_queries = intent_info.get("search_queries", [query])
                is_specific = intent_info.get("is_specific_event", False)
                
                if is_specific or len(search_queries) > 0:
                    cb.phase("主动搜索", 22)
                    cb.step("thought", "TrendAgent", f"🔍 执行主动搜索: {search_queries[:2]}")
                    
                    for q in search_queries[:2]:  # 限制查询数
                        cb.step("tool_call", "TrendAgent", f"search_list('{q}', max_results=5)  # 使用默认引擎")
                        try:
                            results = workflow.search_tools.search_list(q, max_results=5, enrich=True)  # 使用默认引擎
                            for r in results:
                                search_signals.append({
                                    "title": r.get('title'),
                                    "url": r.get('url'),
                                    "source": r.get('source', 'Search'),
                                    "content": r.get('content'),
                                    "publish_time": r.get('publish_time') or datetime.now(),
                                    "sentiment_score": r.get('sentiment_score', 0),
                                    "id": r.get('id') or f"search_{hash(r.get('url') or '')}"
                                })
                            cb.step("result", "TrendAgent", f"✅ 搜索 '{q[:20]}...': {len(results)} 条")
                        except Exception as e:
                            cb.step("error", "TrendAgent", f"❌ 搜索失败: {str(e)[:50]}")
                    
                    cb.step("result", "TrendAgent", f"🔍 主动搜索共获取 {len(search_signals)} 条结果")
            
            # 1.4 情绪分析
            cb.phase("情绪分析", 28)
            cb.step("tool_call", "TrendAgent", "batch_update_sentiment(limit=50)")
            try:
                workflow.trend_agent.sentiment_toolkit.batch_update_sentiment(limit=50)
                cb.step("result", "TrendAgent", "✅ BERT 情绪分析完成")
            except Exception as e:
                cb.step("error", "TrendAgent", f"❌ 情绪分析失败: {str(e)[:50]}")
            
            # 1.5 读取数据库新闻并合并
            db_news = workflow.db.get_daily_news(limit=50) or []
            
            # 合并列表 (搜索结果优先)
            raw_news = search_signals + db_news if search_signals else db_news
            cb.step("thought", "TrendAgent", f"📊 合并数据: 搜索 {len(search_signals)} + 数据库 {len(db_news)} = {len(raw_news)} 条")
            
            if not raw_news:
                cb.phase("完成", 100)
                cb.step("warning", "System", "⚠️ 无可用新闻数据")
                self._running = False
                if run_state:
                    run_state.status = "completed"
                return
            
            # 1.6 LLM 筛选
            cb.phase("信号筛选", 35)
            cb.step("thought", "TrendAgent", f"🧠 使用 LLM 筛选 {len(raw_news)} 条新闻 (Query: {query or 'Auto'})...")
            
            high_value_signals = workflow._llm_filter_signals(raw_news, 'auto', query)
            cb.step("result", "TrendAgent", f"🎯 筛选出 {len(high_value_signals)} 个高价值信号")
            
            for sig in high_value_signals[:5]:
                cb.step("signal", "TrendAgent", f"📌 {sig.get('title', 'Unknown')[:40]}...")
            
            if not high_value_signals:
                cb.phase("完成", 100)
                cb.step("warning", "System", "⚠️ 未发现高价值信号，分析结束")
                self._running = False
                if run_state:
                    run_state.status = "completed"
                return
            
            # ========== Step 2: Financial Analysis ==========
            cb.phase("金融分析", 50)
            cb.step("phase", "System", f"💼 --- Step 2: Financial Analysis ({len(high_value_signals)} signals) ---")
            
            analyzed_signals = []
            total = len(high_value_signals)
            
            for i, signal in enumerate(high_value_signals):
                progress = 50 + int((i + 1) / total * 25)
                cb.phase(f"分析信号 {i+1}/{total}", progress)
                
                title = signal.get('title', 'Unknown')[:30]
                cb.step("thought", "FinAgent", f"📊 分析: {title}...")
                
                # 构造输入
                content = signal.get("content") or ""
                if len(content) < 50 and signal.get("url"):
                    try:
                        content = workflow.trend_agent.news_toolkit.fetch_news_content(signal["url"]) or ""
                    except:
                        pass
                input_text = f"【{signal['title']}】\n{content[:3000]}"
                
                try:
                    # 调用 FinAgent
                    sig_obj = workflow.fin_agent.analyze_signal(input_text, news_id=signal.get("id"))
                    
                    if sig_obj:
                        # 补充来源
                        if not sig_obj.sources and signal.get("url"):
                            sig_obj.sources = [{
                                "title": signal["title"],
                                "url": signal["url"],
                                "source_name": signal.get("source", "Unknown")
                            }]
                        
                        sig_dict = sig_obj.dict()
                        analyzed_signals.append(sig_dict)
                        
                        # 推送信号到 Dashboard
                        cb.signal(sig_dict)
                        
                        # ISQ 评分
                        isq_str = f"I={sig_obj.intensity}, S={sig_obj.sentiment_score:.2f}, C={sig_obj.confidence:.2f}"
                        cb.step("signal", "FinAgent", f"📊 ISQ: {isq_str}")
                        
                        # 推送标的信息
                        for ticker in sig_obj.impact_tickers[:2]:
                            ticker_code = ticker.get("ticker", "")
                            ticker_name = ticker.get("name", "")
                            if ticker_code:
                                cb.step("result", "FinAgent", f"→ {ticker_name} ({ticker_code})")
                                
                                # 尝试获取价格数据推送图表
                                try:
                                    prices = workflow.trend_agent.stock_toolkit.get_stock_price(ticker_code, days=30)
                                    if prices:
                                        chart_data = self._format_chart_data(ticker_code, ticker_name, prices)
                                        cb.chart(ticker_code, chart_data)
                                except:
                                    pass
                        
                        # 传导链
                        if sig_obj.transmission_chain:
                            chain = " → ".join([n.node_name for n in sig_obj.transmission_chain[:3]])
                            cb.step("thought", "FinAgent", f"🔗 {chain}")
                            
                            # 推送传导图
                            graph = self._build_graph(sig_obj)
                            cb.graph(graph)
                        
                        # 保存到数据库
                        workflow.db.save_signal(sig_dict)
                    else:
                        cb.step("warning", "FinAgent", f"⚠️ 无法解析: {title}")
                        
                except Exception as e:
                    cb.step("error", "FinAgent", f"❌ 分析失败: {str(e)[:50]}")
            
            if not analyzed_signals:
                cb.phase("完成", 100)
                cb.step("warning", "System", "⚠️ 分析未产出有效信号")
                self._running = False
                if run_state:
                    run_state.status = "completed"
                return
            
            # 更新 run_state
            if run_state:
                run_state.signals = analyzed_signals
            
            # ========== Step 3: Report Generation ==========
            cb.phase("报告生成", 85)
            cb.step("phase", "System", "📝 --- Step 3: Report Generation ---")
            
            cb.step("thought", "ReportAgent", "信号聚类分析...")
            cb.step("thought", "ReportAgent", "规划报告结构 (Map-Reduce)...")
            
            try:
                result = workflow.report_agent.generate_report(analyzed_signals, user_query=query)
                md_content = result.content if hasattr(result, "content") else str(result)
                
                cb.step("thought", "ReportAgent", "生成章节内容...")
                cb.step("thought", "ReportAgent", "渲染图表...")
                
                # 保存报告
                from utils.md_to_html import save_report_as_html
                import os
                
                report_dir = "reports"
                os.makedirs(report_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M')
                md_filename = f"{report_dir}/daily_report_{timestamp}.md"
                
                with open(md_filename, "w", encoding="utf-8") as f:
                    f.write(md_content)
                
                html_filename = save_report_as_html(md_filename)
                
                cb.step("result", "ReportAgent", f"📄 报告已保存: {html_filename or md_filename}")
                
            except Exception as e:
                cb.step("error", "ReportAgent", f"❌ 报告生成失败: {str(e)[:50]}")
            
            # 完成
            cb.phase("完成", 100)
            cb.step("system", "System", "✅ SignalFlux 分析完成！")
            cb.step("result", "System", f"📊 信号: {len(analyzed_signals)} | 耗时: ~{datetime.now().strftime('%H:%M:%S')}")
            
            if run_state:
                run_state.status = "completed"
                
        except Exception as e:
            cb.step("error", "System", f"❌ 工作流失败: {str(e)}")
            if run_state:
                run_state.status = "failed"
        finally:
            self._running = False
    
    def _format_chart_data(self, ticker: str, name: str, prices: Any) -> dict:
        """格式化价格数据为图表格式"""
        price_list = []
        
        if isinstance(prices, str):
            # 解析字符串格式
            import re
            lines = prices.strip().split('\n')
            for line in lines:
                match = re.search(r'(\d{4}-\d{2}-\d{2}).*?(\d+\.?\d*).*?(\d+\.?\d*).*?(\d+\.?\d*).*?(\d+\.?\d*)', line)
                if match:
                    price_list.append({
                        "date": match.group(1),
                        "open": float(match.group(2)),
                        "high": float(match.group(3)),
                        "low": float(match.group(4)),
                        "close": float(match.group(5)),
                        "volume": 0
                    })
        elif isinstance(prices, list):
            for p in prices:
                if isinstance(p, dict):
                    price_list.append({
                        "date": str(p.get("date", "")),
                        "open": float(p.get("open", 0)),
                        "high": float(p.get("high", 0)),
                        "low": float(p.get("low", 0)),
                        "close": float(p.get("close", 0)),
                        "volume": int(p.get("volume", 0))
                    })
        
        return {
            "ticker": ticker,
            "name": name,
            "prices": price_list[-30:] if price_list else []
        }
    
    def _build_graph(self, signal) -> dict:
        """从 InvestmentSignal 构建传导图"""
        nodes = []
        edges = []
        
        for i, node in enumerate(signal.transmission_chain):
            node_id = f"n{i}"
            node_type = "event" if i == 0 else "impact"
            nodes.append({
                "id": node_id,
                "label": node.node_name,
                "type": node_type,
                "impact": node.impact_type
            })
            if i > 0:
                edges.append({
                    "from": f"n{i-1}",
                    "to": node_id,
                    "label": node.impact_type
                })
        
        # 添加标的
        for j, ticker in enumerate(signal.impact_tickers[:3]):
            ticker_id = f"t{j}"
            nodes.append({
                "id": ticker_id,
                "label": f"{ticker.get('name', '')} ({ticker.get('ticker', '')})",
                "type": "stock"
            })
            if nodes:
                edges.append({
                    "from": f"n{len(signal.transmission_chain)-1}" if signal.transmission_chain else "n0",
                    "to": ticker_id,
                    "label": ""
                })
        
        return {"nodes": nodes, "edges": edges}


# 全局单例
workflow_runner = WorkflowRunner()
