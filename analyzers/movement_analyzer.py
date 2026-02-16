# analyzers/movement_analyzer.py
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from typing import Dict, List, Optional, Deque
import numpy as np
from models import TradingSignal, SignalType
import config


class MovementAnalyzer:
    """
    Анализатор сильных движений цены относительно среднего дневного диапазона.
    """

    def __init__(self, threshold: float = config.MOVEMENT_THRESHOLD,
                 lookback_days: int = config.MOVEMENT_LOOKBACK_DAYS):
        self.threshold = threshold
        self.lookback_days = lookback_days
        self.daily_candles: Dict[str, Deque[Dict]] = defaultdict(lambda: deque(maxlen=lookback_days + 5))
        self.current_day_range: Dict[str, Dict[str, float]] = {}
        self.last_date: Dict[str, Optional[datetime]] = {}

    def update_daily_candle(self, figi: str, candle: Dict):
        candle_date = candle['time'].date()
        last_date = self.last_date.get(figi)

        if last_date is not None and candle_date > last_date:
            day_range = self.current_day_range.get(figi)
            if day_range:
                daily_candle = {
                    'date': last_date,
                    'low': day_range['low'],
                    'high': day_range['high'],
                    'open': day_range['open'],
                    'close': day_range['close'],
                    'range': day_range['high'] - day_range['low']
                }
                self.daily_candles[figi].append(daily_candle)

        self.last_date[figi] = candle_date

    def update_intraday(self, figi: str, candle: Dict):
        if figi not in self.current_day_range:
            self.current_day_range[figi] = {
                'low': candle['low'],
                'high': candle['high'],
                'open': candle['open'],
                'close': candle['close']
            }
        else:
            self.current_day_range[figi]['low'] = min(self.current_day_range[figi]['low'], candle['low'])
            self.current_day_range[figi]['high'] = max(self.current_day_range[figi]['high'], candle['high'])
            self.current_day_range[figi]['close'] = candle['close']

    def check_strong_move(self, figi: str, ticker: str, current_candle: Dict) -> Optional[TradingSignal]:
        day_range = self.current_day_range.get(figi)
        if not day_range:
            return None

        open_price = day_range['open']
        if open_price == 0:
            return None  # защита от деления на ноль

        current_price = current_candle['close']
        move_pct = abs(current_price - open_price) / open_price * 100

        daily_ranges = [c['range'] for c in self.daily_candles.get(figi, [])]
        if len(daily_ranges) < self.lookback_days:
            return None

        avg_daily_range = np.mean(daily_ranges[-self.lookback_days:])
        avg_range_pct = avg_daily_range / open_price * 100

        if move_pct > avg_range_pct * self.threshold:
            if current_price > open_price:
                signal_type = SignalType.STRONG_MOVE_UP
                direction = "вверх"
            else:
                signal_type = SignalType.STRONG_MOVE_DOWN
                direction = "вниз"

            confidence = min(move_pct / (avg_range_pct * self.threshold), 1.0) * 0.8 + 0.2

            reason = (f"Сильное движение {direction}: {move_pct:.2f}% от открытия, "
                      f"средний дневной диапазон {avg_range_pct:.2f}%, порог {self.threshold:.1f}x")

            signal = TradingSignal(
                timestamp=current_candle['time'],
                ticker=ticker,
                figi=figi,
                signal_type=signal_type,
                current_price=current_price,
                entry_price=current_price,
                confidence=confidence,
                reason=reason,
                timeframe="intraday",
                candle_open=current_candle['open'],
                candle_close=current_candle['close'],
                volume=current_candle['volume'],
                move_percent=move_pct,
                avg_daily_range=avg_range_pct,
                threshold=self.threshold
            )
            return signal

        return None

    def get_avg_daily_range_pct(self, figi: str, current_price: float) -> Optional[float]:
        daily_ranges = [c['range'] for c in self.daily_candles.get(figi, [])]
        if len(daily_ranges) < self.lookback_days or current_price == 0:
            return None
        avg_range = np.mean(daily_ranges[-self.lookback_days:])
        return avg_range / current_price * 100