// Context object for plain JavaScript strategies: module.exports = { params, init(ctx), onBar(ctx) }.
var __cmds = [];
var __plots = {};
var __state = { position: 0, positionPrice: NaN, equity: 0, cash: 0, openTrades: 0 };
var __main = null;
var __ctx = null;

function __makeCtx(params) {
  var ctx = {
    params: params,
    state: {},
    ta: ta,
    get i() { return __i; },
    get barIndex() { return __i; },
    get position() { return __state.position; },
    get positionPrice() { return __state.positionPrice; },
    get equity() { return __state.equity; },
    get cash() { return __state.cash; },
    get time() { return __D.time[__i]; },
    symbol: __D.symbol,
    timeframe: __D.timeframe,
    open: __series(__D.open, "open"), high: __series(__D.high, "high"), low: __series(__D.low, "low"),
    close: __series(__D.close, "close"), volume: __series(__D.volume, "volume"),
    hl2: __series(__D.hl2, "hl2"), hlc3: __series(__D.hlc3, "hlc3"), ohlc4: __series(__D.ohlc4, "ohlc4"),
    crossover: __crossover, crossunder: __crossunder,
    buy: function (o) { o = o || {}; __cmds.push({ op: "enter", side: 1, qty: o.qty, sl: o.sl, tp: o.tp, slPct: o.slPct, tpPct: o.tpPct, slPoints: o.slPoints, tpPoints: o.tpPoints, trail: o.trail, tag: o.tag || "long", reason: o.reason || "" }); },
    sell: function (o) { o = o || {}; __cmds.push({ op: "enter", side: -1, qty: o.qty, sl: o.sl, tp: o.tp, slPct: o.slPct, tpPct: o.tpPct, slPoints: o.slPoints, tpPoints: o.tpPoints, trail: o.trail, tag: o.tag || "short", reason: o.reason || "" }); },
    buyLimit: function (price, o) { o = o || {}; __cmds.push({ op: "pending", kind: "limit", side: 1, price: price, qty: o.qty, sl: o.sl, tp: o.tp, tag: o.tag || "", reason: o.reason || "" }); },
    sellLimit: function (price, o) { o = o || {}; __cmds.push({ op: "pending", kind: "limit", side: -1, price: price, qty: o.qty, sl: o.sl, tp: o.tp, tag: o.tag || "", reason: o.reason || "" }); },
    buyStop: function (price, o) { o = o || {}; __cmds.push({ op: "pending", kind: "stop", side: 1, price: price, qty: o.qty, sl: o.sl, tp: o.tp, tag: o.tag || "", reason: o.reason || "" }); },
    sellStop: function (price, o) { o = o || {}; __cmds.push({ op: "pending", kind: "stop", side: -1, price: price, qty: o.qty, sl: o.sl, tp: o.tp, tag: o.tag || "", reason: o.reason || "" }); },
    exit: function (o) { o = o || {}; __cmds.push({ op: "close", tag: o.tag, qty: o.qty, reason: o.reason || "Exit signal" }); },
    cancel: function (tag) { __cmds.push({ op: "cancel", tag: tag }); },
    log: function () { __logs.push(Array.prototype.map.call(arguments, __fmt).join(" ")); },
    plot: function (name, value, opts) { opts = opts || {}; __plots[name] = { v: __val(value), overlay: opts.overlay !== false, color: opts.color || null }; },
  };
  ctx.close_position = ctx.exit; ctx.closePosition = ctx.exit; ctx.short = ctx.sell;
  return ctx;
}

function __initStrategy(path, paramsJson) {
  __main = __loadMain(path);
  if (typeof __main === "function") __main = { onBar: __main };
  var defaults = (__main && __main.params) || {};
  var p = {}; Object.keys(defaults).forEach(function (k) { p[k] = (defaults[k] && typeof defaults[k] === "object" && "def" in defaults[k]) ? defaults[k].def : defaults[k]; });
  var over = JSON.parse(paramsJson); Object.keys(over).forEach(function (k) { p[k] = over[k]; });
  __ctx = __makeCtx(p);
  var onBar = __main.onBar || __main.on_bar || __main.next;
  if (typeof onBar !== "function") throw new Error("No onBar(ctx) found. Export it: module.exports = { onBar(ctx) { ... } }");
  __i = 0;
  if (typeof __main.init === "function") __main.init.call(__main, __ctx);
  return JSON.stringify({ logs: __logs.splice(0) });
}

function __describe(path) {
  var m = __loadMain(path);
  var d = (m && m.params) || {};
  return JSON.stringify(Object.keys(d).map(function (k) {
    var v = (d[k] && typeof d[k] === "object" && "def" in d[k]) ? d[k].def : d[k];
    return { name: k, default: v, type: typeof v };
  }));
}

function __step(i, pos, posPrice, equity, cash) {
  __i = i;
  __state.position = pos; __state.positionPrice = posPrice; __state.equity = equity; __state.cash = cash;
  var onBar = __main.onBar || __main.on_bar || __main.next;
  onBar.call(__main, __ctx);
  var r = JSON.stringify({ cmds: __cmds, logs: __logs, plots: __plots });
  __cmds = []; __logs = []; __plots = {};
  return r;
}
