def signals(df):
    ma = df.close.rolling(20).mean()
    entries = (df.close > ma) & (df.close.shift() <= ma.shift())
    exits = (df.close < ma) & (df.close.shift() >= ma.shift())
    return entries, exits
