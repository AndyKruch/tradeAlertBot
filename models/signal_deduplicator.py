# models/signal_deduplicator.py
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple
from .trading_signal import TradingSignal


class SignalDeduplicator:
    """Класс для дедупликации сигналов"""

    def __init__(self, cooldown_seconds: int = 60):
        self.cooldown_seconds = cooldown_seconds
        self.signal_history: Dict[str, datetime] = {}
        self.level_cooldown: Dict[Tuple[str, str, float], datetime] = {}

    def is_duplicate(self, signal: TradingSignal) -> bool:
        """Проверяет, является ли сигнал дубликатом"""
        current_time = datetime.now(timezone.utc)

        # Проверка по хешу сигнала
        signal_hash = signal.get_signal_hash()
        if signal_hash in self.signal_history:
            last_time = self.signal_history[signal_hash]
            if (current_time - last_time).total_seconds() < self.cooldown_seconds:
                return True

        # Проверка по уровню и типу сигнала
        level_key = (signal.figi, signal.signal_type.value, round(signal.level_price, 4) if signal.level_price else 0)
        if level_key in self.level_cooldown:
            last_time = self.level_cooldown[level_key]
            if (current_time - last_time).total_seconds() < self.cooldown_seconds:
                return True

        # Обновляем историю
        self.signal_history[signal_hash] = current_time
        if signal.level_price:
            self.level_cooldown[level_key] = current_time

        # Очищаем старые записи
        self._cleanup_old_entries(current_time)

        return False

    def _cleanup_old_entries(self, current_time: datetime):
        """Очищает старые записи из истории"""
        expired_hashes = [
            h for h, t in self.signal_history.items()
            if (current_time - t).total_seconds() > self.cooldown_seconds * 2
        ]
        for h in expired_hashes:
            del self.signal_history[h]

        expired_levels = [
            k for k, t in self.level_cooldown.items()
            if (current_time - t).total_seconds() > self.cooldown_seconds * 2
        ]
        for k in expired_levels:
            del self.level_cooldown[k]