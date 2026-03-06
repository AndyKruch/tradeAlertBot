# trading/paper_trading.py
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, List, Any, Tuple

from models import SignalType, TradingSignal


@dataclass
class Position:
    figi: str
    ticker: str
    direction: str          # "LONG" или "SHORT"
    entry_price: float
    entry_level: float       # уровень, который был пробит (для стопа)
    contracts: int
    open_time: datetime
    tp_price: Optional[float] = None
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None


class PaperTradingEngine:
    def __init__(self, breakout_analyzer, logger, contracts: int = 1, tp_points: float = 10.0):
        self.breakout_analyzer = breakout_analyzer
        self.logger = logger
        self.contracts = contracts
        self.tp_points = tp_points
        self.positions: Dict[str, Position] = {}                 # figi -> Position
        self.closed_positions: List[Position] = []               # история закрытых
        self.pending_signals: Dict[str, TradingSignal] = {}      # figi -> сигнал на вход (ожидает следующей свечи)

    def on_candle(self, candle_dict: Dict[str, Any], signals: List[TradingSignal], figi: str):
        """Обработка новой свечи (уже закрытой)"""
        # 1. Проверяем отложенные сигналы (с предыдущей свечи)
        self._process_pending_signals(figi, candle_dict)

        # 2. Проверяем текущую позицию на TP/SL
        if figi in self.positions:
            self._check_tp_sl(figi, candle_dict)

        # 3. Сохраняем новые сигналы (от текущей свечи) в ожидание на следующую свечу
        self._add_pending_signals(figi, signals)

    def on_levels_updated(self, figi: str):
        """Обновление уровней для инструмента – пересчёт take profit для открытой позиции"""
        if figi in self.positions:
            self._update_take_profit(figi)

    def _process_pending_signals(self, figi: str, candle_dict: Dict[str, Any]):
        """Обработка отложенного сигнала для входа по текущей свече"""
        if figi not in self.pending_signals:
            return
        if figi in self.positions:
            # Уже есть позиция – сигнал недействителен
            del self.pending_signals[figi]
            return

        signal = self.pending_signals[figi]
        open_price = candle_dict['open']
        current_time = candle_dict['time']

        direction = None
        reason = None

        if signal.signal_type == SignalType.BREAKOUT_RESISTANCE and open_price >= signal.current_price:
            direction = "LONG"
            reason = "пробитие сопротивления"
        elif signal.signal_type == SignalType.BREAKOUT_SUPPORT and open_price <= signal.current_price:
            direction = "SHORT"
            reason = "пробитие поддержки"

        if direction is not None:
            self._open_position(
                figi=figi,
                direction=direction,
                entry_price=open_price,
                entry_level=signal.level_price,
                reason=reason,
                timestamp=current_time
            )
        # В любом случае удаляем обработанный сигнал
        del self.pending_signals[figi]

    def _add_pending_signals(self, figi: str, signals: List[TradingSignal]):
        if figi in self.positions:
            # print(f"DEBUG: {figi} уже есть позиция, сигналы игнорируются")
            return
        # print(f"DEBUG: _add_pending_signals для {figi}, получено {len(signals)} сигналов")
        for signal in signals:
            # print(f"  сигнал: {signal.signal_type}, цена закрытия={signal.current_price:.2f}")
            if signal.signal_type in (SignalType.BREAKOUT_RESISTANCE, SignalType.BREAKOUT_SUPPORT):
                self.pending_signals[figi] = signal
                # print(f"  -> добавлен в pending_signals")
                break

    def _check_tp_sl(self, figi: str, candle_dict: Dict[str, Any]):
        pos = self.positions[figi]
        high = candle_dict['high']
        low = candle_dict['low']
        close = candle_dict['close']
        current_time = candle_dict['time']

        # Take profit
        tp_triggered = False
        tp_price = None
        if pos.direction == "LONG" and pos.tp_price is not None:
            if high >= pos.tp_price:
                tp_triggered = True
                tp_price = pos.tp_price
        elif pos.direction == "SHORT" and pos.tp_price is not None:
            if low <= pos.tp_price:
                tp_triggered = True
                tp_price = pos.tp_price

        if tp_triggered:
            self._close_position(figi, "take profit", tp_price, current_time)
            return

        # Stop loss
        sl_triggered = False
        sl_price = None
        if pos.direction == "LONG":
            if close < pos.entry_level:
                sl_triggered = True
                sl_price = close
        elif pos.direction == "SHORT":
            if close > pos.entry_level:
                sl_triggered = True
                sl_price = close

        if sl_triggered:
            self._close_position(figi, "stop loss", sl_price, current_time)

    def _open_position(self, figi: str, direction: str, entry_price: float,
                       entry_level: float, reason: str, timestamp: datetime):
        if figi in self.positions:
            return

        monitor = self.breakout_analyzer.breakout_monitors.get(figi)
        if not monitor:
            return

        ticker = monitor.ticker

        pos = Position(
            figi=figi,
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            entry_level=entry_level,
            contracts=self.contracts,
            open_time=timestamp
        )
        self.positions[figi] = pos

        self._update_take_profit(figi)

        self._print_trade(timestamp, ticker, direction, self.contracts, entry_price, entry_level, reason)

    def _close_position(self, figi: str, reason: str, price: float, timestamp: datetime):
        if figi not in self.positions:
            return
        pos = self.positions.pop(figi)
        pos.exit_price = price
        pos.exit_time = timestamp
        pos.exit_reason = reason
        self.closed_positions.append(pos)

        # Определяем цену уровня для вывода
        if reason == "take profit":
            level_price = pos.tp_price
        else:  # stop loss
            level_price = pos.entry_level

        self._print_trade(timestamp, pos.ticker, pos.direction, pos.contracts, price, level_price, reason)

    def _update_take_profit(self, figi: str):
        """Обновить цену take profit на основе актуальных уровней"""
        if figi not in self.positions:
            return
        pos = self.positions[figi]
        monitor = self.breakout_analyzer.breakout_monitors.get(figi)
        if not monitor:
            return

        if pos.direction == "LONG":
            if monitor.active_resistance_levels:
                resistance = monitor.active_resistance_levels[0]
                pos.tp_price = resistance.price - self.tp_points
                # дополнительная проверка (необязательно)
                if pos.tp_price <= pos.entry_price:
                    pos.tp_price = pos.entry_price + self.tp_points
            else:
                pos.tp_price = None
        else:  # SHORT
            if monitor.active_support_levels:
                support = monitor.active_support_levels[0]
                pos.tp_price = support.price - self.tp_points  # ИСПРАВЛЕНО: минус вместо плюса
                if pos.tp_price >= pos.entry_price:
                    pos.tp_price = pos.entry_price - self.tp_points
            else:
                pos.tp_price = None

    def _print_trade(self, timestamp: datetime, ticker: str, direction: str,
                     contracts: int, price: float, level_price: float, reason: str):
        time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        # вывод в консоль
        print(f"{time_str}; {ticker}; {direction}; {contracts}; {price:.2f}; {level_price:.2f}; {reason}")
        # асинхронная запись в CSV
        asyncio.create_task(self.logger.log_trade(
            timestamp, ticker, direction, contracts, price, level_price, reason
        ))
