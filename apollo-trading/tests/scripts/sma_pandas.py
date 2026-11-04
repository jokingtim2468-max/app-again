import pandas as pd
FAST, SLOW = 10, 30
def generate_signals(df):
    fast = df["Close"].rolling(FAST).mean()
    slow = df["Close"].rolling(SLOW).mean()
    return (fast > slow).astype(int) - (fast < slow).astype(int)
