# trading/paper_trading.py
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, List, Any

from models import SignalType


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
    def __init__(self, breakout_analyzer, contracts: int = 1, tp_points: float = 10.0):
        self.breakout_analyzer = breakout_analyzer
        self.contracts = contracts
        self.tp_points = tp_points
        self.positions: Dict[str, Position] = {}       # figi -> Position
        self.closed_positions: List[Position] = []     # история закрытых

    def on_candle(self, candle_dict: Dict[str, Any], signals: List, figi: str):
        """Обработка новой свечи"""
        # Сначала проверяем существующую позицию на TP/SL
        if figi in self.positions:
            self._check_tp_sl(figi, candle_dict)

        # Затем проверяем сигналы на вход (только если нет позиции)
        if figi not in self.positions:
            self._check_entry_signals(figi, signals, candle_dict)

    def on_levels_updated(self, figi: str):
        """Обновление уровней для инструмента – пересчёт take profit для открытой позиции"""
        if figi in self.positions:
            self._update_take_profit(figi)

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

    def _check_entry_signals(self, figi: str, signals: List, candle_dict: Dict[str, Any]):
        """Открытие позиции по сигналам пробоя"""
        for signal in signals:
            if signal.signal_type == SignalType.BREAKOUT_RESISTANCE:
                self._open_position(
                    figi=figi,
                    direction="LONG",
                    entry_price=signal.current_price,
                    entry_level=signal.level_price,
                    reason="пробитие сопротивления",
                    timestamp=signal.timestamp
                )
                break
            elif signal.signal_type == SignalType.BREAKOUT_SUPPORT:
                self._open_position(
                    figi=figi,
                    direction="SHORT",
                    entry_price=signal.current_price,
                    entry_level=signal.level_price,
                    reason="пробитие поддержки",
                    timestamp=signal.timestamp
                )
                break

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

        self._print_trade(timestamp, ticker, direction, self.contracts, entry_price, reason)

    def _close_position(self, figi: str, reason: str, price: float, timestamp: datetime):
        if figi not in self.positions:
            return
        pos = self.positions.pop(figi)
        pos.exit_price = price
        pos.exit_time = timestamp
        pos.exit_reason = reason
        self.closed_positions.append(pos)

        self._print_trade(timestamp, pos.ticker, pos.direction, pos.contracts, price, reason)

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
                # Берём ближайшее сопротивление (единственный активный уровень)
                resistance = monitor.active_resistance_levels[0]
                pos.tp_price = resistance.price - self.tp_points
            else:
                pos.tp_price = None
        else:  # SHORT
            if monitor.active_support_levels:
                support = monitor.active_support_levels[0]
                pos.tp_price = support.price + self.tp_points
            else:
                pos.tp_price = None

    def _print_trade(self, timestamp: datetime, ticker: str, direction: str,
                     contracts: int, price: float, reason: str):
        """Вывод информации о сделке в консоль в требуемом формате"""
        time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{time_str}; {ticker}; {direction}; {contracts}; {price:.2f}; {reason}")