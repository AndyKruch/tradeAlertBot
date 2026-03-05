import csv
from datetime import timedelta

from t_tech.invest import Client, CandleInterval
from t_tech.invest.utils import quotation_to_decimal, now

from config import TOKEN


class MarketDataService:
    """
    The class encapsulate tinkoff market data service api
    """

    def __init__(self, token: str, figi) -> None:
        self.__token = token
        self.__figi = figi

    def get_candles(self):
        with Client(self.__token) as client:
            with open(f"{self.__figi}.csv", mode="w", encoding='utf-8') as w_file:
                names = ["", "Open", "High", "Low", "Close", "Volume"]
                file_writer = csv.DictWriter(w_file, delimiter=",",
                                             lineterminator="\r", fieldnames=names)
                file_writer.writeheader()

                for candle in client.get_all_candles(
                        figi=self.__figi,
                        from_=now() - timedelta(days=600),
                        interval=CandleInterval.CANDLE_INTERVAL_15_MIN,
                ):

                    _time = candle.time
                    _open = quotation_to_decimal(candle.open)
                    _high = quotation_to_decimal(candle.high)
                    _low = quotation_to_decimal(candle.low)
                    _close = quotation_to_decimal(candle.close)
                    _volume = candle.volume
                    file_writer.writerow({"": _time,
                                          "Open": _open,
                                          "High": _high,
                                          "Low": _low,
                                          "Close": _close,
                                          "Volume": _volume})


MarketDataService(token=TOKEN, figi="BBG004730N88").get_candles()
