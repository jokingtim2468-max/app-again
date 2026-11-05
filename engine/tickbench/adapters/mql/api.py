"""MQL4 / MQL5 built-in functions, constants and trade classes on top of the Tickbench broker."""

from __future__ import annotations

import math
import random
import re
from datetime import datetime, timezone

from ...core.broker import Trade
from ...errors import ScriptError, UnsupportedFeature
from .interp import MqlArr, MStruct, STRUCT_DEFAULTS, cast, fmt_value
from .mtind import (ADX_MT, ATR_MT, MACD_MT, MA_FACTORY, Bands_MT, IndSeries, Momentum_MT, Price, Stoch_MT)
from ... import indicators as ind

DBL_MAX = 1.7976931348623158e308

CONST = {
    # MQL4 order types / selection
    "OP_BUY": 0, "OP_SELL": 1, "OP_BUYLIMIT": 2, "OP_SELLLIMIT": 3, "OP_BUYSTOP": 4, "OP_SELLSTOP": 5,
    "SELECT_BY_POS": 0, "SELECT_BY_TICKET": 1, "MODE_TRADES": 0, "MODE_HISTORY": 1,
    # MA methods / applied prices
    "MODE_SMA": 0, "MODE_EMA": 1, "MODE_SMMA": 2, "MODE_LWMA": 3,
    "PRICE_CLOSE": 0, "PRICE_OPEN": 1, "PRICE_HIGH": 2, "PRICE_LOW": 3, "PRICE_MEDIAN": 4, "PRICE_TYPICAL": 5,
    "PRICE_WEIGHTED": 6,
    # indicator buffers / series modes
    "MODE_MAIN": 0, "MODE_SIGNAL": 1, "MODE_UPPER": 1, "MODE_LOWER": 2, "MODE_PLUSDI": 1, "MODE_MINUSDI": 2,
    "MAIN_LINE": 0, "SIGNAL_LINE": 1, "BASE_LINE": 0, "UPPER_BAND": 1, "LOWER_BAND": 2, "PLUSDI_LINE": 1,
    "MINUSDI_LINE": 2, "MODE_OPEN": 0, "MODE_LOW": 1, "MODE_HIGH": 2, "MODE_CLOSE": 3, "MODE_VOLUME": 4,
    "MODE_TIME": 5, "STO_LOWHIGH": 0, "STO_CLOSECLOSE": 1,
    # MarketInfo modes (MQL4)
    "MODE_BID": 9, "MODE_ASK": 10, "MODE_POINT": 11, "MODE_DIGITS": 12, "MODE_SPREAD": 13, "MODE_STOPLEVEL": 14,
    "MODE_LOTSIZE": 15, "MODE_TICKVALUE": 16, "MODE_TICKSIZE": 17, "MODE_SWAPLONG": 18, "MODE_SWAPSHORT": 19,
    "MODE_MINLOT": 23, "MODE_LOTSTEP": 24, "MODE_MAXLOT": 25, "MODE_MARGINREQUIRED": 32, "MODE_FREEZELEVEL": 33,
    # timeframes
    "PERIOD_CURRENT": 0, "PERIOD_M1": 1, "PERIOD_M5": 5, "PERIOD_M15": 15, "PERIOD_M30": 30, "PERIOD_H1": 60,
    "PERIOD_H4": 240, "PERIOD_D1": 1440, "PERIOD_W1": 10080, "PERIOD_MN1": 43200, "PERIOD_M2": 2, "PERIOD_M3": 3,
    "PERIOD_M4": 4, "PERIOD_M6": 6, "PERIOD_M10": 10, "PERIOD_M12": 12, "PERIOD_M20": 20, "PERIOD_H2": 120,
    "PERIOD_H3": 180, "PERIOD_H6": 360, "PERIOD_H8": 480, "PERIOD_H12": 720,
    # MQL5 orders / positions / deals
    "ORDER_TYPE_BUY": 0, "ORDER_TYPE_SELL": 1, "ORDER_TYPE_BUY_LIMIT": 2, "ORDER_TYPE_SELL_LIMIT": 3,
    "ORDER_TYPE_BUY_STOP": 4, "ORDER_TYPE_SELL_STOP": 5, "ORDER_TYPE_BUY_STOP_LIMIT": 6, "ORDER_TYPE_SELL_STOP_LIMIT": 7,
    "POSITION_TYPE_BUY": 0, "POSITION_TYPE_SELL": 1,
    "POSITION_TYPE": 100, "POSITION_MAGIC": 101, "POSITION_TICKET": 102, "POSITION_TIME": 103,
    "POSITION_IDENTIFIER": 104, "POSITION_TIME_MSC": 105, "POSITION_REASON": 106,
    "POSITION_PRICE_OPEN": 110, "POSITION_VOLUME": 111, "POSITION_SL": 112, "POSITION_TP": 113,
    "POSITION_PROFIT": 114, "POSITION_PRICE_CURRENT": 115, "POSITION_SWAP": 116,
    "POSITION_SYMBOL": 120, "POSITION_COMMENT": 121,
    "ORDER_TYPE": 200, "ORDER_MAGIC": 201, "ORDER_TICKET": 202, "ORDER_TIME_SETUP": 203, "ORDER_STATE": 204,
    "ORDER_PRICE_OPEN": 210, "ORDER_VOLUME_CURRENT": 211, "ORDER_VOLUME_INITIAL": 212, "ORDER_SL": 213,
    "ORDER_TP": 214, "ORDER_PRICE_CURRENT": 215, "ORDER_SYMBOL": 220, "ORDER_COMMENT": 221,
    "DEAL_TYPE": 300, "DEAL_ENTRY": 301, "DEAL_MAGIC": 302, "DEAL_TIME": 303, "DEAL_POSITION_ID": 304,
    "DEAL_ORDER": 305, "DEAL_PROFIT": 310, "DEAL_VOLUME": 311, "DEAL_PRICE": 312, "DEAL_COMMISSION": 313,
    "DEAL_SWAP": 314, "DEAL_SYMBOL": 320, "DEAL_COMMENT": 321,
    "DEAL_TYPE_BUY": 0, "DEAL_TYPE_SELL": 1, "DEAL_ENTRY_IN": 0, "DEAL_ENTRY_OUT": 1, "DEAL_ENTRY_INOUT": 2,
    "TRADE_ACTION_DEAL": 1, "TRADE_ACTION_PENDING": 5, "TRADE_ACTION_SLTP": 6, "TRADE_ACTION_MODIFY": 7,
    "TRADE_ACTION_REMOVE": 8, "TRADE_ACTION_CLOSE_BY": 10,
    "TRADE_RETCODE_DONE": 10009, "TRADE_RETCODE_PLACED": 10008, "TRADE_RETCODE_INVALID": 10013,
    "TRADE_RETCODE_INVALID_VOLUME": 10014, "TRADE_RETCODE_NO_MONEY": 10019,
    "ORDER_FILLING_FOK": 0, "ORDER_FILLING_IOC": 1, "ORDER_FILLING_RETURN": 2, "ORDER_TIME_GTC": 0,
    "ORDER_TIME_DAY": 1, "ORDER_TIME_SPECIFIED": 2,
    "SYMBOL_BID": 400, "SYMBOL_ASK": 401, "SYMBOL_POINT": 402, "SYMBOL_TRADE_TICK_VALUE": 403,
    "SYMBOL_TRADE_TICK_SIZE": 404, "SYMBOL_VOLUME_MIN": 405, "SYMBOL_VOLUME_MAX": 406, "SYMBOL_VOLUME_STEP": 407,
    "SYMBOL_TRADE_CONTRACT_SIZE": 408, "SYMBOL_LAST": 409, "SYMBOL_DIGITS": 420, "SYMBOL_SPREAD": 421,
    "SYMBOL_TRADE_STOPS_LEVEL": 422, "SYMBOL_TRADE_FREEZE_LEVEL": 423, "SYMBOL_FILLING_MODE": 424,
    "SYMBOL_TRADE_TICK_VALUE_PROFIT": 403, "SYMBOL_TRADE_TICK_VALUE_LOSS": 403,
    "ACCOUNT_BALANCE": 500, "ACCOUNT_EQUITY": 501, "ACCOUNT_MARGIN_FREE": 502, "ACCOUNT_PROFIT": 503,
    "ACCOUNT_MARGIN": 504, "ACCOUNT_CREDIT": 505, "ACCOUNT_MARGIN_LEVEL": 506, "ACCOUNT_LEVERAGE": 510,
    "ACCOUNT_LOGIN": 511, "ACCOUNT_TRADE_MODE": 512, "ACCOUNT_TRADE_ALLOWED": 513, "ACCOUNT_TRADE_EXPERT": 514,
    "ACCOUNT_CURRENCY": 520, "ACCOUNT_NAME": 521, "ACCOUNT_SERVER": 522, "ACCOUNT_COMPANY": 523,
    "INIT_SUCCEEDED": 0, "INIT_FAILED": 1, "INIT_PARAMETERS_INCORRECT": 2, "INIT_AGENT_NOT_SUITABLE": 3,
    "REASON_PROGRAM": 0, "REASON_REMOVE": 1, "REASON_RECOMPILE": 2, "REASON_CHARTCHANGE": 3,
    "MQL_TESTER": 1, "MQL_OPTIMIZATION": 2, "MQL_VISUAL_MODE": 3, "MQL_TRADE_ALLOWED": 4,
    "TERMINAL_TRADE_ALLOWED": 1, "TERMINAL_CONNECTED": 2, "SERIES_BARS_COUNT": 0,
    "EMPTY_VALUE": DBL_MAX, "DBL_MAX": DBL_MAX, "DBL_MIN": 2.2250738585072014e-308, "INT_MAX": 2147483647,
    "INT_MIN": -2147483648, "LONG_MAX": 9223372036854775807, "UINT_MAX": 4294967295, "EMPTY": -1,
    "WRONG_VALUE": -1, "CHARTS_MAX": 100, "M_PI": math.pi, "M_E": math.e, "CLR_NONE": -1,
    "TIME_DATE": 1, "TIME_MINUTES": 2, "TIME_SECONDS": 4, "MODE_ASCEND": 0, "MODE_DESCEND": 1,
    "WHOLE_ARRAY": 0, "OBJ_ARROW": 22, "OBJ_HLINE": 1, "OBJ_VLINE": 0, "OBJ_TREND": 2, "OBJ_LABEL": 23,
    "OBJ_TEXT": 21, "OBJPROP_COLOR": 6, "OBJPROP_PRICE": 20, "OBJPROP_TIME": 19,
    "ERR_NO_ERROR": 0, "ERR_NO_RESULT": 1, "ERR_INVALID_STOPS": 130, "ERR_INVALID_TRADE_VOLUME": 131,
    "ERR_NOT_ENOUGH_MONEY": 134, "ERR_REQUOTE": 138, "ERR_TRADE_CONTEXT_BUSY": 146,
}

PERIOD_LABEL = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080, "1mo": 43200}


def _dt(sec):
    return datetime.fromtimestamp(int(sec), tz=timezone.utc)


def mql_format(fmt: str, args: list) -> str:
    """printf-style formatting (StringFormat / PrintFormat)."""
    out = []
    ai = 0
    for m in re.finditer(r"%%|%([-+ 0#]*)(\d+|\*)?(?:\.(\d+|\*))?(h|l|ll|I64|I32)?([diouxXeEfgGcsS])|[^%]+|%", fmt):
        tok = m.group(0)
        if tok == "%%":
            out.append("%")
            continue
        if not tok.startswith("%") or m.group(5) is None:
            out.append(tok)
            continue
        flags, width, prec, _len, conv = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        if width == "*":
            width = str(int(args[ai])) if ai < len(args) else ""
            ai += 1
        if prec == "*":
            prec = str(int(args[ai])) if ai < len(args) else ""
            ai += 1
        v = args[ai] if ai < len(args) else ""
        ai += 1
        spec = "%" + (flags or "") + (width or "") + ("." + prec if prec else "")
        try:
            if conv in "diouxX":
                out.append((spec + ("d" if conv in "iu" else conv)) % int(v))
            elif conv in "eEfgG":
                out.append((spec + conv) % float(v))
            elif conv == "c":
                out.append(chr(int(v)))
            else:
                out.append((spec + "s") % (v if isinstance(v, str) else fmt_value(v)))
        except (TypeError, ValueError):
            out.append(str(v))
    return "".join(out)


class MqlApi:
    def __init__(self, adapter):
        self.ad = adapter
        self.handles: dict[int, tuple[IndSeries, int]] = {}
        self.series_cache: dict[tuple, IndSeries] = {}
        self.selected: tuple[str, object] | None = None      # MQL4 OrderSelect
        self.pos_selected: Trade | None = None               # MQL5 PositionSelect
        self.ord_selected = None                             # MQL5 OrderSelect (pending)
        self.last_error = 0
        self.magic_default = 0
        self.stopped = False
        self.comment = ""
        self.classes = {"CTrade": lambda: CTrade(self), "CPositionInfo": lambda: CPositionInfo(self),
                        "CSymbolInfo": lambda: CSymbolInfo(self), "CAccountInfo": lambda: CAccountInfo(self),
                        "COrderInfo": lambda: COrderInfo(self), "CDealInfo": lambda: CDealInfo(self)}
        self.price = Price(adapter.bars)
        self.warned: set[str] = set()

    # ------------------------------------------------------------------ helpers
    @property
    def i(self) -> int:
        return self.ad.ctx.i

    @property
    def broker(self):
        return self.ad.ctx.broker

    @property
    def bars(self):
        return self.ad.bars

    def bid(self) -> float:
        return float(self.bars.open[self.i])

    def ask(self) -> float:
        return self.bid() + self.ad.ctx.settings.spread

    def point(self) -> float:
        return self.ad.ctx.settings.tick_size

    def digits(self) -> int:
        p = self.point()
        return max(0, int(round(-math.log10(p)))) if p and p < 1 else 0

    def warn(self, key, text):
        if key not in self.warned:
            self.warned.add(key)
            self.ad.ctx.log("warn", text)

    def check_tf(self, tf, line):
        if tf in (0, None):
            return
        mine = PERIOD_LABEL.get(self.bars.timeframe)
        if mine is not None and int(tf) != mine:
            self.warn(f"tf{tf}", f"Line {line}: the EA asks for timeframe {tf} min but the data is "
                                 f"{self.bars.timeframe}; using the chart timeframe.")

    def check_symbol(self, sym, line):
        if sym not in (None, "", 0) and isinstance(sym, str) and sym.upper() not in (self.bars.symbol.upper(), self.ad.symbol.upper()):
            self.warn(f"sym{sym}", f"Line {line}: the EA reads symbol '{sym}', but only "
                                   f"{self.ad.symbol} is loaded; using it instead.")

    def parse_datetime(self, s: str) -> int:
        s = s.strip()
        for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                pass
        return 0

    # ------------------------------------------------------------------ names
    def name(self, n: str, line: int):
        if n in CONST:
            return CONST[n]
        i = self.i
        if n in ("Bid",):
            return self.bid()
        if n == "Ask":
            return self.ask()
        if n in ("Point", "_Point"):
            return self.point()
        if n in ("Digits", "_Digits"):
            return self.digits()
        if n in ("Bars",):
            return i + 1
        if n in ("_Symbol",):
            return self.ad.symbol
        if n in ("_Period",):
            return PERIOD_LABEL.get(self.bars.timeframe, 0)
        if n in ("_LastError",):
            return self.last_error
        if n in ("_StopFlag", "IsStopped"):
            return False
        if n in ("Close", "Open", "High", "Low", "Time", "Volume"):
            return SeriesView(self, n.lower())
        if n.startswith("clr") or n.startswith("Color"):
            return 0
        if n.startswith(("OBJPROP_", "OBJ_", "ANCHOR_", "STYLE_", "ALIGN_", "CORNER_", "CHART_", "FONT_",
                         "BORDER_", "SYMBOL_", "ACCOUNT_", "TRADE_", "ORDER_", "DEAL_", "POSITION_", "TERMINAL_",
                         "MQL_", "ERR_", "REASON_", "INDICATOR_", "DRAW_", "PLOT_", "ENUM_")):
            self.warn(n, f"Line {line}: constant {n} isn't modelled; treated as 0.")
            return 0
        raise ScriptError(f"'{n}' is not declared.", line=line, hint="Check the spelling or declare it.")

    # ------------------------------------------------------------------ calls
    def call(self, name: str, arg_nodes: list, interp, line: int):
        fn = FUNCS.get(name)
        if fn is None:
            if name in ("iCustom", "iCustom4", "IndicatorCreate"):
                raise UnsupportedFeature(f"{name}() isn't supported: custom indicator files (.ex4/.ex5) can't be loaded.",
                                         line=line, hint="Re-implement the indicator logic inside the EA.")
            if name in NOOPS:
                return NOOPS[name]
            raise UnsupportedFeature(f"{name}() isn't supported yet.", line=line,
                                     hint="Tickbench runs the common MQL subset; this function is missing.")
        args = [interp.eval(a) for a in arg_nodes]
        try:
            return fn(self, args, line, arg_nodes, interp)
        except (ScriptError, UnsupportedFeature):
            raise
        except IndexError as e:
            raise ScriptError(f"{name}(): not enough arguments.", line=line) from e

    # ------------------------------------------------------------------ indicators
    def series(self, kind: str, params: tuple, n_out: int) -> IndSeries:
        key = (kind, params)
        s = self.series_cache.get(key)
        if s is not None:
            return s
        P = self.price
        if kind == "ma":
            period, method, applied = params
            factory = lambda: MA_FACTORY.get(int(method), ind.SMA)(int(period))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied), j, f),)  # noqa: E731
        elif kind == "rsi":
            period, applied = params
            factory = lambda: ind.RSI(int(period))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied), j, f),)  # noqa: E731
        elif kind == "macd":
            fast, slow, sig, applied = params
            factory = lambda: MACD_MT(int(fast), int(slow), int(sig))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied), j, f),)  # noqa: E731
        elif kind == "atr":
            (period,) = params
            factory = lambda: ATR_MT(int(period))  # noqa: E731
            inputs = lambda j, f: P.hlc(j, f)  # noqa: E731
        elif kind == "bands":
            period, dev, applied = params
            factory = lambda: Bands_MT(int(period), float(dev))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied), j, f),)  # noqa: E731
        elif kind == "stoch":
            k, d, slowing, method, field = params
            factory = lambda: Stoch_MT(int(k), int(d), int(slowing), int(method))  # noqa: E731
            if int(field) == 1:
                inputs = lambda j, f: (P.get(0, j, f),) * 3  # noqa: E731
            else:
                inputs = lambda j, f: P.hlc(j, f)  # noqa: E731
        elif kind == "cci":
            period, applied = params
            factory = lambda: ind.CCI(int(period))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied) if applied else 5, j, f),)  # noqa: E731
        elif kind == "momentum":
            period, applied = params
            factory = lambda: Momentum_MT(int(period))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied), j, f),)  # noqa: E731
        elif kind == "adx":
            (period,) = params
            factory = lambda: ADX_MT(int(period))  # noqa: E731
            inputs = lambda j, f: P.hlc(j, f)  # noqa: E731
            self.warn("adx", "iADX uses Wilder's DMI/ADX; values can differ slightly from MetaTrader's.")
        elif kind == "stddev":
            period, applied = params
            factory = lambda: ind.Stdev(int(period))  # noqa: E731
            inputs = lambda j, f: (P.get(int(applied), j, f),)  # noqa: E731
        else:
            raise UnsupportedFeature(f"Indicator {kind} isn't supported.")
        s = IndSeries(self.bars, factory, inputs, n_out)
        self.series_cache[key] = s
        return s

    def new_handle(self, s: IndSeries, ma_shift: int = 0) -> int:
        h = 10 + len(self.handles)
        self.handles[h] = (s, int(ma_shift))
        return h

    def ind_value(self, s: IndSeries, buf: int, shift: int, ma_shift: int = 0) -> float:
        v = s.value(int(buf), int(shift) + int(ma_shift), self.i)
        return 0.0 if v != v else v  # MetaTrader's built-in indicators hold 0.0 during their warm-up bars

    # ------------------------------------------------------------------ trading helpers
    def lots_to_qty(self, lots) -> float:
        return float(lots)

    def market(self, side: int, lots: float, sl: float, tp: float, comment: str = "", magic: int = 0,
               reason: str = "") -> Trade | None:
        b = self.broker
        hedging = self.ad.ctx.settings.hedging
        before = len(b.trades)
        self.ad.ctx.log("signal", reason or f"{'Buy' if side > 0 else 'Sell'} {lots:g} lots")
        o = b.submit_market(side, self.lots_to_qty(lots), sl=sl or None, tp=tp or None, immediate=True,
                            magic=int(magic or self.magic_default), comment=comment or "", reason=reason,
                            net=not hedging)
        if o is None:
            return None
        new = [t for t in b.trades[before:] if t.order_id == o.id]
        return new[0] if new else None

    def pending(self, kind_code: int, lots: float, price: float, sl: float, tp: float, comment="", magic=0,
                expiration=0):
        side = 1 if kind_code in (2, 4) else -1
        kind = "limit" if kind_code in (2, 3) else "stop"
        exp_bar = None
        if expiration:
            times = self.bars.time
            import bisect
            exp_bar = bisect.bisect_right(times, int(expiration) * 1000) - 1
        o = self.broker.submit_pending(kind, side, float(price), self.lots_to_qty(lots), sl=sl or None, tp=tp or None,
                                       magic=int(magic or self.magic_default), comment=comment or "",
                                       reason=f"{'Buy' if side > 0 else 'Sell'} {kind} @ {price}", expire_bar=exp_bar,
                                       net=not self.ad.ctx.settings.hedging)
        o.placed_bar = self.i - 1  # EA runs at the open, so the order is live for this whole bar
        return o

    def find_trade(self, ticket) -> Trade | None:
        t = int(ticket)
        for tr in self.broker.trades:
            if tr.order_id == t or tr.id == t:
                if tr.is_open:
                    return tr
        for tr in reversed(self.broker.trades):
            if tr.order_id == t or tr.id == t:
                return tr
        return None

    def find_pending(self, ticket):
        for o in self.broker.pending:
            if o.id == int(ticket):
                return o
        return None

    def pool(self):
        """MQL4 MODE_TRADES pool: open trades then pending orders."""
        return [("trade", t) for t in self.broker.open] + [("pending", o) for o in self.broker.pending]

    def profit_of(self, t: Trade) -> float:
        if t.is_open:
            px = self.bid() if t.side > 0 else self.ask()
            return t.unrealized(px, self.ad.ctx.settings.point_value)
        return t.pnl

    def close_trade(self, t: Trade, lots=None, reason="Closed by EA"):
        px = self.bid()
        if lots is not None and lots >= t.qty - 1e-12:
            lots = None
        self.broker.close_trade(t, px, reason, qty=lots)
        return True


class SeriesView:
    """MQL4 predefined arrays Close[], Open[] … indexed by shift."""

    def __init__(self, api: MqlApi, field: str):
        self.api = api
        self.field = field

    def series_get(self, shift: int):
        return _series_value(self.api, self.field, shift)


def _series_value(api: MqlApi, field: str, shift: int):
    i = api.i
    j = i - int(shift)
    b = api.bars
    if j < 0 or shift < 0:
        return 0.0 if field != "time" else 0
    if field == "time":
        return int(b.time[j] // 1000)
    if field == "volume":
        return 1 if shift == 0 else int(b.volume[j])
    if shift == 0:
        return float(b.open[j])
    return float(getattr(b, field)[j])


# ===================================================================================== functions
FUNCS: dict = {}
NOOPS = {n: True for n in (
    "ObjectCreate", "ObjectDelete", "ObjectSet", "ObjectSetInteger", "ObjectSetDouble", "ObjectSetString",
    "ObjectSetText", "ObjectMove", "ObjectsDeleteAll", "ChartRedraw", "WindowRedraw", "EventSetTimer",
    "EventKillTimer", "EventSetMillisecondTimer", "PlaySound", "SendMail", "SendNotification", "SendFTP",
    "ChartSetInteger", "ChartSetSymbolPeriod", "HideTestIndicators", "TesterHideIndicators", "IndicatorRelease",
    "SetIndexBuffer", "IndicatorSetString", "IndicatorSetInteger", "IndicatorSetDouble", "PlotIndexSetInteger",
    "ResetLastError", "Sleep", "RefreshRates", "ChartIndicatorAdd", "GlobalVariableSet", "FileClose",
    "TextSetFont", "LabelCreate", "ButtonCreate")}
NOOPS["GlobalVariableGet"] = 0.0
NOOPS["GlobalVariableCheck"] = False
NOOPS["ObjectFind"] = -1
NOOPS["ObjectsTotal"] = 0
NOOPS["FileOpen"] = -1


def f(*names):
    def deco(fn):
        for n in names:
            FUNCS[n] = fn
        return fn
    return deco


def _a(args, i, default=0):
    return args[i] if i < len(args) and args[i] is not None else default


# ----- output
@f("Print")
def _print(api, args, line, nodes, it):
    api.ad.ctx.log("log", "".join(a if isinstance(a, str) else fmt_value(a) for a in args))


@f("PrintFormat")
def _printformat(api, args, line, nodes, it):
    api.ad.ctx.log("log", mql_format(str(args[0]), args[1:]))


@f("Alert")
def _alert(api, args, line, nodes, it):
    api.ad.ctx.log("log", "[alert] " + "".join(a if isinstance(a, str) else fmt_value(a) for a in args))


@f("Comment")
def _comment(api, args, line, nodes, it):
    api.comment = "".join(a if isinstance(a, str) else fmt_value(a) for a in args)


@f("GetLastError")
def _gle(api, args, line, nodes, it):
    e = api.last_error
    api.last_error = 0
    return e


@f("IsTesting", "IsOptimization", "IsTradeAllowed", "IsExpertEnabled", "IsConnected", "TerminalInfoInteger",
   "MQLInfoInteger", "IsVisualMode")
def _true(api, args, line, nodes, it):
    return True


@f("IsStopped", "IsDemo")
def _false(api, args, line, nodes, it):
    return False


@f("ExpertRemove")
def _expert_remove(api, args, line, nodes, it):
    api.stopped = True
    api.ad.ctx.log("info", "ExpertRemove() called: the EA stops trading.")


@f("GetTickCount", "GetMicrosecondCount")
def _ticks(api, args, line, nodes, it):
    return int(api.bars.time[api.i])


# ----- strings / conversion
@f("StringFormat")
def _sformat(api, args, line, nodes, it):
    return mql_format(str(args[0]), args[1:])


@f("DoubleToString", "DoubleToStr")
def _d2s(api, args, line, nodes, it):
    d = int(_a(args, 1, 8))
    return f"{float(args[0]):.{max(0, min(d, 16))}f}"


@f("IntegerToString")
def _i2s(api, args, line, nodes, it):
    return str(int(args[0]))


@f("StringToDouble", "StrToDouble")
def _s2d(api, args, line, nodes, it):
    return cast("double", args[0])


@f("StringToInteger", "StrToInteger")
def _s2i(api, args, line, nodes, it):
    return cast("int", args[0])


@f("NormalizeDouble")
def _norm(api, args, line, nodes, it):
    return round(float(args[0]), int(_a(args, 1, 0)))


@f("StringLen")
def _slen(api, args, line, nodes, it):
    return len(args[0] or "")


@f("StringFind")
def _sfind(api, args, line, nodes, it):
    return str(args[0]).find(str(args[1]), int(_a(args, 2, 0)))


@f("StringSubstr")
def _ssub(api, args, line, nodes, it):
    s, start = str(args[0]), int(_a(args, 1, 0))
    n = int(_a(args, 2, -1))
    return s[start:] if n < 0 else s[start:start + n]


@f("StringConcatenate")
def _sconcat(api, args, line, nodes, it):
    if nodes and len(args) > 1 and isinstance(args[0], str) and nodes[0].kind == "name":
        joined = "".join(a if isinstance(a, str) else fmt_value(a) for a in args[1:])
        it.assign_to(nodes[0], joined)  # MQL5 form: StringConcatenate(string &out, ...)
        return len(joined)
    return "".join(a if isinstance(a, str) else fmt_value(a) for a in args)


@f("StringToUpper")
def _supper(api, args, line, nodes, it):
    it.assign_to(nodes[0], str(args[0]).upper())
    return True


@f("StringToLower")
def _slower(api, args, line, nodes, it):
    it.assign_to(nodes[0], str(args[0]).lower())
    return True


@f("StringTrimLeft", "StringTrimRight")
def _strim(api, args, line, nodes, it):
    return str(args[0]).strip()


@f("EnumToString")
def _enum2s(api, args, line, nodes, it):
    return str(args[0])


@f("CharToString", "CharToStr")
def _c2s(api, args, line, nodes, it):
    return chr(int(args[0]))


@f("ColorToString")
def _clr2s(api, args, line, nodes, it):
    return str(args[0])


# ----- math
for _n, _fn in {"MathAbs": abs, "fabs": abs, "MathSqrt": math.sqrt, "sqrt": math.sqrt, "MathFloor": math.floor,
                "floor": math.floor, "MathCeil": math.ceil, "ceil": math.ceil, "MathLog": math.log, "log": math.log,
                "MathLog10": math.log10, "log10": math.log10, "MathExp": math.exp, "exp": math.exp,
                "MathSin": math.sin, "MathCos": math.cos, "MathTan": math.tan, "MathArctan": math.atan,
                "MathArcsin": math.asin, "MathArccos": math.acos}.items():
    FUNCS[_n] = (lambda g: (lambda api, args, line, nodes, it: g(args[0])))(_fn)
FUNCS["MathRound"] = FUNCS["round"] = lambda api, args, line, nodes, it: float(math.floor(args[0] + 0.5)) if args[0] >= 0 else -float(math.floor(-args[0] + 0.5))
FUNCS["MathMax"] = FUNCS["fmax"] = FUNCS["MathMax"] = lambda api, args, line, nodes, it: max(args[0], args[1])
FUNCS["MathMin"] = FUNCS["fmin"] = lambda api, args, line, nodes, it: min(args[0], args[1])
FUNCS["MathPow"] = FUNCS["pow"] = lambda api, args, line, nodes, it: math.pow(args[0], args[1])
FUNCS["MathMod"] = FUNCS["fmod"] = lambda api, args, line, nodes, it: math.fmod(args[0], args[1])
FUNCS["MathRand"] = FUNCS["rand"] = lambda api, args, line, nodes, it: random.randint(0, 32767)
FUNCS["MathSrand"] = FUNCS["srand"] = lambda api, args, line, nodes, it: random.seed(int(args[0])) or 0
FUNCS["MathIsValidNumber"] = lambda api, args, line, nodes, it: isinstance(args[0], (int, float)) and math.isfinite(args[0])


# ----- arrays
@f("ArrayResize")
def _aresize(api, args, line, nodes, it):
    arr, n = args[0], int(args[1])
    if not isinstance(arr, MqlArr):
        raise ScriptError("ArrayResize needs an array.", line=line)
    from .interp import default_value
    if n < len(arr.items):
        if arr.as_series:
            arr.items = arr.items[len(arr.items) - n:]
        else:
            del arr.items[n:]
    else:
        pad = [default_value(arr.elem_type)] * (n - len(arr.items))
        arr.items = (pad + arr.items) if arr.as_series else (arr.items + pad)
    return n


@f("ArraySize", "ArrayRange")
def _asize(api, args, line, nodes, it):
    return len(args[0]) if isinstance(args[0], MqlArr) else 0


@f("ArraySetAsSeries")
def _aseries(api, args, line, nodes, it):
    if isinstance(args[0], MqlArr):
        args[0].as_series = bool(args[1])
    return True


@f("ArrayGetAsSeries", "ArrayIsSeries")
def _agetseries(api, args, line, nodes, it):
    return isinstance(args[0], MqlArr) and args[0].as_series


@f("ArrayInitialize")
def _ainit(api, args, line, nodes, it):
    arr = args[0]
    arr.items = [args[1]] * len(arr.items)
    return len(arr.items)


@f("ArrayFill")
def _afill(api, args, line, nodes, it):
    arr, start, count, v = args[0], int(args[1]), int(args[2]), args[3]
    for k in range(start, min(start + count, len(arr.items))):
        arr.items[k] = v


@f("ArrayFree")
def _afree(api, args, line, nodes, it):
    args[0].items = []


def _arr_extreme(use_max):
    def fn(api, args, line, nodes, it):
        arr = args[0]
        count = int(_a(args, 1, 0)) or len(arr)
        start = int(_a(args, 2, 0))
        vals = [arr.get(k) for k in range(start, min(start + count, len(arr)))]
        if not vals:
            return -1
        best = max(vals) if use_max else min(vals)
        return start + vals.index(best)
    return fn


FUNCS["ArrayMaximum"] = _arr_extreme(True)
FUNCS["ArrayMinimum"] = _arr_extreme(False)


@f("ArrayCopy")
def _acopy(api, args, line, nodes, it):
    dst, src = args[0], args[1]
    dst_start, src_start = int(_a(args, 2, 0)), int(_a(args, 3, 0))
    count = int(_a(args, 4, 0)) or (len(src) - src_start)
    vals = [src.get(k) for k in range(src_start, min(len(src), src_start + count))]
    need = dst_start + len(vals)
    if len(dst) < need:
        _aresize(api, [dst, need], line, nodes, it)
    for k, v in enumerate(vals):
        dst.set(dst_start + k, v)
    return len(vals)


@f("ArraySort")
def _asort(api, args, line, nodes, it):
    args[0].items.sort()
    return True


# ----- time
@f("TimeCurrent", "TimeTradeServer", "TimeLocal", "TimeGMT")
def _now(api, args, line, nodes, it):
    return int(api.bars.time[api.i] // 1000)


@f("TimeToString", "TimeToStr")
def _t2s(api, args, line, nodes, it):
    mode = int(_a(args, 1, 3))
    d = _dt(args[0])
    s = d.strftime("%Y.%m.%d") if mode & 1 else ""
    if mode & 4:
        s += (" " if s else "") + d.strftime("%H:%M:%S")
    elif mode & 2:
        s += (" " if s else "") + d.strftime("%H:%M")
    return s


@f("StringToTime", "StrToTime")
def _s2t(api, args, line, nodes, it):
    return api.parse_datetime(str(args[0]))


@f("TimeToStruct")
def _t2struct(api, args, line, nodes, it):
    d = _dt(args[0])
    s = args[1]
    for k, v in dict(year=d.year, mon=d.month, day=d.day, hour=d.hour, min=d.minute, sec=d.second,
                     day_of_week=d.isoweekday() % 7, day_of_year=d.timetuple().tm_yday - 1).items():
        setattr(s, k, v)
    return True


@f("StructToTime")
def _struct2t(api, args, line, nodes, it):
    s = args[0]
    return int(datetime(int(s.year), int(s.mon), int(s.day), int(s.hour), int(s.min), int(s.sec),
                        tzinfo=timezone.utc).timestamp())


def _tpart(attr):
    def fn(api, args, line, nodes, it):
        d = _dt(args[0]) if args else _dt(api.bars.time[api.i] // 1000)
        if attr == "dow":
            return d.isoweekday() % 7
        if attr == "doy":
            return d.timetuple().tm_yday
        return getattr(d, attr)
    return fn


for _name, _attr in (("TimeYear", "year"), ("TimeMonth", "month"), ("TimeDay", "day"), ("TimeHour", "hour"),
                     ("TimeMinute", "minute"), ("TimeSeconds", "second"), ("TimeDayOfWeek", "dow"),
                     ("TimeDayOfYear", "doy"), ("Year", "year"), ("Month", "month"), ("Day", "day"),
                     ("Hour", "hour"), ("Minute", "minute"), ("Seconds", "second"), ("DayOfWeek", "dow"),
                     ("DayOfYear", "doy")):
    FUNCS[_name] = _tpart(_attr)


# ----- symbol / account / market
@f("Symbol")
def _symbol(api, args, line, nodes, it):
    return api.ad.symbol


@f("Period")
def _period(api, args, line, nodes, it):
    return PERIOD_LABEL.get(api.bars.timeframe, 0)


@f("Bars", "iBars")
def _bars(api, args, line, nodes, it):
    return api.i + 1


@f("MarketInfo")
def _marketinfo(api, args, line, nodes, it):
    mode = int(args[1])
    s = api.ad.ctx.settings
    return {9: api.bid(), 10: api.ask(), 11: api.point(), 12: api.digits(),
            13: round(s.spread / api.point()) if api.point() else 0, 14: 0, 15: s.point_value,
            16: s.point_value * api.point(), 17: api.point(), 23: 0.01, 24: 0.01, 25: 1000.0, 33: 0,
            18: 0.0, 19: 0.0, 32: 0.0, 1: float(api.bars.low[api.i - 1]) if api.i else api.bid(),
            2: float(api.bars.high[api.i - 1]) if api.i else api.bid()}.get(mode, 0.0)


@f("SymbolInfoDouble")
def _sid(api, args, line, nodes, it):
    prop = int(args[1])
    s = api.ad.ctx.settings
    v = {400: api.bid(), 401: api.ask(), 402: api.point(), 403: s.point_value * api.point(), 404: api.point(),
         405: 0.01, 406: 1000.0, 407: 0.01, 408: s.point_value, 409: api.bid()}.get(prop, 0.0)
    if len(nodes) > 2:
        it.assign_to(nodes[2], v)
        return True
    return v


@f("SymbolInfoInteger")
def _sii(api, args, line, nodes, it):
    prop = int(args[1])
    s = api.ad.ctx.settings
    v = {420: api.digits(), 421: round(s.spread / api.point()) if api.point() else 0, 422: 0, 423: 0, 424: 1}.get(prop, 0)
    if len(nodes) > 2:
        it.assign_to(nodes[2], v)
        return True
    return v


@f("SymbolInfoString")
def _sis(api, args, line, nodes, it):
    return api.ad.symbol


@f("SymbolInfoTick")
def _sitick(api, args, line, nodes, it):
    t = args[1]
    t.bid, t.ask, t.last = api.bid(), api.ask(), api.bid()
    t.time = int(api.bars.time[api.i] // 1000)
    t.time_msc = int(api.bars.time[api.i])
    t.volume = 1
    return True


@f("SymbolSelect", "SymbolIsSynchronized")
def _symsel(api, args, line, nodes, it):
    return True


@f("AccountBalance")
def _ab(api, args, line, nodes, it):
    return api.broker.cash


@f("AccountEquity")
def _ae(api, args, line, nodes, it):
    return api.broker.equity(api.bid())


@f("AccountFreeMargin", "AccountFreeMarginCheck")
def _afm(api, args, line, nodes, it):
    return api.broker.equity(api.bid())


@f("AccountProfit")
def _ap(api, args, line, nodes, it):
    return sum(api.profit_of(t) for t in api.broker.open)


@f("AccountLeverage")
def _alev(api, args, line, nodes, it):
    return 100


@f("AccountNumber")
def _anum(api, args, line, nodes, it):
    return 1


@f("AccountCurrency", "AccountName", "AccountServer", "AccountCompany")
def _astr(api, args, line, nodes, it):
    return "USD"


@f("AccountInfoDouble")
def _aid(api, args, line, nodes, it):
    p = int(args[0])
    eq = api.broker.equity(api.bid())
    return {500: api.broker.cash, 501: eq, 502: eq, 503: sum(api.profit_of(t) for t in api.broker.open),
            504: 0.0, 505: 0.0, 506: 0.0}.get(p, 0.0)


@f("AccountInfoInteger")
def _aii(api, args, line, nodes, it):
    return {510: 100, 511: 1, 512: 0, 513: 1, 514: 1}.get(int(args[0]), 0)


@f("AccountInfoString")
def _ais(api, args, line, nodes, it):
    return "USD"


# ----- price series
def _ifield(field):
    def fn(api, args, line, nodes, it):
        api.check_symbol(args[0], line)
        api.check_tf(args[1], line)
        return _series_value(api, field, int(args[2]))
    return fn


for _name, _field in (("iClose", "close"), ("iOpen", "open"), ("iHigh", "high"), ("iLow", "low"),
                      ("iTime", "time"), ("iVolume", "volume"), ("iTickVolume", "volume")):
    FUNCS[_name] = _ifield(_field)


def _iextreme(use_max):
    def fn(api, args, line, nodes, it):
        mode, count, start = int(_a(args, 2, 2)), int(_a(args, 3, 0)), int(_a(args, 4, 0))
        field = {0: "open", 1: "low", 2: "high", 3: "close", 4: "volume", 5: "time"}.get(mode, "high")
        if count <= 0:
            count = api.i + 1 - start
        vals = [(_series_value(api, field, s), s) for s in range(start, min(start + count, api.i + 1))]
        if not vals:
            return -1
        best = max(vals, key=lambda x: (x[0], -x[1])) if use_max else min(vals, key=lambda x: (x[0], x[1]))
        return best[1]
    return fn


FUNCS["iHighest"] = _iextreme(True)
FUNCS["iLowest"] = _iextreme(False)


@f("iBarShift")
def _ibarshift(api, args, line, nodes, it):
    t = int(args[2]) * 1000
    import bisect
    j = bisect.bisect_right(api.bars.time, t) - 1
    return max(-1, api.i - j) if j >= 0 else -1


def _copy_series(field):
    def fn(api, args, line, nodes, it):
        api.check_symbol(args[0], line)
        start, count, arr = int(args[2]), int(args[3]), args[4]
        vals = []
        for shift in range(start + count - 1, start - 1, -1):  # oldest first
            if api.i - shift >= 0:
                vals.append(_series_value(api, field, shift))
        arr.items = vals
        return len(vals) if vals else -1
    return fn


for _name, _field in (("CopyClose", "close"), ("CopyOpen", "open"), ("CopyHigh", "high"), ("CopyLow", "low"),
                      ("CopyTime", "time"), ("CopyTickVolume", "volume"), ("CopyRealVolume", "volume")):
    FUNCS[_name] = _copy_series(_field)


@f("CopyRates")
def _copyrates(api, args, line, nodes, it):
    start, count, arr = int(args[2]), int(args[3]), args[4]
    vals = []
    for shift in range(start + count - 1, start - 1, -1):
        if api.i - shift >= 0:
            vals.append(MStruct("MqlRates", time=_series_value(api, "time", shift),
                                open=_series_value(api, "open", shift), high=_series_value(api, "high", shift),
                                low=_series_value(api, "low", shift), close=_series_value(api, "close", shift),
                                tick_volume=_series_value(api, "volume", shift), spread=0, real_volume=0))
    arr.items = vals
    return len(vals) if vals else -1


# ----- indicators (MQL4 returns a value; MQL5 returns a handle)
def _is_mql4(api, n_args, mql4_count):
    return api.ad.dialect == "mql4" or n_args >= mql4_count


@f("iMA")
def _ima(api, args, line, nodes, it):
    api.check_tf(args[1], line)
    if _is_mql4(api, len(args), 7):
        period, ma_shift, method, applied, shift = args[2], args[3], args[4], args[5], args[6]
        s = api.series("ma", (int(period), int(method), int(applied)), 1)
        return api.ind_value(s, 0, int(shift), int(ma_shift))
    period, ma_shift, method, applied = args[2], args[3], args[4], args[5]
    return api.new_handle(api.series("ma", (int(period), int(method), int(applied)), 1), int(ma_shift))


@f("iRSI")
def _irsi(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 5):
        return api.ind_value(api.series("rsi", (int(args[2]), int(args[3])), 1), 0, int(args[4]))
    return api.new_handle(api.series("rsi", (int(args[2]), int(args[3])), 1))


@f("iMACD")
def _imacd(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 8):
        s = api.series("macd", (int(args[2]), int(args[3]), int(args[4]), int(args[5])), 2)
        return api.ind_value(s, int(args[6]), int(args[7]))
    return api.new_handle(api.series("macd", (int(args[2]), int(args[3]), int(args[4]), int(args[5])), 2))


@f("iATR")
def _iatr(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 4):
        return api.ind_value(api.series("atr", (int(args[2]),), 1), 0, int(args[3]))
    return api.new_handle(api.series("atr", (int(args[2]),), 1))


@f("iBands")
def _ibands(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 8):
        # MQL4: (sym, tf, period, deviation, bands_shift, applied, mode, shift); mode 0 main, 1 upper, 2 lower
        s = api.series("bands", (int(args[2]), float(args[3]), int(args[5])), 3)
        return api.ind_value(s, int(args[6]), int(args[7]), int(args[4]))
    # MQL5: (sym, tf, period, bands_shift, deviation, applied)
    return api.new_handle(api.series("bands", (int(args[2]), float(args[4]), int(args[5])), 3), int(args[3]))


@f("iStochastic")
def _istoch(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 9):
        s = api.series("stoch", (int(args[2]), int(args[3]), int(args[4]), int(args[5]), int(args[6])), 2)
        return api.ind_value(s, int(args[7]), int(args[8]))
    return api.new_handle(api.series("stoch", (int(args[2]), int(args[3]), int(args[4]), int(args[5]), int(args[6])), 2))


@f("iCCI")
def _icci(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 5):
        return api.ind_value(api.series("cci", (int(args[2]), int(args[3])), 1), 0, int(args[4]))
    return api.new_handle(api.series("cci", (int(args[2]), int(args[3])), 1))


@f("iMomentum")
def _imom(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 5):
        return api.ind_value(api.series("momentum", (int(args[2]), int(args[3])), 1), 0, int(args[4]))
    return api.new_handle(api.series("momentum", (int(args[2]), int(args[3])), 1))


@f("iStdDev")
def _istd(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 7):
        return api.ind_value(api.series("stddev", (int(args[2]), int(args[5])), 1), 0, int(args[6]), int(args[3]))
    return api.new_handle(api.series("stddev", (int(args[2]), int(args[5])), 1), int(args[3]))


@f("iADX")
def _iadx(api, args, line, nodes, it):
    if _is_mql4(api, len(args), 6):
        return api.ind_value(api.series("adx", (int(args[2]),), 3), int(args[4]), int(args[5]))
    return api.new_handle(api.series("adx", (int(args[2]),), 3))


@f("CopyBuffer")
def _copybuffer(api, args, line, nodes, it):
    h, buf, start, count, arr = int(args[0]), int(args[1]), int(args[2]), int(args[3]), args[4]
    if h not in api.handles:
        raise ScriptError(f"CopyBuffer: invalid indicator handle {h}.", line=line,
                          hint="Create the handle in OnInit with iMA/iRSI/... and check it isn't INVALID_HANDLE.")
    s, ma_shift = api.handles[h]
    vals = []
    for shift in range(start + count - 1, start - 1, -1):
        if api.i - shift - ma_shift >= 0:
            v = s.value(buf, shift + ma_shift, api.i)
            vals.append(0.0 if v != v else v)  # warm-up bars read as 0.0, as in MetaTrader
    if not isinstance(arr, MqlArr):
        raise ScriptError("CopyBuffer needs an array as the last argument.", line=line)
    arr.items = vals
    return len(vals) if vals else -1


@f("BarsCalculated")
def _barscalc(api, args, line, nodes, it):
    return api.i + 1


CONST["INVALID_HANDLE"] = -1


# ----- MQL4 trading
@f("OrderSend")
def _ordersend(api, args, line, nodes, it):
    if api.stopped:
        return -1
    if args and isinstance(args[0], MStruct):  # MQL5 OrderSend(request, result)
        return _ordersend5(api, args[0], args[1], line)
    sym, cmd, lots, price = args[0], int(args[1]), float(args[2]), float(_a(args, 3, 0.0))
    sl, tp = float(_a(args, 5, 0.0)), float(_a(args, 6, 0.0))
    comment, magic, exp = str(_a(args, 7, "")), int(_a(args, 8, 0)), int(_a(args, 9, 0))
    api.check_symbol(sym, line)
    if lots <= 0:
        api.last_error = 131
        return -1
    if cmd in (0, 1):
        side = 1 if cmd == 0 else -1
        t = api.market(side, lots, sl, tp, comment, magic, f"OrderSend({'OP_BUY' if side > 0 else 'OP_SELL'}, {lots:g} lots)"
                       + (f" — {comment}" if comment else ""))
        return t.order_id if t else -1
    if cmd in (2, 3, 4, 5):
        o = api.pending(cmd, lots, price, sl, tp, comment, magic, exp)
        return o.id
    api.last_error = 3
    return -1


@f("OrdersTotal")
def _orderstotal(api, args, line, nodes, it):
    if api.ad.dialect == "mql5":
        return len(api.broker.pending)
    return len(api.pool())


@f("OrdersHistoryTotal")
def _ohist(api, args, line, nodes, it):
    return len(api.broker.closed)


@f("OrderSelect")
def _orderselect(api, args, line, nodes, it):
    if api.ad.dialect == "mql5" and len(args) == 1:
        o = api.find_pending(args[0])
        api.ord_selected = o
        return o is not None
    idx, by = int(args[0]), int(_a(args, 1, 0))
    pool_kind = int(_a(args, 2, 0))
    if by == 1:  # by ticket: open, pending, or history
        o = api.find_pending(idx)
        if o is not None:
            api.selected = ("pending", o)
            return True
        t = api.find_trade(idx)
        if t is not None:
            api.selected = ("trade" if t.is_open else "hist", t)
            return True
        return False
    if pool_kind == 1:
        hist = api.broker.closed
        if 0 <= idx < len(hist):
            api.selected = ("hist", hist[idx])
            return True
        return False
    pool = api.pool()
    if 0 <= idx < len(pool):
        api.selected = pool[idx]
        return True
    return False


def _sel(api, line):
    if api.selected is None:
        raise ScriptError("No order selected: call OrderSelect() first.", line=line)
    return api.selected


def _order_attr(attr):
    def fn(api, args, line, nodes, it):
        kind, o = _sel(api, line)
        if kind in ("trade", "hist"):
            t = o
            return {
                "OrderTicket": t.order_id, "OrderType": 0 if t.side > 0 else 1, "OrderLots": t.qty,
                "OrderOpenPrice": t.entry_price, "OrderClosePrice": t.exit_price if t.exit_price is not None else (api.bid() if t.side > 0 else api.ask()),
                "OrderStopLoss": t.sl or 0.0, "OrderTakeProfit": t.tp or 0.0, "OrderProfit": api.profit_of(t) + (t.commission if not t.is_open else 0),
                "OrderMagicNumber": t.magic, "OrderSymbol": api.ad.symbol, "OrderComment": t.comment,
                "OrderOpenTime": t.entry_time // 1000, "OrderCloseTime": (t.exit_time or 0) // 1000,
                "OrderCommission": -t.commission, "OrderSwap": 0.0, "OrderExpiration": 0,
            }[attr]
        code = {("limit", 1): 2, ("limit", -1): 3, ("stop", 1): 4, ("stop", -1): 5}.get((o.kind, o.side), 2)
        return {
            "OrderTicket": o.id, "OrderType": code, "OrderLots": o.qty or 0.0, "OrderOpenPrice": o.price,
            "OrderClosePrice": api.bid(), "OrderStopLoss": o.sl or 0.0, "OrderTakeProfit": o.tp or 0.0,
            "OrderProfit": 0.0, "OrderMagicNumber": o.magic, "OrderSymbol": api.ad.symbol,
            "OrderComment": o.comment, "OrderOpenTime": 0, "OrderCloseTime": 0, "OrderCommission": 0.0,
            "OrderSwap": 0.0, "OrderExpiration": 0,
        }[attr]
    return fn


for _attr in ("OrderTicket", "OrderType", "OrderLots", "OrderOpenPrice", "OrderClosePrice", "OrderStopLoss",
              "OrderTakeProfit", "OrderProfit", "OrderMagicNumber", "OrderSymbol", "OrderComment", "OrderOpenTime",
              "OrderCloseTime", "OrderCommission", "OrderSwap", "OrderExpiration"):
    FUNCS[_attr] = _order_attr(_attr)


@f("OrderClose")
def _orderclose(api, args, line, nodes, it):
    t = api.find_trade(args[0])
    if t is None or not t.is_open:
        api.last_error = 4108
        return False
    lots = float(_a(args, 1, t.qty))
    return api.close_trade(t, lots, "OrderClose()")


@f("OrderCloseBy")
def _ordercloseby(api, args, line, nodes, it):
    a, b = api.find_trade(args[0]), api.find_trade(args[1])
    if a and b:
        api.close_trade(a, None, "OrderCloseBy()")
        api.close_trade(b, None, "OrderCloseBy()")
        return True
    return False


@f("OrderModify")
def _ordermodify(api, args, line, nodes, it):
    ticket, price, sl, tp = args[0], float(args[1]), float(args[2]), float(args[3])
    o = api.find_pending(ticket)
    if o is not None:
        o.price = price if price else o.price
        o.sl, o.tp = (sl or None), (tp or None)
        return True
    t = api.find_trade(ticket)
    if t is None or not t.is_open:
        api.last_error = 4108
        return False
    api.broker.modify(t, sl=sl or None, tp=tp or None, keep_none=False)
    return True


@f("OrderDelete")
def _orderdelete(api, args, line, nodes, it):
    return api.broker.cancel(order_id=int(args[0])) > 0


# ----- MQL5 positions / orders / history
@f("PositionsTotal")
def _ptotal(api, args, line, nodes, it):
    return len(api.broker.open)


@f("PositionGetTicket")
def _pgetticket(api, args, line, nodes, it):
    k = int(args[0])
    if 0 <= k < len(api.broker.open):
        api.pos_selected = api.broker.open[k]
        return api.pos_selected.order_id
    return 0


@f("PositionGetSymbol")
def _pgetsym(api, args, line, nodes, it):
    k = int(args[0])
    if 0 <= k < len(api.broker.open):
        api.pos_selected = api.broker.open[k]
        return api.ad.symbol
    return ""


@f("PositionSelect")
def _pselect(api, args, line, nodes, it):
    api.check_symbol(args[0], line)
    api.pos_selected = api.broker.open[0] if api.broker.open else None
    return api.pos_selected is not None


@f("PositionSelectByTicket")
def _pselticket(api, args, line, nodes, it):
    t = api.find_trade(args[0])
    api.pos_selected = t if t is not None and t.is_open else None
    return api.pos_selected is not None


def _psel(api, line):
    if api.pos_selected is None or not api.pos_selected.is_open:
        return None
    return api.pos_selected


@f("PositionGetInteger")
def _pgi(api, args, line, nodes, it):
    t = _psel(api, line)
    if t is None:
        return 0
    v = {100: 0 if t.side > 0 else 1, 101: t.magic, 102: t.order_id, 103: t.entry_time // 1000, 104: t.order_id,
         105: t.entry_time, 106: 3}.get(int(args[0]), 0)
    if len(nodes) > 1:
        it.assign_to(nodes[1], v)
        return True
    return v


@f("PositionGetDouble")
def _pgd(api, args, line, nodes, it):
    t = _psel(api, line)
    if t is None:
        return 0.0
    v = {110: t.entry_price, 111: t.qty, 112: t.sl or 0.0, 113: t.tp or 0.0, 114: api.profit_of(t),
         115: api.bid() if t.side > 0 else api.ask(), 116: 0.0}.get(int(args[0]), 0.0)
    if len(nodes) > 1:
        it.assign_to(nodes[1], v)
        return True
    return v


@f("PositionGetString")
def _pgs(api, args, line, nodes, it):
    t = _psel(api, line)
    if t is None:
        return ""
    return {120: api.ad.symbol, 121: t.comment}.get(int(args[0]), "")


@f("OrderGetTicket")
def _ogetticket(api, args, line, nodes, it):
    k = int(args[0])
    if 0 <= k < len(api.broker.pending):
        api.ord_selected = api.broker.pending[k]
        return api.ord_selected.id
    return 0


@f("OrderGetInteger")
def _ogi(api, args, line, nodes, it):
    o = api.ord_selected
    if o is None:
        return 0
    code = {("limit", 1): 2, ("limit", -1): 3, ("stop", 1): 4, ("stop", -1): 5}.get((o.kind, o.side), 2)
    return {200: code, 201: o.magic, 202: o.id, 203: 0, 204: 1}.get(int(args[0]), 0)


@f("OrderGetDouble")
def _ogd(api, args, line, nodes, it):
    o = api.ord_selected
    if o is None:
        return 0.0
    return {210: o.price, 211: o.qty or 0.0, 212: o.qty or 0.0, 213: o.sl or 0.0, 214: o.tp or 0.0,
            215: api.bid()}.get(int(args[0]), 0.0)


@f("OrderGetString")
def _ogs(api, args, line, nodes, it):
    o = api.ord_selected
    return "" if o is None else {220: api.ad.symbol, 221: o.comment}.get(int(args[0]), "")


@f("HistorySelect", "HistorySelectByPosition")
def _histsel(api, args, line, nodes, it):
    return True


def _deals(api):
    out = []
    for t in api.broker.trades:
        out.append(("in", t))
        if not t.is_open:
            out.append(("out", t))
    return out


@f("HistoryDealsTotal")
def _hdt(api, args, line, nodes, it):
    return len(_deals(api))


@f("HistoryDealGetTicket")
def _hdgt(api, args, line, nodes, it):
    k = int(args[0])
    d = _deals(api)
    if 0 <= k < len(d):
        kind, t = d[k]
        return t.id * 2 + (1 if kind == "out" else 0)
    return 0


def _deal(api, ticket):
    ticket = int(ticket)
    tid, out = divmod(ticket, 2)
    for t in api.broker.trades:
        if t.id == tid:
            return ("out" if out else "in"), t
    return None, None


@f("HistoryDealGetInteger")
def _hdgi(api, args, line, nodes, it):
    kind, t = _deal(api, args[0])
    if t is None:
        return 0
    side = t.side if kind == "in" else -t.side
    return {300: 0 if side > 0 else 1, 301: 0 if kind == "in" else 1, 302: t.magic,
            303: (t.entry_time if kind == "in" else t.exit_time) // 1000, 304: t.order_id, 305: t.order_id}.get(int(args[1]), 0)


@f("HistoryDealGetDouble")
def _hdgd(api, args, line, nodes, it):
    kind, t = _deal(api, args[0])
    if t is None:
        return 0.0
    return {310: t.pnl if kind == "out" else 0.0, 311: t.qty,
            312: t.entry_price if kind == "in" else t.exit_price, 313: -t.commission / 2, 314: 0.0}.get(int(args[1]), 0.0)


@f("HistoryDealGetString")
def _hdgs(api, args, line, nodes, it):
    kind, t = _deal(api, args[0])
    return "" if t is None else {320: api.ad.symbol, 321: t.comment}.get(int(args[1]), "")


@f("ZeroMemory")
def _zero(api, args, line, nodes, it):
    s = args[0]
    if isinstance(s, MStruct) and s._type in STRUCT_DEFAULTS:
        for k, v in STRUCT_DEFAULTS[s._type].items():
            setattr(s, k, v)
    return True


@f("OrderCalcMargin")
def _ocm(api, args, line, nodes, it):
    if len(nodes) > 4:
        it.assign_to(nodes[4], 0.0)
    return True


@f("OrderCalcProfit")
def _ocp(api, args, line, nodes, it):
    order_type, sym, vol, open_p, close_p = args[0], args[1], float(args[2]), float(args[3]), float(args[4])
    side = 1 if int(order_type) in (0, 2, 4) else -1
    v = (close_p - open_p) * side * vol * api.ad.ctx.settings.point_value
    if len(nodes) > 5:
        it.assign_to(nodes[5], v)
    return True


@f("OrderCheck")
def _ocheck(api, args, line, nodes, it):
    if len(args) > 1 and isinstance(args[1], MStruct):
        args[1].retcode = 0
    return True


def _ordersend5(api, req, res, line):
    action = int(req.action)
    typ = int(req.type)
    vol = float(req.volume or 0)
    res.retcode = 10009
    if action == 1:  # DEAL
        if req.position:
            t = api.find_trade(req.position)
            if t is None or not t.is_open:
                res.retcode = 10013
                return False
            api.close_trade(t, vol if vol and vol < t.qty else None, "OrderSend(TRADE_ACTION_DEAL close)")
            res.price = api.bid()
            return True
        side = 1 if typ == 0 else -1
        t = api.market(side, vol, float(req.sl or 0), float(req.tp or 0), str(req.comment or ""), int(req.magic or 0),
                       f"OrderSend({'BUY' if side > 0 else 'SELL'} {vol:g} lots)")
        if t is None:
            res.retcode = 10014
            return False
        res.order = res.deal = t.order_id
        res.price = t.entry_price
        res.volume = t.qty
        return True
    if action == 5:  # PENDING
        o = api.pending(typ, vol, float(req.price), float(req.sl or 0), float(req.tp or 0), str(req.comment or ""),
                        int(req.magic or 0), int(req.expiration or 0))
        res.order = o.id
        res.retcode = 10008
        return True
    if action == 6:  # SLTP
        t = api.find_trade(req.position) if req.position else (api.broker.open[0] if api.broker.open else None)
        if t is None:
            res.retcode = 10013
            return False
        api.broker.modify(t, sl=float(req.sl) or None, tp=float(req.tp) or None, keep_none=False)
        return True
    if action == 7:  # MODIFY pending
        o = api.find_pending(req.order)
        if o is None:
            res.retcode = 10013
            return False
        o.price = float(req.price) or o.price
        o.sl, o.tp = float(req.sl) or None, float(req.tp) or None
        return True
    if action == 8:  # REMOVE
        api.broker.cancel(order_id=int(req.order))
        return True
    res.retcode = 10013
    return False


# ===================================================================================== classes
class CTrade:
    def __init__(self, api: MqlApi):
        self.api = api
        self.magic = 0
        self.ret = 0
        self.res_order = 0
        self.res_price = 0.0
        self.res_volume = 0.0

    def SetExpertMagicNumber(self, m):
        self.magic = int(m)
        return True

    def _done(self, t=None, o=None):
        self.ret = 10009 if (t or o) else 10014
        self.res_order = (t.order_id if t else (o.id if o else 0))
        self.res_price = t.entry_price if t else (o.price if o else 0.0)
        self.res_volume = t.qty if t else 0.0
        return bool(t or o)

    def Buy(self, volume, symbol=None, price=0.0, sl=0.0, tp=0.0, comment=""):
        return self._done(self.api.market(1, float(volume), float(sl or 0), float(tp or 0), comment, self.magic,
                                          f"trade.Buy({float(volume):g})" + (f" — {comment}" if comment else "")))

    def Sell(self, volume, symbol=None, price=0.0, sl=0.0, tp=0.0, comment=""):
        return self._done(self.api.market(-1, float(volume), float(sl or 0), float(tp or 0), comment, self.magic,
                                          f"trade.Sell({float(volume):g})" + (f" — {comment}" if comment else "")))

    def PositionOpen(self, symbol, order_type, volume, price, sl, tp, comment=""):
        return self.Buy(volume, symbol, price, sl, tp, comment) if int(order_type) == 0 else \
            self.Sell(volume, symbol, price, sl, tp, comment)

    def _pending(self, code, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=0, expiration=0, comment=""):
        return self._done(o=self.api.pending(code, float(volume), float(price), float(sl or 0), float(tp or 0), comment,
                                             self.magic, int(expiration or 0)))

    def BuyLimit(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=0, expiration=0, comment=""):
        return self._pending(2, volume, price, symbol, sl, tp, type_time, expiration, comment)

    def SellLimit(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=0, expiration=0, comment=""):
        return self._pending(3, volume, price, symbol, sl, tp, type_time, expiration, comment)

    def BuyStop(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=0, expiration=0, comment=""):
        return self._pending(4, volume, price, symbol, sl, tp, type_time, expiration, comment)

    def SellStop(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=0, expiration=0, comment=""):
        return self._pending(5, volume, price, symbol, sl, tp, type_time, expiration, comment)

    def _targets(self, sym_or_ticket):
        if isinstance(sym_or_ticket, str) or sym_or_ticket is None:
            return [t for t in self.api.broker.open if not self.magic or t.magic == self.magic] or list(self.api.broker.open)
        t = self.api.find_trade(sym_or_ticket)
        return [t] if t is not None and t.is_open else []

    def PositionClose(self, sym_or_ticket, deviation=0):
        ts = self._targets(sym_or_ticket)
        if isinstance(sym_or_ticket, str) and ts:
            ts = ts[:1] if self.api.ad.ctx.settings.hedging else ts
        for t in ts:
            self.api.close_trade(t, None, "trade.PositionClose()")
        self.ret = 10009 if ts else 10013
        return bool(ts)

    def PositionClosePartial(self, ticket, volume, deviation=0):
        ts = self._targets(ticket)
        for t in ts:
            self.api.close_trade(t, float(volume), "trade.PositionClosePartial()")
        return bool(ts)

    def PositionModify(self, sym_or_ticket, sl, tp):
        ts = self._targets(sym_or_ticket)
        for t in ts:
            self.api.broker.modify(t, sl=float(sl) or None, tp=float(tp) or None, keep_none=False)
        self.ret = 10009 if ts else 10013
        return bool(ts)

    def OrderDelete(self, ticket):
        return self.api.broker.cancel(order_id=int(ticket)) > 0

    def OrderModify(self, ticket, price, sl, tp, type_time=0, expiration=0, stoplimit=0):
        o = self.api.find_pending(ticket)
        if o is None:
            return False
        o.price, o.sl, o.tp = float(price) or o.price, float(sl) or None, float(tp) or None
        return True

    def ResultRetcode(self):
        return self.ret

    def ResultOrder(self):
        return self.res_order

    def ResultDeal(self):
        return self.res_order

    def ResultPrice(self):
        return self.res_price

    def ResultVolume(self):
        return self.res_volume

    def ResultRetcodeDescription(self):
        return "done" if self.ret == 10009 else "rejected"

    def ResultComment(self):
        return self.ResultRetcodeDescription()

    def __getattr__(self, name):
        if name.startswith(("Set", "LogLevel")):
            return lambda *a: True
        raise AttributeError(name)


class CPositionInfo:
    def __init__(self, api):
        self.api = api
        self.t = None

    def Select(self, symbol):
        self.t = self.api.broker.open[0] if self.api.broker.open else None
        return self.t is not None

    def SelectByIndex(self, i):
        ts = self.api.broker.open
        self.t = ts[int(i)] if 0 <= int(i) < len(ts) else None
        return self.t is not None

    def SelectByTicket(self, ticket):
        t = self.api.find_trade(ticket)
        self.t = t if t is not None and t.is_open else None
        return self.t is not None

    def SelectByMagic(self, symbol, magic):
        ts = [t for t in self.api.broker.open if t.magic == int(magic)]
        self.t = ts[0] if ts else None
        return self.t is not None

    def PositionType(self):
        return 0 if self.t and self.t.side > 0 else 1

    def PriceOpen(self):
        return self.t.entry_price if self.t else 0.0

    def PriceCurrent(self):
        return self.api.bid()

    def Volume(self):
        return self.t.qty if self.t else 0.0

    def StopLoss(self):
        return (self.t.sl or 0.0) if self.t else 0.0

    def TakeProfit(self):
        return (self.t.tp or 0.0) if self.t else 0.0

    def Profit(self):
        return self.api.profit_of(self.t) if self.t else 0.0

    def Magic(self):
        return self.t.magic if self.t else 0

    def Symbol(self):
        return self.api.ad.symbol

    def Ticket(self):
        return self.t.order_id if self.t else 0

    def Identifier(self):
        return self.Ticket()

    def Time(self):
        return self.t.entry_time // 1000 if self.t else 0

    def Comment(self):
        return self.t.comment if self.t else ""

    def Swap(self):
        return 0.0

    def Commission(self):
        return 0.0


class COrderInfo:
    def __init__(self, api):
        self.api = api
        self.o = None

    def SelectByIndex(self, i):
        ps = self.api.broker.pending
        self.o = ps[int(i)] if 0 <= int(i) < len(ps) else None
        return self.o is not None

    def Select(self, ticket):
        self.o = self.api.find_pending(ticket)
        return self.o is not None

    def OrderType(self):
        o = self.o
        return {("limit", 1): 2, ("limit", -1): 3, ("stop", 1): 4, ("stop", -1): 5}.get((o.kind, o.side), 2) if o else 0

    def PriceOpen(self):
        return self.o.price if self.o else 0.0

    def Magic(self):
        return self.o.magic if self.o else 0

    def Ticket(self):
        return self.o.id if self.o else 0

    def Symbol(self):
        return self.api.ad.symbol

    def VolumeCurrent(self):
        return (self.o.qty or 0.0) if self.o else 0.0


class CDealInfo:
    def __init__(self, api):
        self.api = api


class CSymbolInfo:
    def __init__(self, api):
        self.api = api

    def Name(self, *a):
        return True if a else self.api.ad.symbol

    def RefreshRates(self):
        return True

    def Refresh(self):
        return True

    def Ask(self):
        return self.api.ask()

    def Bid(self):
        return self.api.bid()

    def Last(self):
        return self.api.bid()

    def Point(self):
        return self.api.point()

    def Digits(self):
        return self.api.digits()

    def TickSize(self):
        return self.api.point()

    def TickValue(self):
        return self.api.ad.ctx.settings.point_value * self.api.point()

    def ContractSize(self):
        return self.api.ad.ctx.settings.point_value

    def LotsMin(self):
        return 0.01

    def LotsMax(self):
        return 1000.0

    def LotsStep(self):
        return 0.01

    def Spread(self):
        return round(self.api.ad.ctx.settings.spread / self.api.point()) if self.api.point() else 0

    def StopsLevel(self):
        return 0

    def NormalizePrice(self, p):
        tick = self.api.point()
        return round(round(float(p) / tick) * tick, 10) if tick else float(p)


class CAccountInfo:
    def __init__(self, api):
        self.api = api

    def Balance(self):
        return self.api.broker.cash

    def Equity(self):
        return self.api.broker.equity(self.api.bid())

    def FreeMargin(self):
        return self.Equity()

    def Margin(self):
        return 0.0

    def Profit(self):
        return sum(self.api.profit_of(t) for t in self.api.broker.open)

    def Leverage(self):
        return 100

    def Currency(self):
        return "USD"

    def Login(self):
        return 1
