# models/trading_signal.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum
import hashlib


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"
    WEAK_BUY = "WEAK_BUY"
    WEAK_SELL = "WEAK_SELL"
    NEUTRAL = "NEUTRAL"
    BREAKOUT_SUPPORT = "BREAKOUT_SUPPORT"
    BREAKOUT_RESISTANCE = "BREAKOUT_RESISTANCE"
    REJECTION_SUPPORT = "REJECTION_SUPPORT"
    REJECTION_RESISTANCE = "REJECTION_RESISTANCE"
    STRONG_MOVE_UP = "STRONG_MOVE_UP"
    STRONG_MOVE_DOWN = "STRONG_MOVE_DOWN"


@dataclass
class TradingSignal:
    """Торговый сигнал"""
    timestamp: datetime
    ticker: str
    figi: str
    signal_type: SignalType
    current_price: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.0
    reason: str = ""
    timeframe: str = "1min"
    risk_reward: float = 0.0
    level_price: Optional[float] = None  # Для пробоев - цена уровня
    candle_open: Optional[float] = None  # Цена открытия свечи
    candle_close: Optional[float] = None  # Цена закрытия свечи
    volume: Optional[int] = None  # Объем свечи
    # Поля для анализа движения
    move_percent: Optional[float] = None   # величина движения в процентах
    avg_daily_range: Optional[float] = None  # средний дневной диапазон
    threshold: Optional[float] = None       # использованный порог

    def get_signal_hash(self) -> str:
        """Создает уникальный хеш сигнала для дедупликации"""
        # Безопасное форматирование level_price (может быть None)
        level_price_str = f"{self.level_price:.4f}" if self.level_price is not None else "None"
        signal_str = f"{self.figi}_{self.signal_type.value}_{level_price_str}_{self.current_price:.4f}"
        return hashlib.md5(signal_str.encode()).hexdigest()