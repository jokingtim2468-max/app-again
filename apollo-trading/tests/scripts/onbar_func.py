closes = []
def on_bar(bar):
    closes.append(bar.close)
    if len(closes) < 15: return "hold"
    m = sum(closes[-15:]) / 15
    return "buy" if bar.close > m + 0.5 else "sell" if bar.close < m - 0.5 else "hold"
