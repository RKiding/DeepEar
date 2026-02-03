"""
AlphaEar Dashboard 集成层
将 Dashboard WebSocket 与真实 AlphaEar 工作流连接
"""
import asyncio
import threading
from datetime import datetime
import contextvars
from typing import Optional, Callable, Dict, Any, List, Union
from loguru import logger
from queue import Queue

# Context Var to track current run_id in threads
run_id_ctx = contextvars.ContextVar("run_id", default=None)

class DashboardCallback:
    """
    Dashboard 回调管理器
    """
    def __init__(self):
        self._enabled = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._broadcast_func: Optional[Callable] = None
    
    def enable(self, broadcast_func: Callable, loop: asyncio.AbstractEventLoop):
        self._enabled = True
        self._broadcast_func = broadcast_func
        self._loop = loop
        logger.info("📡 Dashboard callback enabled")
    
    def disable(self):
        self._enabled = False
        self._broadcast_func = None
        self._loop = None
    
    def _send_event(self, event_type: str, data: dict):
        if not self._enabled or not self._broadcast_func or not self._loop:
            return
        
        # Inject run_id from context
        current_run_id = run_id_ctx.get()
        if current_run_id:
            data["run_id"] = current_run_id
        
        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_func({"type": event_type, "data": data}),
                self._loop
            )
        except Exception as e:
            logger.warning(f"Failed to send dashboard event: {e}")

    # ... methods (phase, step, etc.) remain same as they call _send_event ...
    def phase(self, name: str, progress: int):
        self._send_event("progress", {"phase": name, "progress": progress})
    
    def step(self, step_type: str, agent: str, content: str, **kwargs):
        self._send_event("step", {
            "type": step_type,
            "agent": agent,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        })
    
    def signal(self, signal_data: dict):
        self._send_event("signal", signal_data)
    
    def chart(self, ticker: str, data: dict):
        self._send_event("chart", {"ticker": ticker, **data})
    
    def prediction(self, ticker: str, prediction: dict):
        self._send_event("prediction", {"ticker": ticker, "prediction": prediction})
    
    def graph(self, graph_data: dict):
        self._send_event("graph", graph_data)

# 全局单例
dashboard_callback = DashboardCallback()


class WorkflowRunner:
    """
    工作流运行器 - 支持多并发
    """
    
    def __init__(self):
        self._workflow = None
        # Track active runs: run_id -> Thread
        self._active_runs: Dict[str, threading.Thread] = {}
        self._cancelled_flags: Dict[str, bool] = {}
        self._lock = threading.Lock()
    
    def _ensure_workflow(self):
        if self._workflow is None:
            from main_flow import SignalFluxWorkflow
            self._workflow = SignalFluxWorkflow(isq_template_id="default_isq_v1")
        return self._workflow
    
    def is_running(self, run_id: str = None) -> bool:
        if run_id:
            return run_id in self._active_runs and self._active_runs[run_id].is_alive()
        return len(self._active_runs) > 0
    
    def is_cancelled(self, run_id: str) -> bool:
        return self._cancelled_flags.get(run_id, False)
    
    def cancel(self, run_id: str):
        if run_id in self._active_runs:
            self._cancelled_flags[run_id] = True
            logger.info(f"⚠️ Workflow cancellation requested for {run_id}")
            return True
        return False
    
    def run_async(
        self,
        query: Optional[str] = None,
        sources: List[str] = None,
        wide: int = 10,
        depth: Union[int, str] = "auto",
        run_state: Any = None, # Deprecated logic, server handles map
        user_id: Optional[str] = None,
        run_id: str = None, # Required for concurrency
        concurrency: int = 1
    ):
        if run_id in self._active_runs and self._active_runs[run_id].is_alive():
            raise RuntimeError(f"Run {run_id} is already active")
        
        self._cancelled_flags[run_id] = False
        
        thread = threading.Thread(
            target=self._run_workflow_wrapper, # Use wrapper to set context
            args=(run_id, query, sources or ["financial"], wide, depth, run_state, user_id, concurrency),
            daemon=True
        )
        with self._lock:
            self._active_runs[run_id] = thread
        thread.start()

    def update_run_async(
        self,
        base_run_id: str,
        run_state: Any = None,
        user_query: Optional[str] = None,
        new_run_id: str = None,
        user_id: Optional[str] = None
    ):
        if not new_run_id:
            raise ValueError("new_run_id required for update")
            
        if new_run_id in self._active_runs:
             raise RuntimeError(f"Run {new_run_id} is already active")

        self._cancelled_flags[new_run_id] = False

        thread = threading.Thread(
            target=self._run_update_wrapper,
            args=(new_run_id, base_run_id, run_state, user_query, user_id),
            daemon=True
        )
        with self._lock:
            self._active_runs[new_run_id] = thread
        thread.start()

    def _run_workflow_wrapper(self, run_id: str, *args):
        # Set context var
        token = run_id_ctx.set(run_id)
        try:
            self._run_workflow(run_id, *args)
        finally:
            run_id_ctx.reset(token)
            with self._lock:
                self._active_runs.pop(run_id, None)
                self._cancelled_flags.pop(run_id, None)
    
    def _run_update_wrapper(self, run_id: str, *args):
        token = run_id_ctx.set(run_id)
        try:
            self._run_update(run_id, *args)
        finally:
            run_id_ctx.reset(token)
            with self._lock:
                self._active_runs.pop(run_id, None)
                self._cancelled_flags.pop(run_id, None)


    
    def _run_workflow(
        self,
        run_id: str,
        query: Optional[str],
        sources: List[str],
        wide: int,
        depth: Union[int, str],
        run_state: Any, # Deprecated in multi-user mode essentially, but kept for sig compatibility
        user_id: Optional[str] = None,
        concurrency: int = 1
    ):
        """实际执行工作流（在后台线程中）- 完整复制 main_flow.py 逻辑"""
        cb = dashboard_callback
        
        def check_cancelled():
            """检查是否已取消"""
            if self._cancelled_flags.get(run_id, False):
                cb.step("warning", "System", "⚠️ 工作流已取消")
                raise InterruptedError("Workflow cancelled by user")
        
        try:
            # ========== Step 0: 初始化 ==========
            check_cancelled()
            cb.phase("初始化", 5)
            cb.step("system", "System", f"🚀 AlphaEar Workflow 启动")
            cb.step("config", "System", f"Query: {query or '自动扫描'}, Sources: {sources}")
            cb.step("config", "System", f"⚙️ Concurrency: {concurrency}")
            logger.info(f"🔧 Workflow started with concurrency={concurrency}")
            
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
                check_cancelled()  # 取消检查点
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
                        check_cancelled()  # 取消检查点
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
            
            high_value_signals = workflow._llm_filter_signals(raw_news, depth, query)
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
                check_cancelled()  # 取消检查点
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
                
            # --- New Concurrency Logic Start ---
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def analyze_single_signal_integration(signal_data, index, total_count):
                """Helper for integration.py concurrency"""
                try:
                    # Progress update (approximate since async)
                    # We can't easily update phase progress from thread accurately without lock or messing up order
                    # But individual signal processing doesn't need strict ordered progress updates.
                    # For simplicity, we skip granular progress update inside thread or just log.
                    
                    t_title = signal_data.get('title', 'Unknown')[:30]
                    # cb.step("thought", "FinAgent", f"📊 [Parallel] Analyzing: {t_title}...") # Avoid thread race on cb? cb should be thread safe-ish via loop.call_soon_threadsafe
                    
                    # Reconstruct context
                    s_content = signal_data.get("content") or ""
                    if len(s_content) < 50 and signal_data.get("url"):
                         try:
                             s_content = workflow.trend_agent.news_toolkit.fetch_news_content(signal_data["url"]) or ""
                         except:
                             pass
                    s_input_text = f"【{signal_data['title']}】\n{s_content[:3000]}"
                    
                    # Run Analysis
                    s_sig_obj = workflow.fin_agent.analyze_signal(s_input_text, news_id=signal_data.get("id"))
                    
                    if s_sig_obj:
                         # Source fallback
                        if not s_sig_obj.sources and signal_data.get("url"):
                            s_sig_obj.sources = [{
                                "title": signal_data["title"],
                                "url": signal_data["url"],
                                "source_name": signal_data.get("source", "Unknown")
                            }]
                        return s_sig_obj.dict(), s_sig_obj, signal_data
                    return None, None, signal_data
                except Exception as ex:
                    logger.error(f"Parallel analysis failed for {signal_data.get('title')}: {ex}")
                    return None, None, signal_data

            if concurrency > 1:
                cb.step("status", "System", f"🚀 启动并发分析 (并发数: {concurrency})")
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    futures = {executor.submit(analyze_single_signal_integration, sig, idx, total): sig for idx, sig in enumerate(high_value_signals)}
                    
                    completed_count = 0
                    for future in as_completed(futures):
                        try:
                            check_cancelled()
                            completed_count += 1
                            progress = 50 + int(completed_count / total * 25)
                            cb.phase(f"分析信号 {completed_count}/{total}", progress)
                            
                            sig_dict_res, sig_obj_res, original_sig = future.result()
                            
                            if sig_dict_res and sig_obj_res:
                                analyzed_signals.append(sig_dict_res)
                                cb.signal(sig_dict_res)
                                
                                # Logs & Steps
                                isq_str_res = f"I={sig_obj_res.intensity}, S={sig_obj_res.sentiment_score:.2f}, C={sig_obj_res.confidence:.2f}"
                                cb.step("signal", "FinAgent", f"📊 {original_sig.get('title')[:20]}... ISQ: {isq_str_res}")
                                
                                # Tickers & Charts
                                for ticker in sig_obj_res.impact_tickers[:2]:
                                    ticker_code = ticker.get("ticker", "")
                                    ticker_name = ticker.get("name", "")
                                    if ticker_code:
                                        # cb.step("result", "FinAgent", f"→ {ticker_name} ({ticker_code})")
                                        # Fetch chart (sync in thread is fine)
                                        try:
                                            from datetime import timedelta
                                            e_date = datetime.now().strftime('%Y-%m-%d')
                                            s_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
                                            df_res = workflow.trend_agent.stock_toolkit._stock_tools.get_stock_price(ticker_code, s_date, e_date)
                                            if df_res is not None and not df_res.empty:
                                                # Need input text for prediction
                                                s_c = original_sig.get("content") or "" 
                                                # (Simplified content retrieval again? or pass it out. Let's re-use simple one)
                                                c_input = f"【{original_sig['title']}】\n{s_c[:3000]}"
                                                
                                                chart_data_res = self._format_chart_from_df(
                                                    ticker_code, ticker_name, df_res, news_text=c_input, prediction_logic=sig_obj_res.summary
                                                )
                                                cb.chart(ticker_code, chart_data_res)
                                        except Exception as chart_e:
                                             logger.warning(f"Chart failed: {chart_e}")

                                # Graph
                                if sig_obj_res.transmission_chain:
                                    graph_res = self._build_graph(sig_obj_res)
                                    cb.graph(graph_res)

                                # Save DB
                                sig_dict_res["user_id"] = user_id
                                if user_id and sig_dict_res.get("signal_id"):
                                     sig_dict_res["signal_id"] = f"{sig_dict_res['signal_id']}_{user_id}"
                                workflow.db.save_signal(sig_dict_res)
                            
                        except Exception as thread_e:
                            cb.step("error", "FinAgent", f"❌ Thread Error: {thread_e}")

            else:
                # Sequential Loop (Original)
                for i, signal in enumerate(high_value_signals):
                    check_cancelled()  # 取消检查点
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
                        check_cancelled()  # LLM调用前检查点
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
                                        from datetime import timedelta
                                        end_date = datetime.now().strftime('%Y-%m-%d')
                                        start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
                                        # 使用底层 StockTools 获取 DataFrame，而非 Toolkit 的 markdown 输出
                                        df = workflow.trend_agent.stock_toolkit._stock_tools.get_stock_price(ticker_code, start_date, end_date)
                                        if df is not None and not df.empty:
                                            # Pass full signal content for news-aware prediction
                                            chart_data = self._format_chart_from_df(
                                                ticker_code, 
                                                ticker_name, 
                                                df, 
                                                news_text=input_text,
                                                prediction_logic=sig_obj.summary
                                            )
                                            cb.chart(ticker_code, chart_data)
                                    except Exception as e:
                                        logger.warning(f"Chart data fetch failed for {ticker_code}: {e}")
                            
                            # 传导链
                            if sig_obj.transmission_chain:
                                chain = " → ".join([n.node_name for n in sig_obj.transmission_chain[:3]])
                                cb.step("thought", "FinAgent", f"🔗 {chain}")
                                
                                # 推送传导图
                                graph = self._build_graph(sig_obj)
                                cb.graph(graph)
                            
                            # 保存到数据库
                            sig_dict["user_id"] = user_id
                            if user_id and sig_dict.get("signal_id"):
                                 sig_dict["signal_id"] = f"{sig_dict['signal_id']}_{user_id}"
                            workflow.db.save_signal(sig_dict)
                        else:
                            cb.step("warning", "FinAgent", f"⚠️ 无法解析: {title}")
                            
                    except Exception as e:
                        cb.step("error", "FinAgent", f"❌ 分析失败: {str(e)[:50]}")
            # --- Concurrency Logic End ---
            
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
                check_cancelled()  # 报告生成前检查点
                result = workflow.report_agent.generate_report(analyzed_signals, user_query=query)
                md_content = result.content if hasattr(result, "content") else str(result)
                if run_state and hasattr(result, "structured"):
                    run_state.report_structured = result.structured
                
                cb.step("thought", "ReportAgent", "生成章节内容...")
                cb.step("thought", "ReportAgent", "渲染图表...")
                
                # 保存报告
                from utils.md_to_html import save_report_as_html
                import os
                
                report_dir = "reports"
                os.makedirs(report_dir, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                md_filename = f"{report_dir}/daily_report_{timestamp}_{run_id[:6]}.md"
                
                with open(md_filename, "w", encoding="utf-8") as f:
                    f.write(md_content)
                
                html_filename = save_report_as_html(md_filename)
                
                cb.step("result", "ReportAgent", f"📄 报告已保存: {html_filename or md_filename}")
                
                 # 更新 run_state output (优先使用 HTML)
                if run_state:
                    run_state.output = html_filename or md_filename
                
            except Exception as e:
                cb.step("error", "ReportAgent", f"❌ 报告生成失败: {str(e)[:50]}")
            
            # 完成
            cb.phase("完成", 100)
            cb.step("system", "System", "✅ AlphaEar 分析完成！")
            cb.step("result", "System", f"📊 信号: {len(analyzed_signals)} | 耗时: ~{datetime.now().strftime('%H:%M:%S')}")
            
            if run_state:
                run_state.status = "completed"
        
        except InterruptedError:
            # 用户取消
            cb.step("warning", "System", "⚠️ 工作流已被用户取消")
            if run_state:
                run_state.status = "cancelled"
                
        except Exception as e:
            cb.step("error", "System", f"❌ 工作流失败: {str(e)}")
            if run_state:
                run_state.status = "failed"
        
        finally:
            # Cleanup handled by wrapper
            pass
    
    def _run_update(self, run_id: str, base_run_id: str, *args):
        """执行更新工作流 (Thread)"""
        # args: run_state, user_query, user_id (after update to update_run_async)
        # Unpack
        run_state = args[0] if len(args) > 0 else None
        user_query = args[1] if len(args) > 1 else None
        user_id = args[2] if len(args) > 2 else None
        new_run_id = run_id  # This is the new run ID passed from wrapper

        cb = dashboard_callback
        try:
            cb.phase("初始化", 5)
            cb.step("system", "System", f"🚀 Starting Update for Run: {base_run_id}")
            
            workflow = self._ensure_workflow()
            
            # Use workflow.update_run which handles reloading signals and refreshing prices
            cb.phase("刷新数据", 20)
            cb.step("status", "System", "📡 Refreshing market data...")
            
            # We override workflow.update_run slightly or trust it to do the job.
            # workflow.update_run returns the new run_id
            generated_run_id = workflow.update_run(
                base_run_id=base_run_id,
                user_query=user_query,
                new_run_id=new_run_id,
                callback=cb,
                user_id=user_id
            )
            
            if generated_run_id:
                cb.phase("完成", 100)
                cb.step("status", "System", f"✅ Update Completed. New Run ID: {generated_run_id}")
                if run_state:
                    run_state.status = "completed"
                    # Update DB for the new run (update_run created it, but we might want to ensure status sync)
                    # Actually workflow.update_run handles state.json and report generation.
            else:
                cb.step("error", "System", "❌ Update failed to produce a new run.")
                if run_state:
                    run_state.status = "failed"

        except Exception as e:
            cb.step("error", "System", f"❌ Update Workflow failed: {str(e)}")
            if run_state:
                run_state.status = "failed"
        finally:
            pass
    
    def _format_chart_from_df(self, ticker: str, name: str, df, news_text: Optional[str] = None, prediction_logic: Optional[str] = None) -> dict:
        """从 DataFrame 格式化价格数据为图表格式（推荐方法），包含预测"""
        import pandas as pd
        price_list = []
        
        # 取最近30条数据
        df_recent = df.tail(30)
        
        for _, row in df_recent.iterrows():
            try:
                # 处理日期格式
                date_val = row.get('date', '')
                if hasattr(date_val, 'strftime'):
                    date_str = date_val.strftime('%Y-%m-%d')
                else:
                    date_str = str(date_val)[:10]  # 确保只取日期部分
                
                price_list.append({
                    "date": date_str,
                    "open": float(row.get('open', 0)),
                    "high": float(row.get('high', 0)),
                    "low": float(row.get('low', 0)),
                    "close": float(row.get('close', 0)),
                    "volume": int(row.get('volume', 0))
                })
            except Exception as e:
                logger.warning(f"Error formatting price row: {e}")
                continue
        
        # 尝试获取 Kronos 预测
        prediction = None
        try:
            from utils.kronos_predictor import KronosPredictorUtility
            predictor = KronosPredictorUtility()
            # Pass news_text to the predictor
            forecast_points = predictor.get_base_forecast(df, lookback=20, pred_len=5, news_text=news_text)
            if forecast_points and len(forecast_points) > 0:
                # 计算预测涨跌幅
                last_close = price_list[-1]["close"] if price_list else 0
                if last_close > 0:
                    pred_closes = [p.close for p in forecast_points]
                    min_close = min(pred_closes)
                    max_close = max(pred_closes)
                    target_low = round(((min_close - last_close) / last_close) * 100, 1)
                    target_high = round(((max_close - last_close) / last_close) * 100, 1)
                    prediction = {
                        "target_low": target_low,
                        "target_high": target_high,
                        "confidence": 65  # 基础模型置信度
                    }
                    logger.debug(f"Kronos prediction for {ticker}: {target_low}% ~ {target_high}%")
        except Exception as e:
            logger.warning(f"Kronos prediction failed for {ticker}: {e}")
        
        result = {
            "ticker": ticker,
            "name": name,
            "prices": price_list
        }
        if prediction:
            result["prediction"] = prediction
            
        # Serialize full forecast points for visualization if available
        if 'forecast_points' in locals() and forecast_points:
             try:
                forecast_list = []
                for p in forecast_points:
                    forecast_list.append({
                        "date": p.date, 
                        "open": p.open,
                        "high": p.high,
                        "low": p.low,
                        "close": p.close,
                        "volume": p.volume
                    })
                result["forecast"] = forecast_list
             except Exception as e:
                 logger.warning(f"Failed to serialize forecast: {e}")

        # Try to get base forecast (without news) if news_text is provided
        if news_text:
            try:
                base_points = predictor.get_base_forecast(df, lookback=20, pred_len=5, news_text=None)
                if base_points:
                    base_list = []
                    for p in base_points:
                        base_list.append({
                            "date": p.date,
                            "open": p.open,
                            "high": p.high,
                            "low": p.low,
                            "close": p.close,
                            "volume": p.volume
                        })
                    result["forecast_base"] = base_list
            except Exception as e:
                logger.warning(f"Failed to get base forecast: {e}")

        if prediction_logic:
            result["prediction_logic"] = prediction_logic

        return result
    
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
