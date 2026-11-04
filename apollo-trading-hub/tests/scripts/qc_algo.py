from AlgorithmImports import *
class GoldTrend(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2025, 1, 1)
        self.sym = self.AddCfd("XAUUSD", Resolution.Minute).Symbol
        self.fast = self.EMA(self.sym, 10)
        self.slow = self.SMA(self.sym, 30)
    def OnData(self, data):
        if not self.slow.IsReady:
            return
        if self.fast.Current.Value > self.slow.Current.Value and not self.Portfolio[self.sym].Invested:
            self.SetHoldings(self.sym, 1)
        elif self.fast.Current.Value < self.slow.Current.Value and self.Portfolio[self.sym].Invested:
            self.Liquidate()
