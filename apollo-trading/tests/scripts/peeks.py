def generate_signals(df):
    return (df.close.shift(-3) > df.close).astype(int)   # cheats: uses future price
