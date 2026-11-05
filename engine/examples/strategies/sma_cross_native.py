"""SMA cross, Tickbench native Python API.

Long when the fast SMA crosses above the slow SMA, flat when it crosses back below.
"""

PARAMS = {"fast": 10, "slow": 30}


def init(ctx):
    ctx.state["fast"] = ctx.sma("close", ctx.params["fast"])
    ctx.state["slow"] = ctx.sma("close", ctx.params["slow"])


def on_bar(ctx):
    fast, slow = ctx.state["fast"], ctx.state["slow"]
    ctx.plot("Fast SMA", fast)
    ctx.plot("Slow SMA", slow)
    if ctx.position <= 0 and ctx.crossover(fast, slow):
        ctx.buy(reason=f"SMA{ctx.params['fast']} crossed above SMA{ctx.params['slow']}")
    elif ctx.position > 0 and ctx.crossunder(fast, slow):
        ctx.close_position(reason=f"SMA{ctx.params['fast']} crossed below SMA{ctx.params['slow']}")
