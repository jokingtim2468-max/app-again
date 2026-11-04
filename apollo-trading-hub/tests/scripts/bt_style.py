import backtrader as bt
class SmaCross(bt.Strategy):
    params = (("period", 20),)
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)
    def next(self):
        if not self.position and self.data.close[0] > self.sma[0]:
            self.buy()
        elif self.position and self.data.close[0] < self.sma[0]:
            self.close()
