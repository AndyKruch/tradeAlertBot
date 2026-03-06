# trading/trade_logger.py
import asyncio
import csv
from datetime import datetime
from typing import Optional


class TradeLogger:
    def __init__(self, filename: str = "trades.csv"):
        self.filename = filename
        self.queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        """Запускает фоновую задачу записи"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._writer())

    async def stop(self):
        """Останавливает фоновую задачу, дожидаясь завершения записи"""
        if not self._running:
            return
        self._running = False
        await self.queue.join()  # ждём обработки всех элементов
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def log_trade(self, timestamp: datetime, ticker: str, direction: str,
                        contracts: int, price: float, level_price: float, reason: str):
        """Добавляет сделку в очередь на запись"""
        await self.queue.put((timestamp, ticker, direction, contracts, price, level_price, reason))

    async def _writer(self):
        """Фоновая задача: читает очередь и пишет в CSV"""
        # Открываем файл в режиме добавления, с заголовком если файл новый
        file_exists = False
        try:
            with open(self.filename, 'r'):
                file_exists = True
        except FileNotFoundError:
            pass

        with open(self.filename, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            if not file_exists:
                writer.writerow(['timestamp', 'ticker', 'direction', 'contracts',
                                 'price', 'level_price', 'reason'])

            while self._running or not self.queue.empty():
                try:
                    # ждём новую запись до 1 секунды, чтобы можно было проверить флаг _running
                    item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                timestamp, ticker, direction, contracts, price, level_price, reason = item
                writer.writerow([
                    timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    ticker,
                    direction,
                    contracts,
                    f"{price:.2f}",
                    f"{level_price:.2f}",
                    reason
                ])
                f.flush()  # гарантируем запись на диск
                self.queue.task_done()