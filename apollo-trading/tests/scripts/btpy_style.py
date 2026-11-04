from backtesting import Strategy
from backtesting.lib import crossover
import pandas as pd
def SMA(v, n): return pd.Series(v).rolling(n).mean()
class Cross(Strategy):
    def init(self):
        self.f = self.I(SMA, self.data.Close, 10)
        self.s = self.I(SMA, self.data.Close, 30)
    def next(self):
        if self.f[0] > self.s[0] and self.f[-1] <= self.s[-1]:
            self.position.close(); self.buy()
        elif self.f[0] < self.s[0] and self.f[-1] >= self.s[-1]:
            self.position.close(); self.sell()
