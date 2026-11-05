"""SMA cross written for backtrader — runs unchanged in Tickbench."""
import backtrader as bt


class SmaCross(bt.Strategy):
    params = (("fast", 10), ("slow", 30))

    def __init__(self):
        sma1 = bt.ind.SMA(period=self.p.fast)
        sma2 = bt.ind.SMA(period=self.p.slow)
        self.crossover = bt.ind.CrossOver(sma1, sma2)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


if __name__ == "__main__":
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SmaCross)
    cerebro.run()
