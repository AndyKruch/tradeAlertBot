# alerting/alert_system.py
import asyncio
import threading
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from typing import List, Dict, Any, Optional, Deque
from t_tech.invest import Client, CandleInterval
from models import TradingSignal, SignalType
from analyzers import LevelAnalyzer, BreakoutAnalyzer
from services import MarketDataStreamService
from utils.converters import candle_to_dict
import config


class AlertSystem:
    """Система алертов с детектированием пробоев и сильных движений"""

    def __init__(self, token: str, app_name: str = config.APP_NAME):
        self.token = token
        self.app_name = app_name
        self.breakout_analyzer = BreakoutAnalyzer(token)
        self.level_analyzer = LevelAnalyzer()
        self.stream_service = MarketDataStreamService(token, app_name)

        self.candle_history: Dict[str, Deque[Dict]] = defaultdict(lambda: deque(maxlen=500))
        self.last_candles: Dict[str, Optional[Dict]] = {}
        self.instruments: List[Dict[str, str]] = []

        self.signals_count = 0
        self.breakouts_count = 0
        self.rejections_count = 0
        self.strong_moves_count = 0
        self.filtered_count = 0
        self.last_alert_time = None
        self.running = False

        self.level_update_thread = None
        self.level_update_interval = config.LEVEL_UPDATE_INTERVAL_SECONDS

    def initialize(self, instruments: List[Dict[str, str]]):
        self.instruments = instruments
        self.breakout_analyzer.initialize_instruments(instruments)

        print(f"✅ Инициализирована система мониторинга с пробоями для {len(instruments)} инструментов")
        print("📊 Анализируемые инструменты:")
        for instrument in instruments:
            print(f"   • {instrument['ticker']} ({instrument['figi'][:8]}...)")

    def _get_candles(self, client, figi: str, interval: CandleInterval, limit: int) -> List[Dict]:
        try:
            to_time = datetime.now(timezone.utc)
            if interval == CandleInterval.CANDLE_INTERVAL_1_MIN:
                from_time = to_time - timedelta(hours=48)
            elif interval == CandleInterval.CANDLE_INTERVAL_5_MIN:
                from_time = to_time - timedelta(hours=48)
            elif interval == CandleInterval.CANDLE_INTERVAL_15_MIN:
                from_time = to_time - timedelta(hours=48)
            elif interval == CandleInterval.CANDLE_INTERVAL_HOUR:
                from_time = to_time - timedelta(days=10)
            elif interval == CandleInterval.CANDLE_INTERVAL_DAY:
                from_time = to_time - timedelta(days=10)
            else:
                from_time = to_time - timedelta(days=1)

            response = client.market_data.get_candles(
                figi=figi,
                from_=from_time,
                to=to_time,
                interval=interval
            )

            candles = [candle_to_dict(c) for c in response.candles]
            return candles[-limit:] if len(candles) > limit else candles

        except Exception as e:
            print(f"Ошибка при получении свечей {interval}: {e}")
            return []

    async def _load_historical_data(self):
        print("\n📥 Загрузка исторических данных...")
        with Client(self.token, app_name=self.app_name) as client:
            for instrument in self.instruments:
                figi = instrument['figi']
                ticker = instrument['ticker']
                print(f"   Загрузка данных для {ticker}...")

                try:
                    # candles_5min = self._get_candles(client, figi, CandleInterval.CANDLE_INTERVAL_5_MIN, 288)
                    candles_15min = self._get_candles(client, figi, CandleInterval.CANDLE_INTERVAL_15_MIN, 100)
                    candles_1hour = self._get_candles(client, figi, CandleInterval.CANDLE_INTERVAL_HOUR, 70)
                    candles_1day = self._get_candles(client, figi, CandleInterval.CANDLE_INTERVAL_DAY, 10)

                    all_candles = []
                    if candles_1day:
                        all_candles.extend(candles_1day)
                    if candles_1hour:
                        all_candles.extend(candles_1hour)
                    if candles_15min:
                        all_candles.extend(candles_15min)
                    # if candles_5min:
                    #     all_candles.extend(candles_5min)

                    all_candles.sort(key=lambda x: x['time'])

                    if all_candles:
                        self.candle_history[figi] = deque(all_candles, maxlen=500)

                        # Инициализируем анализатор движения историческими данными
                        for hist_candle in all_candles:
                            self.breakout_analyzer.movement_analyzer.update_intraday(figi, hist_candle)
                            self.breakout_analyzer.movement_analyzer.update_daily_candle(figi, hist_candle)

                        print(f"   ✅ {ticker}: всего {len(all_candles)} свечей")
                        await self._analyze_levels_for_instrument(figi, all_candles)
                    else:
                        print(f"   ❌ {ticker}: не удалось загрузить исторические данные")

                except Exception as e:
                    print(f"   ❌ Ошибка при загрузке данных для {ticker}: {e}")

        print("✅ Загрузка исторических данных завершена")

    def _format_age(self, age_hours: float) -> str:
        if age_hours >= 1:
            return f"{age_hours:.1f}ч"
        else:
            return f"{age_hours * 60:.0f}м"

    async def _analyze_levels_for_instrument(self, figi: str, candles: List[Dict]):
        if len(candles) >= 20:
            current_price = candles[-1]['close'] if candles else 0
            supports, resistances = self.level_analyzer.find_support_resistance_levels(list(candles), current_price)
            self.breakout_analyzer.update_levels(figi, supports, resistances, current_price)

            monitor = self.breakout_analyzer.breakout_monitors.get(figi)
            if monitor:
                stats = monitor.get_level_statistics()
                levels_info = monitor.get_levels_info()
                ticker = monitor.ticker
                print(f"   📊 {ticker}: найдено {stats['active_supports']} поддержек, {stats['active_resistances']} сопротивлений")

                if levels_info['supports']:
                    print(f"     Поддержки:")
                    for sup in levels_info['supports']:
                        age_str = self._format_age(sup['age_hours'])
                        fresh_mark = " 🆕" if sup['is_fresh'] else ""
                        print(f"       - {sup['price']:.3f} (сила: {sup['strength']:.2f}, возраст: {age_str}, тестов: {sup['times_tested']}){fresh_mark}")
                else:
                    print(f"     Поддержки: нет")

                if levels_info['resistances']:
                    print(f"     Сопротивления:")
                    for res in levels_info['resistances']:
                        age_str = self._format_age(res['age_hours'])
                        fresh_mark = " 🆕" if res['is_fresh'] else ""
                        print(f"       - {res['price']:.3f} (сила: {res['strength']:.2f}, возраст: {age_str}, тестов: {res['times_tested']}){fresh_mark}")
                else:
                    print(f"     Сопротивления: нет")

                # Вывод среднего дневного диапазона
                avg_daily_range_pct = self.breakout_analyzer.movement_analyzer.get_avg_daily_range_pct(figi, current_price)
                if avg_daily_range_pct is not None:
                    print(f"     📊 Средний дневной диапазон (последние {config.MOVEMENT_LOOKBACK_DAYS} дн): {avg_daily_range_pct:.2f}%")
                else:
                    print(f"     📊 Средний дневной диапазон: недостаточно данных (нужно минимум {config.MOVEMENT_LOOKBACK_DAYS} дней)")

                for level in monitor.active_support_levels:
                    level.is_fresh = False
                for level in monitor.active_resistance_levels:
                    level.is_fresh = False

    async def start_monitoring(self, hours: int = config.DEFAULT_MONITOR_HOURS):
        self.running = True
        trade_before_time = datetime.now(timezone.utc) + timedelta(hours=hours)

        print(f"\n🚀 Запуск онлайн-мониторинга с пробоями...")
        print(f"⏰ Длительность: {hours} часов (до {trade_before_time.strftime('%H:%M')})")
        print(f"🔄 Обновление уровней: каждые {self.level_update_interval // 60} минут")
        print(f"📈 Анализ сильных движений: порог {config.MOVEMENT_THRESHOLD}x от среднего дневного диапазона")
        print("=" * 80)

        await self._load_historical_data()

        for figi in self.breakout_analyzer.breakout_monitors.keys():
            self.last_candles[figi] = None

        print(f"\n⏳ Ожидание 1 минуту перед первым обновлением уровней...")
        await asyncio.sleep(60)

        self._start_level_update_thread()

        figies = list(self.breakout_analyzer.breakout_monitors.keys())
        await self.stream_service.start_async_candles_stream(
            figies=figies,
            trade_before_time=trade_before_time,
            callback=self._process_candle
        )

    def _start_level_update_thread(self):
        def update_worker():
            time.sleep(self.level_update_interval)
            while self.running:
                try:
                    self._update_all_levels()
                    time.sleep(self.level_update_interval)
                except Exception as e:
                    print(f"Ошибка в потоке обновления уровней: {e}")
                    time.sleep(60)

        self.level_update_thread = threading.Thread(target=update_worker, daemon=True)
        self.level_update_thread.start()
        print("🔄 Поток обновления уровней запущен")

    def _update_all_levels(self):
        current_time = datetime.now(timezone.utc)
        print(f"\n🔄 Обновление уровней... {current_time.strftime('%H:%M:%S')}")

        any_updated = False
        for figi, history in self.candle_history.items():
            if len(history) < 20:
                continue

            current_price = history[-1]['close'] if history else 0
            supports, resistances = self.level_analyzer.find_support_resistance_levels(list(history), current_price)
            self.breakout_analyzer.update_levels(figi, supports, resistances, current_price)

            monitor = self.breakout_analyzer.breakout_monitors.get(figi)
            if not monitor:
                continue

            stats = monitor.get_level_statistics()
            levels_info = monitor.get_levels_info()
            ticker = monitor.ticker

            print(f"   📈 {ticker}: {stats['active_supports']} поддержек, {stats['active_resistances']} сопротивлений")

            if levels_info['supports']:
                print(f"     Поддержки:")
                for sup in levels_info['supports']:
                    age_str = self._format_age(sup['age_hours'])
                    fresh_mark = " 🆕" if sup['is_fresh'] else ""
                    print(f"       - {sup['price']:.3f} (сила: {sup['strength']:.2f}, возраст: {age_str}, тестов: {sup['times_tested']}){fresh_mark}")
            else:
                print(f"     Поддержки: нет")

            if levels_info['resistances']:
                print(f"     Сопротивления:")
                for res in levels_info['resistances']:
                    age_str = self._format_age(res['age_hours'])
                    fresh_mark = " 🆕" if res['is_fresh'] else ""
                    print(f"       - {res['price']:.3f} (сила: {res['strength']:.2f}, возраст: {age_str}, тестов: {res['times_tested']}){fresh_mark}")
            else:
                print(f"     Сопротивления: нет")

            # Вывод среднего дневного диапазона
            avg_daily_range_pct = self.breakout_analyzer.movement_analyzer.get_avg_daily_range_pct(figi, current_price)
            if avg_daily_range_pct is not None:
                print(f"     📊 Средний дневной диапазон (последние {config.MOVEMENT_LOOKBACK_DAYS} дн): {avg_daily_range_pct:.2f}%")
            else:
                print(f"     📊 Средний дневной диапазон: недостаточно данных (нужно минимум {config.MOVEMENT_LOOKBACK_DAYS} дней)")

            for level in monitor.active_support_levels:
                level.is_fresh = False
            for level in monitor.active_resistance_levels:
                level.is_fresh = False

            any_updated = True

        if not any_updated:
            print("   ❌ Нет инструментов с достаточным количеством данных")

    async def _process_candle(self, candle):
        figi = candle.figi
        candle_dict = candle_to_dict(candle)
        candle_time = candle.time

        if figi in self.last_candles and self.last_candles[figi] is not None:
            last_candle = self.last_candles[figi]
            if candle_time > last_candle['time']:
                self.candle_history[figi].append(last_candle)

        self.last_candles[figi] = candle_dict

        signals = self.breakout_analyzer.process_candle(candle)

        for signal in signals:
            self.signals_count += 1
            self.last_alert_time = datetime.now(timezone.utc)

            if signal.signal_type in [SignalType.BREAKOUT_SUPPORT, SignalType.BREAKOUT_RESISTANCE]:
                self.breakouts_count += 1
            elif signal.signal_type in [SignalType.REJECTION_SUPPORT, SignalType.REJECTION_RESISTANCE]:
                self.rejections_count += 1
            elif signal.signal_type in [SignalType.STRONG_MOVE_UP, SignalType.STRONG_MOVE_DOWN]:
                self.strong_moves_count += 1

            await self._alert_signal(signal)

    async def _alert_signal(self, signal: TradingSignal):
        colors = {
            SignalType.BREAKOUT_SUPPORT: "\033[91;1m",
            SignalType.BREAKOUT_RESISTANCE: "\033[92;1m",
            SignalType.REJECTION_SUPPORT: "\033[92m",
            SignalType.REJECTION_RESISTANCE: "\033[91m",
            SignalType.STRONG_MOVE_UP: "\033[94;1m",
            SignalType.STRONG_MOVE_DOWN: "\033[94;1m",
            SignalType.BUY: "\033[92m",
            SignalType.STRONG_BUY: "\033[92;1m",
            SignalType.SELL: "\033[91m",
            SignalType.STRONG_SELL: "\033[91;1m",
            SignalType.WEAK_BUY: "\033[93m",
            SignalType.WEAK_SELL: "\033[93m",
            SignalType.NEUTRAL: "\033[90m"
        }
        reset_color = "\033[0m"
        color = colors.get(signal.signal_type, "")

        icons = {
            SignalType.BREAKOUT_SUPPORT: "📉🔴",
            SignalType.BREAKOUT_RESISTANCE: "📈🟢",
            SignalType.REJECTION_SUPPORT: "↗️🟢",
            SignalType.REJECTION_RESISTANCE: "↘️🔴",
            SignalType.STRONG_MOVE_UP: "🚀🟢",
            SignalType.STRONG_MOVE_DOWN: "📉🔴",
            SignalType.BUY: "🟢",
            SignalType.STRONG_BUY: "🟢🟢",
            SignalType.SELL: "🔴",
            SignalType.STRONG_SELL: "🔴🔴"
        }
        icon = icons.get(signal.signal_type, "ℹ️")

        time_str = signal.timestamp.strftime("%H:%M:%S.%f")[:-3]

        if signal.signal_type in [SignalType.BREAKOUT_SUPPORT, SignalType.BREAKOUT_RESISTANCE]:
            alert_type = "ПРОБОЙ УРОВНЯ"
        elif signal.signal_type in [SignalType.REJECTION_SUPPORT, SignalType.REJECTION_RESISTANCE]:
            alert_type = "ОТСКОК ОТ УРОВНЯ"
        elif signal.signal_type in [SignalType.STRONG_MOVE_UP, SignalType.STRONG_MOVE_DOWN]:
            alert_type = "СИЛЬНОЕ ДВИЖЕНИЕ"
        else:
            alert_type = "ТОРГОВЫЙ СИГНАЛ"

        print(f"\n{'═' * 80}")
        print(f"{color}{icon} {alert_type} {signal.signal_type.value} [{time_str}]{reset_color}")
        print(f"{'═' * 80}")
        print(f"{color}📊 {signal.ticker} | Цена: {signal.current_price:.2f}{reset_color}")

        # Безопасный вывод дополнительных полей
        if signal.level_price is not None:
            print(f"{color}🎯 Уровень: {signal.level_price:.2f}{reset_color}")
        if signal.candle_open is not None and signal.candle_close is not None:
            print(f"{color}📈 Открытие: {signal.candle_open:.2f} | Закрытие: {signal.candle_close:.2f}{reset_color}")
        if signal.volume is not None:
            print(f"{color}📊 Объем: {signal.volume:,}{reset_color}")

        # Блок для торговых сигналов (entry_price, stop_loss, take_profit, risk_reward)
        if signal.entry_price is not None and signal.stop_loss is not None and signal.take_profit is not None:
            print(f"{color}🎯 Вход: {signal.entry_price:.2f} | Стоп: {signal.stop_loss:.2f} | Тейк: {signal.take_profit:.2f}{reset_color}")
            if signal.risk_reward is not None and signal.risk_reward > 0:
                print(f"{color}⚖️  Риск/Прибыль: 1:{signal.risk_reward:.1f}{reset_color}")

        if signal.move_percent is not None:
            print(f"{color}📈 Движение от открытия: {signal.move_percent:.2f}%{reset_color}")
        if signal.avg_daily_range is not None:
            print(f"{color}📊 Средний дневной диапазон: {signal.avg_daily_range:.2f}%{reset_color}")
        if signal.threshold is not None:
            print(f"{color}⚡ Порог: {signal.threshold:.1f}x{reset_color}")

        print(f"{color}📈 Уверенность: {signal.confidence:.2%}{reset_color}")
        print(f"{color}📝 {signal.reason}{reset_color}")
        print(f"{'═' * 80}")

        # await self._log_signal(signal)

    # async def _log_signal(self, signal: TradingSignal):
    #     log_entry = (
    #         f"{signal.timestamp.isoformat()},"
    #         f"{signal.ticker},"
    #         f"{signal.signal_type.value},"
    #         f"{signal.current_price:.2f},"
    #         f"{signal.level_price if signal.level_price is not None else ''},"
    #         f"{signal.candle_open if signal.candle_open is not None else ''},"
    #         f"{signal.candle_close if signal.candle_close is not None else ''},"
    #         f"{signal.volume if signal.volume is not None else ''},"
    #         f"{signal.confidence:.3f},"
    #         f"\"{signal.reason}\"\n"
    #     )
    #
    #     try:
    #         with open("breakout_signals.csv", "a") as f:
    #             if f.tell() == 0:
    #                 f.write("timestamp,ticker,signal,price,level,open,close,volume,confidence,reason\n")
    #             f.write(log_entry)
    #     except Exception as e:
    #         print(f"Ошибка при записи в лог: {e}")

    def print_stats(self):
        print(f"\n{'=' * 80}")
        print("📊 СТАТИСТИКА МОНИТОРИНГА С ПРОБОЯМИ")
        print(f"{'=' * 80}")
        print(f"Всего сигналов: {self.signals_count}")
        print(f"  - Пробоев уровней: {self.breakouts_count}")
        print(f"  - Отскоков от уровней: {self.rejections_count}")
        print(f"  - Сильных движений: {self.strong_moves_count}")
        print(f"  - Отфильтровано дублей: {self.breakout_analyzer.filtered_signals}")

        breakout_stats = self.breakout_analyzer.get_statistics()
        print(f"\n📈 Статистика пробоев:")
        print(f"  Мониторируемых инструментов: {breakout_stats['monitored_instruments']}")

        if self.last_alert_time:
            print(f"  Последний алерт: {self.last_alert_time.strftime('%H:%M:%S')}")