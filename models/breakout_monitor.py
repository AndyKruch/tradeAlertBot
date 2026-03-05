# models/breakout_monitor.py
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Deque, Tuple, Optional
from collections import deque
from .price_level import PriceLevel, PriceLevelCluster


@dataclass
class BreakoutMonitor:
    """Мониторинг пробоев уровней"""
    figi: str
    ticker: str
    active_support_levels: List[PriceLevel] = field(default_factory=list)
    active_resistance_levels: List[PriceLevel] = field(default_factory=list)
    broken_support_levels: List[PriceLevel] = field(default_factory=list)
    broken_resistance_levels: List[PriceLevel] = field(default_factory=list)
    recent_signals: Deque[Tuple[datetime, str, float]] = field(default_factory=lambda: deque(maxlen=20))

    # Параметры для предотвращения ложных срабатываний
    min_candle_size: float = 0.001  # Минимальный размер свечи (0.1%)
    confirmation_period: int = 2  # Период подтверждения в свечах
    max_level_age_hours: int = 24  # Максимальный возраст уровня в часах
    price_range_percentage: float = 20.0  # Диапазон цены для актуальных уровней (в %)
    merge_threshold: float = 0.002  # Порог объединения близких уровней (0.2%)
    min_level_strength: float = 0.6  # Минимальная сила уровня для мониторинга

    def __post_init__(self):
        self.level_cluster = PriceLevelCluster(merge_threshold=self.merge_threshold)

    def add_levels(self, supports: List[PriceLevel], resistances: List[PriceLevel], current_price: float):
        """Добавляет новые уровни для мониторинга, объединяя близкие, и оставляет только ближайшие."""
        current_time = datetime.now(timezone.utc)

        # Фильтруем устаревшие уровни
        self._filter_old_levels(current_time)

        # Диапазон цены для актуальных уровней (в абсолютных единицах)
        price_range = current_price * (self.price_range_percentage / 100.0)

        # Допуск для учёта небольших отклонений
        epsilon = 0.001  # 0.1%

        # Фильтруем поддержки: должны быть НИЖЕ или равны текущей цене (с учётом epsilon)
        filtered_supports = []
        for s in supports:
            if s.strength >= self.min_level_strength:
                if s.price <= current_price * (1 + epsilon):
                    if abs(s.price - current_price) <= price_range:
                        filtered_supports.append(s)

        # Фильтруем сопротивления: должны быть ВЫШЕ или равны текущей цене
        filtered_resistances = []
        for r in resistances:
            if r.strength >= self.min_level_strength:
                if r.price >= current_price * (1 - epsilon):
                    if abs(r.price - current_price) <= price_range:
                        filtered_resistances.append(r)

        # Кластеризуем новые уровни
        clustered_supports = self.level_cluster.cluster_levels(filtered_supports, current_price)
        clustered_resistances = self.level_cluster.cluster_levels(filtered_resistances, current_price)

        # Объединяем старые и новые уровни поддержки
        for new_support in clustered_supports:
            self._merge_or_add_level(self.active_support_levels, new_support, current_time)

        # Объединяем старые и новые уровни сопротивления
        for new_resistance in clustered_resistances:
            self._merge_or_add_level(self.active_resistance_levels, new_resistance, current_time)

        # --- НОВЫЙ БЛОК: оставляем только ближайшие уровни ---
        # Поддержки: выбираем самую высокую цену среди нижележащих
        if self.active_support_levels:
            valid_supports = [l for l in self.active_support_levels if l.price < current_price]
            if valid_supports:
                closest_support = max(valid_supports, key=lambda l: l.price)
                self.active_support_levels = [closest_support]
            else:
                self.active_support_levels = []
        else:
            self.active_support_levels = []

        # Сопротивления: выбираем самую низкую цену среди вышележащих
        if self.active_resistance_levels:
            valid_resistances = [l for l in self.active_resistance_levels if l.price > current_price]
            if valid_resistances:
                closest_resistance = min(valid_resistances, key=lambda l: l.price)
                self.active_resistance_levels = [closest_resistance]
            else:
                self.active_resistance_levels = []
        else:
            self.active_resistance_levels = []
        # --- КОНЕЦ НОВОГО БЛОКА ---

        # Сортируем уровни по силе (для порядка)
        self.active_support_levels.sort(key=lambda x: x.strength, reverse=True)
        self.active_resistance_levels.sort(key=lambda x: x.strength, reverse=True)

    def _merge_or_add_level(self, existing_levels: List[PriceLevel], new_level: PriceLevel, current_time: datetime):
        """Объединяет близкие уровни или добавляет новый"""
        merge_threshold_pct = self.merge_threshold

        # Ищем близкий существующий уровень
        closest_level = None
        min_diff = float('inf')

        for existing in existing_levels:
            price_diff_pct = abs(existing.price - new_level.price) / existing.price if existing.price > 0 else 0
            if price_diff_pct < merge_threshold_pct and price_diff_pct < min_diff:
                closest_level = existing
                min_diff = price_diff_pct

        if closest_level:
            # Объединяем с существующим уровнем
            total_strength = closest_level.strength + new_level.strength
            closest_level.price = (closest_level.price * closest_level.strength +
                                   new_level.price * new_level.strength) / total_strength
            closest_level.strength = min(closest_level.strength + 0.1, 1.0)
            closest_level.touches += new_level.touches
            closest_level.times_tested += new_level.times_tested
            closest_level.last_touch_time = current_time
            closest_level.is_fresh = True
            closest_level.created_time = min(closest_level.created_time, new_level.created_time)
        else:
            new_level.last_touch_time = current_time
            new_level.is_fresh = True
            existing_levels.append(new_level)

    def _filter_old_levels(self, current_time: datetime):
        """Фильтрует устаревшие уровни"""
        max_age = timedelta(hours=self.max_level_age_hours)
        self.active_support_levels = [
            level for level in self.active_support_levels
            if (current_time - level.created_time) <= max_age
        ]
        self.active_resistance_levels = [
            level for level in self.active_resistance_levels
            if (current_time - level.created_time) <= max_age
        ]

    def check_breakout(self, candle_open: float, candle_close: float,
                       candle_time: datetime) -> List[Tuple[str, PriceLevel]]:
        """Проверяет пробои уровней на свече (смягчённые условия)"""
        breakouts = []
        candle_size = abs(candle_close - candle_open) / candle_open if candle_open > 0 else 0
        if candle_size < self.min_candle_size:
            return breakouts

        breakout_threshold = 0.003  # 0.3%

        for level in self.active_support_levels:
            if level.price <= 0:
                continue
            threshold_price = level.price * (1 - breakout_threshold)
            if candle_close < threshold_price:
                if not self._has_recent_signal("BREAKOUT_SUPPORT", level.price, candle_time):
                    breakouts.append(("SUPPORT", level))
                    self._mark_level_broken(level, "SUPPORT", candle_time)

        for level in self.active_resistance_levels:
            if level.price <= 0:
                continue
            threshold_price = level.price * (1 + breakout_threshold)
            if candle_close > threshold_price:
                if not self._has_recent_signal("BREAKOUT_RESISTANCE", level.price, candle_time):
                    breakouts.append(("RESISTANCE", level))
                    self._mark_level_broken(level, "RESISTANCE", candle_time)

        return breakouts

    def check_rejection(self, candle_open: float, candle_close: float,
                        candle_low: float, candle_high: float,
                        candle_time: datetime, candle_volume: int = 0) -> List[Tuple[str, PriceLevel]]:
        """Проверяет отскоки от уровней"""
        rejections = []
        candle_size = abs(candle_close - candle_open) / candle_open if candle_open > 0 else 0
        if candle_size < self.min_candle_size:
            return rejections

        for level in self.active_support_levels:
            if abs(candle_low - level.price) / level.price < 0.002:
                if candle_close > level.price and candle_open > level.price:
                    level.last_touch_time = candle_time
                    level.times_tested += 1
                    if not self._has_recent_signal("REJECTION_SUPPORT", level.price, candle_time):
                        rejections.append(("SUPPORT_REJECTION", level))

        for level in self.active_resistance_levels:
            if abs(candle_high - level.price) / level.price < 0.002:
                if candle_close < level.price and candle_open < level.price:
                    level.last_touch_time = candle_time
                    level.times_tested += 1
                    if not self._has_recent_signal("REJECTION_RESISTANCE", level.price, candle_time):
                        rejections.append(("RESISTANCE_REJECTION", level))

        return rejections

    def _has_recent_signal(self, signal_type: str, level_price: float, timestamp: datetime) -> bool:
        for signal_time, sig_type, sig_price in self.recent_signals:
            time_diff = (timestamp - signal_time).total_seconds()
            price_diff = abs(sig_price - level_price) / level_price if level_price > 0 else 0
            if sig_type == signal_type and price_diff < 0.001 and time_diff < 60:
                return True
        return False

    def _mark_level_broken(self, level: PriceLevel, level_type: str, timestamp: datetime):
        signal_type = "BREAKOUT_SUPPORT" if level_type == "SUPPORT" else "BREAKOUT_RESISTANCE"
        self.recent_signals.append((timestamp, signal_type, level.price))

        if level_type == "SUPPORT":
            if level not in self.broken_support_levels:
                self.broken_support_levels.append(level)
            self.active_support_levels = [l for l in self.active_support_levels if l.price != level.price]
        else:
            if level not in self.broken_resistance_levels:
                self.broken_resistance_levels.append(level)
            self.active_resistance_levels = [l for l in self.active_resistance_levels if l.price != level.price]

    def get_level_statistics(self) -> Dict[str, Any]:
        return {
            'active_supports': len(self.active_support_levels),
            'active_resistances': len(self.active_resistance_levels),
            'broken_supports': len(self.broken_support_levels),
            'broken_resistances': len(self.broken_resistance_levels),
            'recent_signals': list(self.recent_signals)
        }

    def get_formatted_levels(self) -> Dict[str, str]:
        supports_str = ", ".join(
            [f"{l.price:.3f}" for l in self.active_support_levels]) if self.active_support_levels else "нет"
        resistances_str = ", ".join(
            [f"{l.price:.3f}" for l in self.active_resistance_levels]) if self.active_resistance_levels else "нет"
        return {'supports': supports_str, 'resistances': resistances_str}

    def get_levels_info(self) -> Dict[str, List[Dict[str, Any]]]:
        supports_info = []
        for level in self.active_support_levels:
            supports_info.append({
                'price': level.price,
                'strength': level.strength,
                'touches': level.touches,
                'times_tested': level.times_tested,
                'age_hours': (datetime.now(timezone.utc) - level.created_time).total_seconds() / 3600,
                'is_fresh': level.is_fresh,
                'cluster_id': level.cluster_id
            })

        resistances_info = []
        for level in self.active_resistance_levels:
            resistances_info.append({
                'price': level.price,
                'strength': level.strength,
                'touches': level.touches,
                'times_tested': level.times_tested,
                'age_hours': (datetime.now(timezone.utc) - level.created_time).total_seconds() / 3600,
                'is_fresh': level.is_fresh,
                'cluster_id': level.cluster_id
            })

        return {'supports': supports_info, 'resistances': resistances_info}