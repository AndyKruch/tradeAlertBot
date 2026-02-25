# analyzers/level_analyzer.py
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
import numpy as np
from models import PriceLevel


class LevelAnalyzer:
    """Анализатор уровней поддержки и сопротивления"""

    def __init__(self):
        self.window_size = 5
        self.min_levels_distance = 0.005  # Минимальное расстояние между уровнями (0.5%)

    def find_support_resistance_levels(self, candles: List[Dict],
                                       current_price: float) -> Tuple[List[PriceLevel], List[PriceLevel]]:
        """Находит уровни поддержки и сопротивления"""
        if len(candles) < 20:
            return [], []

        support_levels = self._find_levels(candles, 'low', 'support', current_price)
        resistance_levels = self._find_levels(candles, 'high', 'resistance', current_price)
        return support_levels, resistance_levels

    def _find_levels(self, candles: List[Dict], price_key: str,
                     level_type: str, current_price: float) -> List[PriceLevel]:
        # Получаем список экстремумов: (цена, время)
        extremums = self._find_local_extremums(candles, price_key, level_type)
        # Кластеризуем: возвращает список (цена, количество, среднее расстояние, стд, время_последнего)
        clusters = self._cluster_extremums_with_min_distance(extremums, current_price, level_type)

        levels = []
        for cluster_price, count, avg_distance, cluster_std, last_time in clusters:
            strength = self._calculate_level_strength(count, avg_distance,
                                                      cluster_price, current_price, level_type,
                                                      cluster_std)
            level = PriceLevel(
                price=cluster_price,
                strength=strength,
                time_frame="15min",
                touches=count,
                is_fresh=True,
                created_time=last_time,  # используем реальное время последнего экстремума в кластере
                last_touch_time=last_time  # также можно установить последнее касание
            )
            levels.append(level)

        levels.sort(key=lambda x: x.strength, reverse=True)
        return levels[:5]

    def _find_local_extremums(self, candles: List[Dict], price_key: str,
                              level_type: str) -> List[Tuple[float, datetime]]:
        """Возвращает список (цена, время) для локальных экстремумов"""
        extremums = []
        for i in range(self.window_size, len(candles) - self.window_size):
            current_price = candles[i][price_key]
            current_time = candles[i]['time']
            is_extremum = True
            for j in range(i - self.window_size, i + self.window_size + 1):
                if j != i and 0 <= j < len(candles):
                    if level_type == 'support':
                        if candles[j][price_key] < current_price:
                            is_extremum = False
                            break
                    else:
                        if candles[j][price_key] > current_price:
                            is_extremum = False
                            break
            if is_extremum:
                extremums.append((current_price, current_time))
        return extremums

    def _cluster_extremums_with_min_distance(self, extremums: List[Tuple[float, datetime]], current_price: float,
                                             level_type: str) -> List[Tuple[float, int, float, float, datetime]]:
        """Кластеризует экстремумы с учётом времени; возвращает (цена, количество, среднее расстояние, стд, последнее время)"""
        if not extremums:
            return []

        # Фильтруем по расстоянию от текущей цены
        filtered = []
        for price, ts in extremums:
            distance_pct = abs(price - current_price) / current_price * 100 if current_price > 0 else 100
            if distance_pct < 10:
                filtered.append((price, ts))

        if not filtered:
            return []

        # Сортируем по цене
        sorted_items = sorted(filtered, key=lambda x: x[0])
        clusters = []
        current_cluster = [sorted_items[0]]

        for price, ts in sorted_items[1:]:
            avg_price = sum(p for p, _ in current_cluster) / len(current_cluster)
            if abs(price - avg_price) / avg_price < 0.0025:
                current_cluster.append((price, ts))
            else:
                if len(current_cluster) >= 2:
                    cluster_prices = [p for p, _ in current_cluster]
                    cluster_times = [ts for _, ts in current_cluster]
                    cluster_price = sum(cluster_prices) / len(cluster_prices)
                    avg_distance = sum(abs(p - cluster_price) for p in cluster_prices) / len(cluster_prices)
                    cluster_std = np.std(cluster_prices) if len(cluster_prices) > 1 else 0
                    last_time = max(cluster_times)  # самое позднее время в кластере
                    clusters.append((cluster_price, len(current_cluster), avg_distance, cluster_std, last_time))
                current_cluster = [(price, ts)]

        if len(current_cluster) >= 2:
            cluster_prices = [p for p, _ in current_cluster]
            cluster_times = [ts for _, ts in current_cluster]
            cluster_price = sum(cluster_prices) / len(cluster_prices)
            avg_distance = sum(abs(p - cluster_price) for p in cluster_prices) / len(cluster_prices)
            cluster_std = np.std(cluster_prices) if len(cluster_prices) > 1 else 0
            last_time = max(cluster_times)
            clusters.append((cluster_price, len(current_cluster), avg_distance, cluster_std, last_time))

        # Фильтруем слишком близкие кластеры
        filtered_clusters = []
        for price1, count1, avg_dist1, std1, last_time1 in clusters:
            too_close = False
            for i, (price2, count2, avg_dist2, std2, last_time2) in enumerate(filtered_clusters):
                if abs(price1 - price2) / price2 < self.min_levels_distance:
                    too_close = True
                    # Если текущий кластер сильнее, заменяем
                    if count1 > count2 or std1 < std2:
                        filtered_clusters[i] = (price1, count1, avg_dist1, std1, last_time1)
                    break
            if not too_close:
                filtered_clusters.append((price1, count1, avg_dist1, std1, last_time1))

        return filtered_clusters

    def _calculate_level_strength(self, touches: int, avg_distance: float,
                                  level_price: float, current_price: float,
                                  level_type: str, cluster_std: float) -> float:
        touches_factor = min(touches / 5, 1.0) * 0.5
        if current_price > 0:
            distance_factor = max(0, 1 - avg_distance / current_price * 100) * 0.3
        else:
            distance_factor = 0.15
        if current_price > 0 and cluster_std > 0:
            std_factor = max(0, 1 - (cluster_std / current_price * 100)) * 0.2
        else:
            std_factor = 0.1
        if current_price > 0:
            price_distance = abs(level_price - current_price) / current_price
            proximity_factor = max(0, 1 - price_distance * 10) * 0.2
        else:
            proximity_factor = 0.1

        total_strength = touches_factor + distance_factor + std_factor + proximity_factor
        return min(total_strength, 1.0)