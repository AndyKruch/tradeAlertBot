# trading/position_persistence.py
import asyncio
import json
from datetime import datetime
from typing import Dict, Optional
from .paper_trading import Position


class PositionPersistence:
    def __init__(self, filename: str = "active_positions.json"):
        self.filename = filename
        self.queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._writer())

    async def stop(self):
        if not self._running:
            return
        self._running = False
        await self.queue.join()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def save_positions(self, positions: Dict[str, Position]):
        """Помещает текущий снэпшот позиций в очередь на запись"""
        await self.queue.put(positions.copy())  # копируем, чтобы избежать изменений во время сериализации

    async def _writer(self):
        while self._running or not self.queue.empty():
            try:
                positions_dict = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Преобразуем в список сериализуемых словарей
            serializable = []
            for pos in positions_dict.values():
                pos_data = {
                    'figi': pos.figi,
                    'ticker': pos.ticker,
                    'direction': pos.direction,
                    'entry_price': pos.entry_price,
                    'entry_level': pos.entry_level,
                    'contracts': pos.contracts,
                    'open_time': pos.open_time.isoformat() if pos.open_time else None,
                    'tp_price': pos.tp_price
                }
                serializable.append(pos_data)

            # Пишем в файл (полностью перезаписываем)
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, indent=2, ensure_ascii=False)

            self.queue.task_done()

    def load_positions(self) -> Dict[str, Position]:
        """Загружает позиции из файла при старте (синхронно)"""
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

        positions = {}
        for item in data:
            # Преобразуем ISO строку обратно в datetime
            open_time = datetime.fromisoformat(item['open_time']) if item.get('open_time') else None
            pos = Position(
                figi=item['figi'],
                ticker=item['ticker'],
                direction=item['direction'],
                entry_price=item['entry_price'],
                entry_level=item['entry_level'],
                contracts=item['contracts'],
                open_time=open_time,
                tp_price=item.get('tp_price')
            )
            positions[pos.figi] = pos
        return positions