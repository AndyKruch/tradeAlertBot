# models/price_level.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import numpy as np


@dataclass
class PriceLevel:
    """Класс для хранения уровня цены"""
    price: float
    strength: float  # Сила уровня (0-1)
    time_frame: str  # Таймфрейм
    touches: int  # Количество касаний
    is_fresh: bool  # Уровень сформирован недавно
    created_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_touch_time: Optional[datetime] = None
    times_tested: int = 0  # Сколько раз уровень был протестирован
    is_active: bool = True  # Активен ли уровень
    cluster_id: Optional[int] = None  # ID кластера для группировки близких уровней

    def __hash__(self):
        return hash((round(self.price, 4), self.time_frame))

    def __eq__(self, other):
        if not isinstance(other, PriceLevel):
            return False
        return (round(self.price, 4) == round(other.price, 4) and
                self.time_frame == other.time_frame)


class PriceLevelCluster:
    """Класс для кластеризации близких ценовых уровней"""

    def __init__(self, merge_threshold: float = 0.002):  # 0.2% порог для объединения
        self.merge_threshold = merge_threshold

    def cluster_levels(self, levels: List[PriceLevel], current_price: float) -> List[PriceLevel]:
        """Кластеризует уровни, объединяя близкие"""
        if not levels:
            return []

        # Сортируем уровни по цене
        sorted_levels = sorted(levels, key=lambda x: x.price)

        clusters = []
        current_cluster = [sorted_levels[0]]

        for level in sorted_levels[1:]:
            # Проверяем, близок ли уровень к текущему кластеру
            cluster_avg = sum(l.price for l in current_cluster) / len(current_cluster)
            price_diff = abs(level.price - cluster_avg) / cluster_avg

            if price_diff < self.merge_threshold:
                # Добавляем в текущий кластер
                current_cluster.append(level)
            else:
                # Создаем новый кластер
                clusters.append(current_cluster)
                current_cluster = [level]

        # Добавляем последний кластер
        if current_cluster:
            clusters.append(current_cluster)

        # Создаем объединенные уровни
        merged_levels = []
        for i, cluster in enumerate(clusters):
            # Вычисляем среднюю цену кластера (взвешенную по силе уровней)
            total_strength = sum(l.strength for l in cluster)
            if total_strength > 0:
                weighted_price = sum(l.price * l.strength for l in cluster) / total_strength
            else:
                weighted_price = sum(l.price for l in cluster) / len(cluster)

            # Вычисляем среднюю силу
            avg_strength = sum(l.strength for l in cluster) / len(cluster)

            # Суммируем касания
            total_touches = sum(l.touches for l in cluster)

            # Берем самое раннее время создания
            earliest_time = min(l.created_time for l in cluster)

            # Создаем объединенный уровень
            merged_level = PriceLevel(
                price=weighted_price,
                strength=min(avg_strength * 1.1, 1.0),  # Немного увеличиваем силу при объединении
                time_frame=cluster[0].time_frame,
                touches=total_touches,
                is_fresh=any(l.is_fresh for l in cluster),
                created_time=earliest_time,
                last_touch_time=max((l.last_touch_time for l in cluster if l.last_touch_time),
                                    default=None),
                times_tested=sum(l.times_tested for l in cluster),
                is_active=True,
                cluster_id=i
            )
            merged_levels.append(merged_level)

        # Фильтруем уровни, которые слишком близки к текущей цене (менее 0.5%)
        filtered_levels = []
        for level in merged_levels:
            price_diff_pct = abs(level.price - current_price) / current_price * 100 if current_price > 0 else 0
            if price_diff_pct > 0.5:  # Только уровни, отстоящие от текущей цены более чем на 0.5%
                filtered_levels.append(level)

        return filtered_levels