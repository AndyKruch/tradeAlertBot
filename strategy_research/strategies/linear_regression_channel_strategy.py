import talib as ta
import pandas as pd
from backtesting import Backtest
from backtesting import Strategy
from backtesting.lib import crossover

from csv_reader import IMOEXF, SBER


class LinearRegressionChannelStrategy(Strategy):
    channel_period = 20
    channel_std_multiplier = 2.0

    stop_loss_pct = -1
    take_profit_pct = 0.02

    def init(self):
        close = pd.Series(self.data.Close)

        def upper_channel(series):
            regression = ta.LINEARREG(series, self.channel_period)
            std = ta.STDDEV(series, self.channel_period)
            return regression + self.channel_std_multiplier * std

        def lower_channel(series):
            regression = ta.LINEARREG(series, self.channel_period)
            std = ta.STDDEV(series, self.channel_period)
            return regression - self.channel_std_multiplier * std

        self.upper_channel = self.I(upper_channel, close)
        self.lower_channel = self.I(lower_channel, close)

    def next(self):
        price = self.data.Close[-1]

        if self.position:
            if self.position.pl_pct <= self.stop_loss_pct \
            or self.data.Close < self.lower_channel \
            or self.position.pl_pct >= self.take_profit_pct:
                self.position.close()
                return

        if not self.position and self.data.Close > self.upper_channel:
            self.buy()


bt = Backtest(SBER, LinearRegressionChannelStrategy, cash=1_000_000, commission=0.002)

stats = bt.run()

bt.plot()

print("\nРезультаты бэктеста:")
print(f"Период тестирования: с {stats['Start']} по {stats['End']}")
print(f"Начальный капитал: 1000000 руб.")
print(f"Конечный капитал: {stats['Equity Final [$]']:.2f} руб.")
print(f"Общая доходность: {stats['Return [%]']:.2f}%")
print(f"Buy & Hold: {stats['Buy & Hold Return [%]']:.2f}%")
print(f"Годовая доходность: {stats['Return (Ann.) [%]']:.2f}%")
print(f"Коэффициент Шарпа: {stats['Sharpe Ratio']:.2f}")
print(f"Максимальная просадка: {stats['Max. Drawdown [%]']:.2f}%")
print(f"Количество сделок: {stats['# Trades']}")
print(f"Процент выигрышных сделок: {stats['Win Rate [%]']:.2f}%")
print(f"Лучшая сделка: +{stats['Best Trade [%]']:.2f}%")
print(f"Худшая сделка: {stats['Worst Trade [%]']:.2f}%")
print(f"Средняя продолжительность сделки: {stats['Avg. Trade Duration']}")
