// SMA cross as a plain JavaScript strategy for Tickbench.
module.exports = {
  params: { fast: 10, slow: 30 },

  init(ctx) {
    this.fast = ctx.ta.sma(ctx.close, ctx.params.fast);
    this.slow = ctx.ta.sma(ctx.close, ctx.params.slow);
  },

  onBar(ctx) {
    ctx.plot("Fast SMA", this.fast);
    ctx.plot("Slow SMA", this.slow);
    if (ctx.position <= 0 && ctx.crossover(this.fast, this.slow)) {
      ctx.buy({ reason: `SMA${ctx.params.fast} crossed above SMA${ctx.params.slow}` });
    } else if (ctx.position > 0 && ctx.crossunder(this.fast, this.slow)) {
      ctx.exit({ reason: `SMA${ctx.params.fast} crossed below SMA${ctx.params.slow}` });
    }
  },
};
