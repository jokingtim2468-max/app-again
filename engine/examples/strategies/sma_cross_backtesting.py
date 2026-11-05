"""SMA cross written for the backtesting.py library — runs unchanged in Tickbench."""
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA


class SmaCross(Strategy):
    n1 = 10
    n2 = 30

    def init(self):
        self.sma1 = self.I(SMA, self.data.Close, self.n1)
        self.sma2 = self.I(SMA, self.data.Close, self.n2)

    def next(self):
        if not self.position and crossover(self.sma1, self.sma2):
            self.buy(size=1)
        elif self.position and crossover(self.sma2, self.sma1):
            self.position.close()


if __name__ == "__main__":
    bt = Backtest(None, SmaCross)
    print(bt.run())
