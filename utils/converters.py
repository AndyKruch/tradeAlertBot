from datetime import datetime
from typing import Dict, Any
from decimal import Decimal

from t_tech.invest.utils import quotation_to_decimal
from t_tech.invest import MoneyValue, Quotation, Candle, HistoricCandle


def candle_to_dict(candle: Candle) -> Dict[str, Any]:
    """Конвертирует свечу Tinkoff в словарь"""
    return {
        'open': float(moneyvalue_to_decimal(candle.open)),
        'high': float(moneyvalue_to_decimal(candle.high)),
        'low': float(moneyvalue_to_decimal(candle.low)),
        'close': float(moneyvalue_to_decimal(candle.close)),
        'volume': candle.volume,
        'time': candle.time
    }


def moneyvalue_to_decimal(money_value: MoneyValue) -> Decimal:
    return quotation_to_decimal(
        Quotation(
            units=money_value.units,
            nano=money_value.nano
        )
    )
