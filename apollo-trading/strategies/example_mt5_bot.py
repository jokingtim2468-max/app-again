import time
import MetaTrader5 as mt5
import pandas as pd
SYMBOL = "XAUUSD"
def main():
    mt5.initialize()
    while True:
        rates = pd.DataFrame(mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 50))
        if len(rates) >= 20:
            ma = rates.close.rolling(20).mean().iloc[-1]
            last = rates.close.iloc[-1]
            pos = mt5.positions_get(symbol=SYMBOL)
            if not pos and last > ma:
                mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": 0.1, "type": mt5.ORDER_TYPE_BUY})
            elif pos and last < ma:
                mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": 0.1, "type": mt5.ORDER_TYPE_SELL, "position": pos[0].ticket})
        time.sleep(60)
if __name__ == "__main__":
    main()
