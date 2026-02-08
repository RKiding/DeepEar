import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger

from utils.kronos_predictor import KronosPredictorUtility
from utils.json_utils import extract_json
from utils.database_manager import DatabaseManager
from schema.models import ForecastResult, KLinePoint, InvestmentSignal
from prompts.forecast_analyst import get_forecast_adjustment_instructions, get_forecast_task

class ForecastAgent:
    """
    预测智能体 (ForecastAgent)
    协调 Kronos 模型进行时序预测，并让 LLM 结合新闻背景进行调整。
    """
    
    def __init__(self, db: DatabaseManager, model: Model):
        self.db = db
        self.model = model
        self.predictor_util = KronosPredictorUtility() # Singleton
        
        # 调整智能体
        self.adjuster = Agent(
            model=self.model,
            instructions=["你是一个专业的 K 线趋势修正专家。"],
            markdown=False,
            debug_mode=True,
            tool_call_limit=3
        )

    def generate_forecast(
        self,
        ticker: str,
        signals: List[InvestmentSignal],
        lookback: int = 20,
        pred_len: int = 5,
        extra_context: str = "",
    ) -> Optional[ForecastResult]:
        """
        生成完整的预测流程：模型预测 -> LLM 调整
        """
        logger.info(f"🔮 Generating forecast for {ticker}...")
        
        # 1. 获取历史数据
        from utils.stock_tools import StockTools
        stock_tools = StockTools(self.db, auto_update=False)
        
        # 获取足够的数据进行 lookback
        import pandas as pd
        end_date = datetime.now().strftime("%Y-%m-%d")
        # 宽放一点时间以确保有足够的交易日
        start_date = (datetime.now() - pd.Timedelta(days=max(lookback * 4, 90))).strftime("%Y-%m-%d")
        df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date)

        # Retry strategy:
        # 1) If not enough history, force-sync from network once.
        # 2) If still not enough, degrade lookback to the maximum available length.
        if df.empty or len(df) < lookback:
            logger.warning(
                f"⚠️ Not enough history for {ticker} (need {lookback}, got {len(df)}). Forcing network sync..."
            )
            df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date, force_sync=True)

        if df.empty:
            logger.warning(f"⚠️ No history data for {ticker} after sync")
            return None

        # Absolute minimum history needed to produce a reasonable forecast.
        # If we have fewer than this, forecasting is likely unstable.
        min_lookback = 10
        effective_lookback = lookback
        if len(df) < lookback:
            if len(df) < min_lookback:
                logger.warning(
                    f"⚠️ Not enough history for {ticker} even after sync (need >= {min_lookback}, got {len(df)})"
                )
                return None
            effective_lookback = len(df)
            logger.warning(
                f"⚠️ Using degraded lookback for {ticker}: {effective_lookback} (desired {lookback})"
            )

        # 2. 准备信号上下文 (提前到预测之前，因为 news-aware model 需要它)
        signal_lines = []
        for s in (signals or []):
            try:
                if isinstance(s, dict):
                    title = s.get('title', '')
                    summary = s.get('summary', '')
                else:
                    title = getattr(s, 'title', '')
                    summary = getattr(s, 'summary', '')
                if title or summary:
                    signal_lines.append(f"- {title}: {summary}")
            except Exception:
                continue

        signals_context = "\n".join(signal_lines).strip()
        
        # 3. 模型预测 (Two-Pass: Technical & News-Adjusted)
        # Pass 1: Pure Technical
        tech_points = self.predictor_util.get_base_forecast(df, lookback=effective_lookback, pred_len=pred_len, news_text=None)
        
        # Pass 2: News-Adjusted (Only if we have signals context)
        news_points = []
        if signals_context:
            news_points = self.predictor_util.get_base_forecast(df, lookback=effective_lookback, pred_len=pred_len, news_text=signals_context)
        
        if not tech_points:
            logger.warning(f"⚠️ Failed to get base forecast for {ticker}")
            return None

        # Determine if we successfully got a different news forecast
        has_news_forecast = False
        if news_points and news_points != tech_points:
             has_news_forecast = True
        else:
             news_points = tech_points # Fallback

        # 4. LLM Rationale Generation (Formerly Adjustment)
        
        ctx_parts = []
        if effective_lookback != lookback:
            ctx_parts.append(
                f"【数据质量提示】历史数据不足：仅 {len(df)} 条，使用可用最长窗口 lookback={effective_lookback} 生成预测。"
            )
        if signals_context:
            ctx_parts.append("【相关结构化信号摘要（较高可信）】\n" + signals_context)
        
        if has_news_forecast:
             # Add the specific quantitative adjustment to context for LLM to analyze
             # Convert news_points to string
             news_forecast_str = "\n".join([f"Day {i+1}: Open={p.open:.2f}, Close={p.close:.2f}" for i, p in enumerate(news_points)])
             ctx_parts.append(f"【Kronos模型定量修正预测】\n基于上述新闻训练的专用模型已给出以下修正后走势，请重点分析此走势与纯技术面预测的差异合理性：\n{news_forecast_str}")

        if extra_context:
            ctx_parts.append(extra_context)

        final_context = "\n\n".join(ctx_parts).strip() or "（无额外上下文）"
        
        # We pass 'tech_points' as the base to the prompt.
        # If 'has_news_forecast' is True, the LLM sees the 'correction' in the context and should align with it.
        adjust_instructions = get_forecast_adjustment_instructions(ticker, final_context, tech_points)
        self.adjuster.instructions = [adjust_instructions]
        
        try:
            response = self.adjuster.run(get_forecast_task())
            content = response.content if hasattr(response, 'content') else str(response)
            
            adjust_data = extract_json(content)
            
            # Key Change: If we have a robust News Model forecast, we prefer it over LLM's hallucinated numbers,
            # unless the LLM suggests minor refinements (which it might).
            # But to be safe and use our trained model, we should verify if LLM output is drastically different.
            # For now, let's trust the LLM's output because the prompt asks it to "output the valid forecast".
            # Since we fed the 'News Forecast' into the context, a smart LLM should adopt it.
            
            if adjust_data and "adjusted_forecast" in adjust_data:
                final_points = [KLinePoint(**p) for p in adjust_data["adjusted_forecast"]]
                rationale = adjust_data.get("rationale", "LLM subjectively adjusted based on news context.")
                
                return ForecastResult(
                    ticker=ticker,
                    base_forecast=tech_points, # Always show the technical baseline
                    adjusted_forecast=final_points, # LLM's final call (influenced by News Model)
                    rationale=rationale
                )
            else:
                # If LLM fails to output valid JSON, but we have a news forecast, use it.
                if has_news_forecast:
                    logger.warning(f"⚠️ LLM json parsing failed for {ticker}, but we have News Model forecast. Using that.")
                    return ForecastResult(
                        ticker=ticker,
                        base_forecast=tech_points,
                        adjusted_forecast=news_points,
                        rationale="LLM parsing failed. Reverted to Kronos News-Aware Model output."
                    )
                else:
                    return ForecastResult(
                        ticker=ticker,
                        base_forecast=tech_points,
                        adjusted_forecast=tech_points,
                        rationale="Fallback: LLM adjustment failed."
                    )
                
        except Exception as e:
            logger.error(f"❌ Error during forecast adjustment for {ticker}: {e}")
            return ForecastResult(
                ticker=ticker,
                base_forecast=base_points,
                adjusted_forecast=base_points,
                rationale=f"Error: {e}"
            )
