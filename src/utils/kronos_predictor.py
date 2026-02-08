import torch
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional
from loguru import logger
from pandas.tseries.offsets import BusinessDay
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fix for Kronos internal imports
import sys
import os
KRONOS_DIR = os.path.join(os.path.dirname(__file__), 'predictor')
if KRONOS_DIR not in sys.path:
    sys.path.append(KRONOS_DIR)

import glob
from sentence_transformers import SentenceTransformer

from utils.predictor.model import Kronos, KronosTokenizer, KronosPredictor
from schema.models import KLinePoint

class KronosPredictorUtility:
    """
    Kronos 时序预测工具类
    负责模型加载、推理以及数据结构转换
    """
    _instance = None
    _predictor = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KronosPredictorUtility, cls).__new__(cls)
        return cls._instance

    def __init__(self, device: Optional[str] = None):
        if self._predictor is not None:
            return
            
        try:
            if not device:
                device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            
            logger.info(f"🔮 Loading Kronos Model on {device}...")
            
            # 1. Load Embedder (SentenceTransformer)
            model_name = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')  # Match training
            try:
                self.embedder = SentenceTransformer(model_name, device=device, local_files_only=True)
            except Exception:
                logger.warning(f"⚠️ Local embedder {model_name} not found. Downloading...")
                self.embedder = SentenceTransformer(model_name, device=device)

            # 2. Load Kronos Base
            try:
                tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base", local_files_only=True)
                model = Kronos.from_pretrained("NeoQuasar/Kronos-base", local_files_only=True)
            except Exception:
                logger.warning("⚠️ Local Kronos cache not found. Attempting to download...")
                tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
                model = Kronos.from_pretrained("NeoQuasar/Kronos-base")
            
            # 3. Load Trained News Projector Weights
            # Check explicit model path first, otherwise fallback to latest in exports/models
            PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            models_dir = os.path.join(PROJECT_ROOT, "exports/models")
            explicit_model = os.getenv("KRONOS_NEWS_MODEL_PATH", "").strip()
            model_files = glob.glob(os.path.join(models_dir, "*.pt"))

            selected_model = None
            if explicit_model and os.path.exists(explicit_model):
                selected_model = explicit_model
            elif model_files:
                selected_model = max(model_files, key=os.path.getctime)

            if selected_model:
                logger.info(f"🔄 Loading trained news weights from {selected_model}...")
                try:
                    checkpoint = torch.load(selected_model, map_location=device)
                    # The checkpoint contains 'news_proj_state_dict'
                    if 'news_proj_state_dict' in checkpoint:
                        # Ensure model has news_proj initialized with correct dim if needed (usually handled by config but good to be safe)
                        # Kronos init usually sets news_proj if news_dim is passed. 
                        # But here we loaded from pretrained which might have different config.
                        # We need to manually re-init news_proj if it's None or shaped differently, 
                        # but standard Kronos loading should be fine if we just load state dict.
                        # Wait, original Kronos init might not have `news_dim` set if loaded from HF config without it.
                        # We need to check if we need to re-init the layer.
                        if not hasattr(model, 'news_proj') or model.news_proj is None:
                            import torch.nn as nn
                            news_dim = checkpoint.get('news_dim', 384)
                            model.news_proj = nn.Linear(news_dim, model.d_model).to(device)
                        
                        model.news_proj.load_state_dict(checkpoint['news_proj_state_dict'])
                        logger.success("✅ News-Aware Projection Layer loaded!")
                        self.has_news_model = True
                    else:
                        logger.warning("⚠️ Checkpoint found but missing 'news_proj_state_dict'. Using base model.")
                        self.has_news_model = False
                except Exception as e:
                    logger.error(f"❌ Failed to load trained weights: {e}. Using base model.")
                    self.has_news_model = False
            else:
                logger.info("ℹ️ No trained news models found. Using base model.")
                self.has_news_model = False
            
            tokenizer = tokenizer.to(device)
            model = model.to(device)
            
            self._predictor = KronosPredictor(model, tokenizer, device=device, max_context=512)
            logger.info("✅ Kronos Model loaded successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to load Kronos Model: {e}")
            self._predictor = None
            self.has_news_model = False

    def get_base_forecast(self, df: pd.DataFrame, lookback: int = 20, pred_len: int = 5, news_text: Optional[str] = None) -> List[KLinePoint]:
        """
        生成原始模型预测
        """
        if self._predictor is None:
            logger.error("Predictor not initialized.")
            return []

        if len(df) < lookback:
            logger.warning(f"Insufficient historical data ({len(df)}) for lookback ({lookback}).")
            return []

        # 获取最后 lookback 条数据
        x_df = df.iloc[-lookback:].copy()
        x_timestamp = pd.to_datetime(x_df['date']) # Ensure datetime
        last_date = x_timestamp.iloc[-1]
        
        # 生成未来时间戳
        future_dates = pd.date_range(start=last_date + BusinessDay(1), periods=pred_len, freq='B')
        y_timestamp = pd.Series(future_dates)

        # Embedding News if available
        news_emb = None
        if news_text and getattr(self, 'has_news_model', False) and hasattr(self, 'embedder'):
            try:
                # Truncate to avoid too long text
                emb = self.embedder.encode(news_text[:1000])
                news_emb = emb # KronosPredictor expects numpy array or tensor
            except Exception as e:
                logger.error(f"Failed to encode news: {e}")

        try:
            # 预测所需的列
            cols = ['open', 'high', 'low', 'close', 'volume']
            pred_df = self._predictor.predict(
                df=x_df[cols],
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=1.0, 
                top_p=0.9, 
                sample_count=1,
                verbose=False,
                news_emb=news_emb
            )
            
            # 转换为 KLinePoint
            results = []
            for date, row in pred_df.iterrows():
                results.append(KLinePoint(
                    date=date.strftime("%Y-%m-%d"),
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=float(row['volume'])
                ))
            return results
        except Exception as e:
            logger.error(f"Forecast generation failed: {e}")
            return []

# Singleton instance for easy access
# Usage: predictor = KronosPredictorUtility()
