import os
import time
from datetime import datetime
from typing import List, Optional
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger

from utils.database_manager import DatabaseManager
from tools.toolkits import StockToolkit, SearchToolkit, NewsToolkit
from prompts.fin_agent import (
    get_fin_researcher_instructions, 
    get_fin_analyst_instructions,
    get_fin_research_task,
    format_research_context,
    get_fin_analysis_task,
    get_tracking_analysis_task
)
from schema.models import InvestmentSignal, ResearchContext
from utils.json_utils import extract_json

class FinAgent:
    """
    金融分析师 (FinAgent) - 负责深度分析金融信号并关联具体的投资标的
    采用双模型架构：Tool Model 负责信息检索，Reasoning Model 负责深度分析与结构化输出。
    """
    
    def __init__(self, db: DatabaseManager, model: Model, tool_model: Optional[Model] = None, isq_template_id: str = "default_isq_v1"):
        self.db = db
        self.model = model  # Reasoning Model
        self.tool_model = tool_model or model  # Tool Model
        self.isq_template_id = isq_template_id
        
        # 初始化工具包
        self.stock_toolkit = StockToolkit(db)
        self.search_toolkit = SearchToolkit(db)
        self.news_toolkit = NewsToolkit(db)
        
        # 1. 研究员 Agent (负责使用工具搜集信息)
        self.researcher = Agent(
            model=self.tool_model,
            tools=[
                self.stock_toolkit.search_ticker,
                self.stock_toolkit.get_stock_price,
                self.search_toolkit.web_search,
                self.news_toolkit.fetch_news_content,
            ],
            instructions=[get_fin_researcher_instructions()],
            markdown=False,
            debug_mode=True,
            output_schema=ResearchContext if hasattr(self.tool_model, 'response_format') else None,
            tool_call_limit=3
        )

        # 2. 分析师 Agent (负责深度逻辑推理和 JSON 输出)
        self.analyst = Agent(
            model=self.model,
            instructions=[get_fin_analyst_instructions(template_id=self.isq_template_id)],
            markdown=False,
            debug_mode=True,
            output_schema=InvestmentSignal if hasattr(self.model, 'response_format') else None,
            tool_call_limit=3
        )
        
        logger.info(f"💼 FinAgent initialized (Dual-Model: Reasoning={self.model.id}, Tool={self.tool_model.id}, ISQ={self.isq_template_id})")

    def analyze_signal(self, signal_text: str, news_id: str = None, max_retries: int = 3) -> Optional[InvestmentSignal]:
        """
        分析具体的金融信号并返回结构化的 InvestmentSignal
        采用双模型架构：Tool Model 搜集数据 -> Reasoning Model 深度分析
        """
        
        logger.info(f"💼 FinAgent starting dual-phase analysis for: {signal_text[:50]}...")
        
        # 第一阶段：研究员搜集信息（使用 Tool Model）
        research_task = get_fin_research_task(signal_text)
        research_context_str = ""
        research_raw_response = ""
        research_data = None
        
        try:
            logger.info("📊 Phase 1: Researcher gathering information using tools...")
            research_response = self.researcher.run(research_task)
            research_raw_response = research_response.content if hasattr(research_response, 'content') else str(research_response)
            
            # 直接使用研究员的完整输出（包含工具调用结果）
            research_context_str = research_raw_response
            
            # 同时尝试解析结构化数据用于日志记录
            research_data = extract_json(research_raw_response)
            if research_data:
                logger.info(f"✅ Research phase completed. Found tickers: {research_data.get('tickers_found', [])}")
            else:
                logger.info("✅ Research phase completed (unstructured format)")
                
        except Exception as e:
            logger.warning(f"⚠️ Research phase failed: {e}. Proceeding with raw signal only.")
            research_context_str = "（研究阶段失败，将仅基于原始信号进行分析）"

        # 第二阶段：分析师基于完整背景进行深度分析（使用 Reasoning Model）
        # 包含详细的工具调用结果和原始信号
        analysis_task = get_fin_analysis_task(signal_text, research_context_str)
        
        logger.info("🧠 Phase 2: Analyst performing deep ISQ analysis...")
        
        for attempt in range(max_retries):
            try:
                response = self.analyst.run(analysis_task)
                content = response.content if hasattr(response, 'content') else str(response)
                
                # 调试日志：显示分析师的输出长度
                logger.debug(f"Analyst response length: {len(content)} chars")
                
                # 尝试从内容中提取 JSON
                json_data = extract_json(content)
                if json_data:
                    # 补全 news_id 如果有
                    if news_id and not json_data.get('signal_id'):
                        json_data['signal_id'] = news_id

                    # Sanitize tickers to avoid low-quality hallucinated associations.
                    json_data = self._sanitize_signal_output(json_data, research_data=research_data, raw_signal=signal_text)
                    
                    logger.info(f"✅ Analysis completed successfully (attempt {attempt + 1}/{max_retries})")
                    logger.debug(f"Extracted signal: {json_data.get('title', 'N/A')}, confidence: {json_data.get('confidence', 'N/A')}")
                    
                    # 转换为模型对象
                    return InvestmentSignal(**json_data)
                
                raise ValueError("Could not extract valid JSON from response")
                
            except Exception as e:
                logger.warning(f"⚠️ FinAgent analysis attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)
                else:
                    logger.error("❌ FinAgent analysis failed after all retries")
                    return None

    @staticmethod
    def _clean_digits(value: str) -> str:
        s = (value or "").strip()
        if not s:
            return ""
        return "".join([c for c in s if c.isdigit()])

    def _sanitize_signal_output(self, json_data: dict, research_data: Optional[dict] = None, raw_signal: str = "") -> dict:
        """Post-process LLM output to prevent spurious ticker/name binding.

        Rules (conservative by default):
        - impact_tickers must be valid A/H numeric codes present in cached stock_list.
        - The ticker must be supported by evidence: it appears in signal title/summary/source titles/urls,
          OR it was returned via the researcher's structured tickers_found.
        - The displayed name is overwritten by the official name from stock_list.
        """
        if not isinstance(json_data, dict):
            return json_data

        tool_suggested: set[str] = set()
        if isinstance(research_data, dict):
            tf = research_data.get('tickers_found')
            if isinstance(tf, list):
                for item in tf:
                    if not isinstance(item, dict):
                        continue
                    code_raw = item.get('code') or item.get('ticker') or item.get('symbol')
                    code = self._clean_digits(str(code_raw or ""))
                    if code:
                        tool_suggested.add(code)

        sources = json_data.get('sources')
        source_titles: list[str] = []
        source_urls: list[str] = []
        if isinstance(sources, list):
            for s in sources:
                if not isinstance(s, dict):
                    continue
                t = str(s.get('title') or "").strip()
                u = str(s.get('url') or "").strip()
                if t:
                    source_titles.append(t)
                if u:
                    source_urls.append(u)

        evidence_text = " ".join([
            str(raw_signal or ""),
            str(json_data.get('title') or ""),
            str(json_data.get('summary') or ""),
            " ".join(source_titles),
            " ".join(source_urls),
        ])

        impact = json_data.get('impact_tickers')
        if not isinstance(impact, list) or not impact:
            return json_data

        sanitized: list[dict] = []
        for item in impact:
            if not isinstance(item, dict):
                continue
            code_raw = item.get('ticker') or item.get('code') or item.get('symbol')
            code = self._clean_digits(str(code_raw or ""))
            if not (code.isdigit() and len(code) in (5, 6)):
                continue

            stock = self.db.get_stock_by_code(code)
            if not stock:
                continue
            official_name = stock.get('name') or ""

            # Evidence gate: allow if suggested by tools OR explicitly mentioned in evidence.
            mentioned = (code in evidence_text) or (official_name and official_name in evidence_text)
            if tool_suggested:
                if code not in tool_suggested and not mentioned:
                    continue
            else:
                if not mentioned:
                    continue

            new_item = dict(item)
            new_item['ticker'] = code
            new_item['name'] = official_name
            sanitized.append(new_item)

        json_data['impact_tickers'] = sanitized

        # Sanitize ISQ values to avoid NaN/None/out-of-range
        def to_float(value: object, default: float) -> float:
            try:
                v = float(value)
                if v != v:  # NaN check
                    return default
                return v
            except Exception:
                return default

        def clamp(v: float, min_v: float, max_v: float) -> float:
            return max(min(v, max_v), min_v)

        json_data['sentiment_score'] = clamp(to_float(json_data.get('sentiment_score'), 0.0), -1.0, 1.0)
        json_data['confidence'] = clamp(to_float(json_data.get('confidence'), 0.5), 0.0, 1.0)

        intensity_raw = json_data.get('intensity', 3)
        try:
            intensity_val = int(float(intensity_raw))
        except Exception:
            intensity_val = 3
        json_data['intensity'] = max(1, min(intensity_val, 5))

        json_data['expectation_gap'] = clamp(to_float(json_data.get('expectation_gap'), 0.5), 0.0, 1.0)
        json_data['timeliness'] = clamp(to_float(json_data.get('timeliness'), 0.8), 0.0, 1.0)
        return json_data

    def track_signal(self, old_signal: dict, max_retries: int = 3) -> Optional[InvestmentSignal]:
        """
        追踪并更新已有信号的状态（Update/Tracking Mode）
        1. 研究员：针对该信号搜集最新进展（Price + News）
        2. 分析师：对比新旧信息，输出 Evolution
        """
        title = old_signal.get("title", "Unknown")
        logger.info(f"🔄 Tracking signal evolution: {title}")
        
        # 1. 针对性搜集最新信息
        # 构造一个侧重于“近期变化”的研究任务
        research_task = f"请追踪【{title}】的最新进展。重点查询：1. 最近的股价走势和关键公告。2. 原有的逻辑（{old_signal.get('summary', '')}）是否发生变化？包含具体的新闻标题和价格。"
        
        research_context_str = ""
        research_data = None
        
        try:
            logger.info(f"📊 Tracking Phase 1: Researching updates for {title}...")
            research_response = self.researcher.run(research_task)
            research_raw_response = research_response.content if hasattr(research_response, 'content') else str(research_response)
            research_context_str = research_raw_response
            research_data = extract_json(research_raw_response)
        except Exception as e:
            logger.warning(f"⚠️ Tracking research failed: {e}")
            research_context_str = "（追踪研究失败，仅基于已有数据）"
            
        # 2. 分析师执行追踪更新
        tracking_task = get_tracking_analysis_task(old_signal, research_context_str)
        
        logger.info(f"🧠 Tracking Phase 2: Analyst evaluating evolution...")
        
        for attempt in range(max_retries):
            try:
                response = self.analyst.run(tracking_task)
                content = response.content if hasattr(response, 'content') else str(response)
                
                json_data = extract_json(content)
                if json_data:
                    # 保持 ID 不变
                    json_data['signal_id'] = old_signal.get('signal_id', f"evolved_{int(time.time())}")
                    
                    # Sanitize
                    json_data = self._sanitize_signal_output(json_data, research_data=research_data, raw_signal=f"Tracking: {title}")
                    
                    logger.info(f"✅ Tracking completed for {title}")
                    return InvestmentSignal(**json_data)
                    
                raise ValueError("No valid JSON in tracking response")
                
            except Exception as e:
                logger.warning(f"⚠️ Tracking attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    
        return None

    def run(self, task: str) -> str:
        """通用运行入口 - 使用分析师 Agent 执行任务"""
        response = self.analyst.run(task)
        return response.content if hasattr(response, 'content') else str(response)

