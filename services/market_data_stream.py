# services/market_data_stream.py
from datetime import datetime, timezone
from typing import List, Callable, Awaitable, Any
import asyncio
from t_tech.invest import AsyncClient, CandleInstrument, SubscriptionInterval


class MarketDataStreamService:
    """Сервис для работы с потоковыми данными рынка"""

    def __init__(self, token: str, app_name: str):
        self.token = token
        self.app_name = app_name

    async def start_async_candles_stream(self, figies: List[str],
                                         trade_before_time: datetime,
                                         callback: Callable[[Any], Awaitable[None]]) -> None:
        """Запускает асинхронный поток свечей и вызывает callback для каждой свечи"""
        while datetime.now(timezone.utc) < trade_before_time:
            try:
                async with AsyncClient(self.token, app_name=self.app_name) as client:
                    stream = client.create_market_data_stream()

                    stream.candles.subscribe([
                        CandleInstrument(
                            figi=figi,
                            interval=SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_MINUTE
                        )
                        for figi in figies
                    ])

                    async for market_data in stream:
                        if datetime.now(timezone.utc) >= trade_before_time:
                            stream.stop()
                            break

                        if market_data.candle:
                            await callback(market_data.candle)

            except Exception as e:
                print(f"Ошибка в потоке данных: {e}")
                await asyncio.sleep(5)