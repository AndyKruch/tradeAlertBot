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
        # Храним историю дневных свечей для каждого инструмента (ключ: figi)
        self.daily_candles: Dict[str, Deque[Dict]] = defaultdict(lambda: deque(maxlen=lookback_days + 5))
        # Текущий внутридневной диапазон (low, high) для каждого инструмента
        self.current_day_range: Dict[str, Dict[str, float]] = {}
        # Последняя дата, для которой обновляли дневную статистику
        self.last_date: Dict[str, Optional[datetime]] = {}

    def update_daily_candle(self, figi: str, candle: Dict):
        """
        Обновляет дневную статистику по завершении торгового дня.
        Вызывается, когда получена свеча с новым днём.
        """
        candle_date = candle['time'].date()
        last_date = self.last_date.get(figi)

        if last_date is not None and candle_date > last_date:
            # Сохраняем завершённый дневной диапазон за предыдущий день
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

            # Начинаем новый день с текущей свечи
            self.current_day_range[figi] = {
                'low': candle['low'],
                'high': candle['high'],
                'open': candle['open'],
                'close': candle['close']
            }
        elif last_date is None:
            # Первый запуск, просто инициализируем диапазон текущей свечой
            self.current_day_range[figi] = {
                'low': candle['low'],
                'high': candle['high'],
                'open': candle['open'],
                'close': candle['close']
            }
        else:
            # Тот же день, диапазон будет обновлён в update_intraday
            pass

        self.last_date[figi] = candle_date

    def update_intraday(self, figi: str, candle: Dict):
        """
        Обновляет внутридневной диапазон для текущего дня.
        Вызывается для каждой новой свечи.
        """
        if figi not in self.current_day_range:
            # Если по какой-то причине диапазона ещё нет (например, не было вызова update_daily_candle),
            # инициализируем его текущей свечой.
            self.current_day_range[figi] = {
                'low': candle['low'],
                'high': candle['high'],
                'open': candle['open'],
                'close': candle['close']
            }
        else:
            # Расширяем диапазон
            self.current_day_range[figi]['low'] = min(self.current_day_range[figi]['low'], candle['low'])
            self.current_day_range[figi]['high'] = max(self.current_day_range[figi]['high'], candle['high'])
            self.current_day_range[figi]['close'] = candle['close']  # последняя цена закрытия

    def check_strong_move(self, figi: str, ticker: str, current_candle: Dict) -> Optional[TradingSignal]:
        """
        Проверяет, является ли текущее движение сильным (превышает порог от среднего дневного диапазона).
        Возвращает сигнал, если условие выполняется.
        """
        # Получаем текущий внутридневной диапазон
        day_range = self.current_day_range.get(figi)
        if not day_range:
            return None

        # Текущее движение от открытия дня
        open_price = day_range['open']
        current_price = current_candle['close']  # используем close последней свечи
        move_pct = abs(current_price - open_price) / open_price * 100

        # Рассчитываем средний дневной диапазон за последние lookback_days
        daily_ranges = [c['range'] for c in self.daily_candles.get(figi, [])]
        if len(daily_ranges) < self.lookback_days:
            return None  # недостаточно данных

        avg_daily_range = np.mean(daily_ranges[-self.lookback_days:])
        avg_range_pct = avg_daily_range / open_price * 100

        # Проверяем превышение порога
        if move_pct > avg_range_pct * self.threshold:
            # Определяем направление
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
        """
        Возвращает средний дневной диапазон в процентах от текущей цены.
        Если данных недостаточно, возвращает None.
        """
        daily_ranges = [c['range'] for c in self.daily_candles.get(figi, [])]
        if len(daily_ranges) < self.lookback_days or current_price == 0:
            return None
        avg_range = np.mean(daily_ranges[-self.lookback_days:])
        return avg_range / current_price * 100