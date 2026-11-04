from freqtrade.strategy import IStrategy, IntParameter
import freqtrade.vendor.qtpylib.indicators as qtpylib
from pandas import DataFrame
class EmaCross(IStrategy):
    timeframe = "5m"
    can_short = True
    stoploss = -0.05
    fast = IntParameter(5, 20, default=9)
    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["f"] = df["close"].ewm(span=self.fast.value).mean()
        df["s"] = df["close"].ewm(span=21).mean()
        return df
    def populate_entry_trend(self, df, metadata):
        df.loc[qtpylib.crossed_above(df["f"], df["s"]), "enter_long"] = 1
        df.loc[qtpylib.crossed_below(df["f"], df["s"]), "enter_short"] = 1
        return df
    def populate_exit_trend(self, df, metadata):
        df.loc[qtpylib.crossed_below(df["f"], df["s"]), "exit_long"] = 1
        df.loc[qtpylib.crossed_above(df["f"], df["s"]), "exit_short"] = 1
        return df
