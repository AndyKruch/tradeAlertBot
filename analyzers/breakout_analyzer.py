# analyzers/breakout_analyzer.py
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from models import TradingSignal, SignalType, SignalDeduplicator, BreakoutMonitor, PriceLevel
from utils.converters import candle_to_dict
from .movement_analyzer import MovementAnalyzer


class BreakoutAnalyzer:
    """Анализатор пробоев, отскоков и сильных движений"""

    def __init__(self, token: str):
        self.token = token
        self.breakout_monitors: Dict[str, BreakoutMonitor] = {}
        self.last_signals: Dict[str, TradingSignal] = {}
        self.signal_cooldown = timedelta(minutes=2)
        self.deduplicator = SignalDeduplicator(cooldown_seconds=60)

        # Анализатор движения
        self.movement_analyzer = MovementAnalyzer()

        # Статистика
        self.breakouts_count = 0
        self.rejections_count = 0
        self.strong_moves_count = 0
        self.filtered_signals = 0

    def initialize_instruments(self, instruments: List[Dict[str, str]]):
        for instrument in instruments:
            figi = instrument['figi']
            ticker = instrument['ticker']
            self.breakout_monitors[figi] = BreakoutMonitor(figi=figi, ticker=ticker)

    def update_levels(self, figi: str, support_levels: List[PriceLevel],
                      resistance_levels: List[PriceLevel], current_price: float):
        if figi in self.breakout_monitors:
            monitor = self.breakout_monitors[figi]
            monitor.add_levels(support_levels, resistance_levels, current_price)

    def process_candle(self, candle) -> List[TradingSignal]:
        """Обрабатывает свечу и возвращает список сигналов"""
        figi = candle.figi
        if figi not in self.breakout_monitors:
            return []

        monitor = self.breakout_monitors[figi]
        signals = []

        candle_dict = candle_to_dict(candle)
        candle_time = candle.time

        # --- Обновление данных для анализа движения ---
        self.movement_analyzer.update_intraday(figi, candle_dict)
        self.movement_analyzer.update_daily_candle(figi, candle_dict)

        # --- Проверка сильного движения ---
        move_signal = self.movement_analyzer.check_strong_move(figi, monitor.ticker, candle_dict)
        if move_signal and not self.deduplicator.is_duplicate(move_signal):
            signals.append(move_signal)
            self.strong_moves_count += 1

        # --- Проверка пробоев ---
        breakouts = monitor.check_breakout(
            candle_open=candle_dict['open'],
            candle_close=candle_dict['close'],
            candle_time=candle_time
        )

        for breakout_type, level in breakouts:
            signal = self._create_breakout_signal(
                figi=figi,
                ticker=monitor.ticker,
                breakout_type=breakout_type,
                level=level,
                candle=candle_dict,
                candle_time=candle_time
            )
            if not self.deduplicator.is_duplicate(signal):
                signals.append(signal)
                self.breakouts_count += 1
            else:
                self.filtered_signals += 1

        # --- Проверка отскоков ---
        rejections = monitor.check_rejection(
            candle_open=candle_dict['open'],
            candle_close=candle_dict['close'],
            candle_low=candle_dict['low'],
            candle_high=candle_dict['high'],
            candle_time=candle_time,
            candle_volume=candle_dict['volume']
        )

        for rejection_type, level in rejections:
            signal = self._create_rejection_signal(
                figi=figi,
                ticker=monitor.ticker,
                rejection_type=rejection_type,
                level=level,
                candle=candle_dict,
                candle_time=candle_time
            )
            if not self.deduplicator.is_duplicate(signal):
                signals.append(signal)
                self.rejections_count += 1
            else:
                self.filtered_signals += 1

        return signals

    def _create_breakout_signal(self, figi: str, ticker: str, breakout_type: str,
                                level: PriceLevel, candle: Dict, candle_time: datetime) -> TradingSignal:
        if breakout_type == "SUPPORT":
            signal_type = SignalType.BREAKOUT_SUPPORT
            direction = "📉 МЕДВЕЖИЙ ПРОБОЙ"
            reason = f"Пробитие поддержки {level.price:.2f}. Закрытие ниже уровня на {abs(candle['close'] - level.price):.2f}"
        else:
            signal_type = SignalType.BREAKOUT_RESISTANCE
            direction = "📈 БЫЧИЙ ПРОБОЙ"
            reason = f"Пробитие сопротивления {level.price:.2f}. Закрытие выше уровня на {abs(candle['close'] - level.price):.2f}"

        confidence = level.strength * 0.8 + min(abs(candle['close'] - level.price) / level.price * 100, 0.2)

        return TradingSignal(
            timestamp=candle_time,
            ticker=ticker,
            figi=figi,
            signal_type=signal_type,
            current_price=candle['close'],
            entry_price=candle['close'],
            confidence=confidence,
            reason=f"{direction}: {reason} (сила уровня: {level.strength:.2f})",
            timeframe="1min",
            level_price=level.price,
            candle_open=candle['open'],
            candle_close=candle['close'],
            volume=candle['volume']
        )

    def _create_rejection_signal(self, figi: str, ticker: str, rejection_type: str,
                                 level: PriceLevel, candle: Dict, candle_time: datetime) -> TradingSignal:
        if rejection_type == "SUPPORT_REJECTION":
            signal_type = SignalType.REJECTION_SUPPORT
            direction = "🟢 ОТСКОК ОТ ПОДДЕРЖКИ"
            price_action = f"Тестирование {level.price:.2f} с закрытием выше"
        else:
            signal_type = SignalType.REJECTION_RESISTANCE
            direction = "🔴 ОТСКОК ОТ СОПРОТИВЛЕНИЯ"
            price_action = f"Тестирование {level.price:.2f} с закрытием ниже"

        return TradingSignal(
            timestamp=candle_time,
            ticker=ticker,
            figi=figi,
            signal_type=signal_type,
            current_price=candle['close'],
            entry_price=candle['close'],
            confidence=level.strength * 0.7,
            reason=f"{direction}: {price_action} (сила уровня: {level.strength:.2f})",
            timeframe="1min",
            level_price=level.price,
            candle_open=candle['open'],
            candle_close=candle['close'],
            volume=candle['volume']
        )

    def get_statistics(self) -> Dict[str, Any]:
        return {
            'total_breakouts': self.breakouts_count,
            'total_rejections': self.rejections_count,
            'total_strong_moves': self.strong_moves_count,
            'filtered_signals': self.filtered_signals,
            'monitored_instruments': len(self.breakout_monitors),
            'breakout_stats': {
                figi: monitor.get_level_statistics()
                for figi, monitor in self.breakout_monitors.items()
            }
        }