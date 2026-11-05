from tickbench.data.loader import load_csv, resample

MT5 = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n" \
      "2024.01.02\t00:00:00\t2062.98\t2078.62\t2058.23\t2064.18\t44560\t0\t9\n" \
      "2024.01.03\t00:00:00\t2064.25\t2066.98\t2030.70\t2042.23\t52280\t0\t9\n" \
      "2024.01.04\t00:00:00\t2042.40\t2050.70\t2033.48\t2043.67\t44260\t0\t9\n"
MT4 = "2024.01.02,00:00,1.10,1.11,1.09,1.105,100\n2024.01.02,01:00,1.105,1.12,1.10,1.115,90\n"
TV = "time,open,high,low,close,Volume\n1704153600,10,11,9,10.5,1\n1704240000,10.5,12,10,11,2\n"
SEMI = "Date;Open;High;Low;Close;Volume\n02/01/2024;1;2;0.5;1.5;10\n03/01/2024;1.5;2;1;1.8;11\n"
COMPACT = "20240102 093000;4780.25;4781.00;4779.50;4780.75;120\n20240102 093100;4780.75;4782.00;4780.50;4781.50;98\n"


def test_mt5_tab_export():
    b = load_csv(MT5, "XAUUSD", is_text=True)
    assert len(b) == 3 and b.close[0] == 2064.18 and b.volume[0] == 44560
    assert b.timeframe == "1d"


def test_mt4_headerless():
    b = load_csv(MT4, "EURUSD", is_text=True)
    assert len(b) == 2 and b.timeframe == "1h" and b.time[1] - b.time[0] == 3_600_000


def test_tradingview_unix_seconds():
    b = load_csv(TV, "X", is_text=True)
    assert b.time[0] == 1704153600000


def test_semicolon_and_compact():
    assert len(load_csv(SEMI, "X", is_text=True)) == 2
    b = load_csv(COMPACT, "ES", is_text=True)
    assert b.timeframe == "1m" and b.close[1] == 4781.5


def test_resample_hourly_to_daily():
    b = load_csv(MT4, "EURUSD", is_text=True)
    d = resample(b, "1d")
    assert len(d) == 1 and d.high[0] == 1.12 and d.close[0] == 1.115
