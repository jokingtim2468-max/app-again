// Driver for Tradovate API ("AutoTrade") strategies: class X extends Strategy { init(props); next(state, [event, payload]) }.
// Chart bars are replayed as TdEvent.Chart, fills come back as TdEvent.Props position/cashBalance updates,
// and order effects (startOrderStrategy, placeOrder, placeOCO, liquidatePosition) are executed by Tickbench's broker.
var __tv = { inst: null, state: null, props: null, pendingFx: [], cmds: [], stopped: false, ev: null, entityIds: 1 };

function __tvFindClass(exp) {
  var Base = __makeRequire("main.js")("strategy/strategy").Strategy;
  var cands = [];
  function consider(v) { if (typeof v === "function" && v.prototype && typeof v.prototype.next === "function") cands.push(v); }
  if (typeof exp === "function") consider(exp);
  else if (exp && typeof exp === "object") Object.keys(exp).forEach(function (k) { consider(exp[k]); });
  var sub = cands.filter(function (c) { return c.prototype instanceof Base; });
  return (sub.length ? sub : cands)[0] || null;
}

function __tvParamSpec(path) {
  var Cls = __tvFindClass(__loadMain(path));
  if (!Cls) throw new Error("No Tradovate Strategy class found. Export it: module.exports = { MyStrategy }");
  var own = Cls.params || {};
  var base = { contract: 1, barType: 1, barInterval: 1, elementSizeUnit: 1, histogram: 1, timeRangeType: 1, timeRangeValue: 1, dev_mode: 1, replay_periods: 1 };
  var out = [];
  Object.keys(own).forEach(function (k) { if (!base[k]) out.push({ name: k, type: own[k] }); });
  return JSON.stringify({ name: Cls.name, params: out });
}

function __tvInit(path, propsJson, productJson) {
  __tv.ev = __makeRequire("main.js")("strategy/tdEvent").TdEvent;
  var Cls = __tvFindClass(__loadMain(path));
  if (!Cls) throw new Error("No Tradovate Strategy class found. Export it: module.exports = { MyStrategy }");
  var props = JSON.parse(propsJson);
  var product = JSON.parse(productJson);
  props.dispatcher = { dispatch: function (event, data) { __tvDispatch(event, data || { props: props }); }, state: function () { return __tv.state; }, effects: function () { return []; } };
  __tv.props = props;
  __tv.inst = new Cls(props);
  __tv.state = __tv.inst.init(props) || {};
  __tvDispatch(__tv.ev.UserSync, { data: { users: [{ id: 1, name: "tickbench" }], accounts: [{ id: 1, name: "BACKTEST", active: true }],
    positions: [], products: [product], contracts: [props.contract], cashBalances: [{ realizedPnL: 0, amount: 0 }], orders: [] }, props: props });
  return __tvFlush();
}

function __tvHandleResult(r) {
  if (r === undefined || r === null) return;
  if (typeof r === "object" && Object.prototype.hasOwnProperty.call(r, "state")) {
    __tv.state = r.state;
    (r.effects || []).forEach(__tvEffect);
  } else {
    __tv.state = r;
  }
}

function __tvDispatch(event, payload) {
  if (__tv.stopped) return;
  var r = __tv.inst.next(__tv.state, [event, payload]);
  __tvHandleResult(r);
}

function __num(v, d) { var n = Number(v); return isFinite(n) ? n : d; }

function __tvEffect(fx) {
  if (!fx) return;
  var url = String(fx.url || fx.event || "").replace(/^\//, "");
  var d = fx.data || {};
  var lower = url.toLowerCase();
  if (lower === "orderstrategy/startorderstrategy") {
    var ev = d.entryVersion || {};
    var br = (d.brackets || [])[0] || {};
    if ((d.brackets || []).length > 1) __logs.push("[warn] Only the first bracket of a multi-bracket order strategy is simulated.");
    var qty = __num(ev.orderQty, __num(br.qty, 1));
    __tv.cmds.push({ op: "bracket", side: String(d.action).toLowerCase() === "buy" ? 1 : -1, qty: qty,
      orderType: ev.orderType || "Market", price: ev.price, stopPrice: ev.stopPrice,
      tp: br.profitTarget !== undefined ? Math.abs(__num(br.profitTarget, 0)) : null,
      sl: br.stopLoss !== undefined ? Math.abs(__num(br.stopLoss, 0)) : null,
      trail: !!br.trailingStop, reason: "startOrderStrategy " + d.action });
  } else if (lower === "order/placeorder") {
    __tv.cmds.push({ op: "order", side: String(d.action).toLowerCase() === "buy" ? 1 : -1, qty: __num(d.orderQty, 1),
      orderType: d.orderType || "Market", price: d.price, stopPrice: d.stopPrice, reason: "placeOrder " + d.action + " " + (d.orderType || "Market") });
  } else if (lower === "order/placeoco") {
    var other = d.other || {};
    __tv.cmds.push({ op: "oco", a: { side: String(d.action).toLowerCase() === "buy" ? 1 : -1, qty: __num(d.orderQty, 1), orderType: d.orderType, price: d.price, stopPrice: d.stopPrice },
      b: { side: String(other.action || d.action).toLowerCase() === "buy" ? 1 : -1, qty: __num(other.orderQty || d.orderQty, 1), orderType: other.orderType, price: other.price, stopPrice: other.stopPrice } });
  } else if (lower === "order/liquidateposition" || lower === "order/liquidatepositions") {
    __tv.cmds.push({ op: "flatten", reason: "liquidatePosition" });
  } else if (lower === "order/cancelorder" || lower === "order/cancelallorders") {
    __tv.cmds.push({ op: "cancelAll" });
  } else if (lower === "stop") {
    __tv.stopped = true;
    __logs.push("Strategy dispatched 'stop'; no further events are sent.");
  } else if (lower === "product/find") {
    __tv.pendingFx.push([__tv.ev.ProductFound, { data: __tv.productEntity || {}, props: __tv.props }]);
  } else if (url) {
    // other effects (drawing, logging) are dispatched back once before the next incoming event, as in AutoTrade
    __tv.pendingFx.push([fx.url || fx.event, { data: fx.data, props: __tv.props }]);
  }
}

function __tvRunPendingFx() {
  var fx = __tv.pendingFx.splice(0);
  fx.forEach(function (a) { __tvDispatch(a[0], a[1]); });
}

function __tvFlush() {
  var r = JSON.stringify({ cmds: __tv.cmds, logs: __logs, stopped: __tv.stopped });
  __tv.cmds = []; __logs = [];
  return r;
}

// position: {netPos, netPrice}, realized: number
function __tvProps(posJson, realized) {
  __tvRunPendingFx();
  if (posJson) {
    var p = JSON.parse(posJson);
    __tvDispatch(__tv.ev.Props, { data: { entityType: "position", eventType: "Updated",
      entity: { id: 1, accountId: 1, contractId: __tv.props.contract.id, netPos: p.netPos, netPrice: p.netPrice, timestamp: p.timestamp, bought: p.bought, sold: p.sold } }, props: __tv.props });
  }
  if (realized !== null && realized !== undefined) {
    __tvDispatch(__tv.ev.Props, { data: { entityType: "cashBalance", eventType: "Updated", entity: { id: 1, accountId: 1, realizedPnL: realized, amount: realized } }, props: __tv.props });
  }
}

function __tvBar(i, posJson, realized, changed) {
  __i = i;
  if (changed) __tvProps(posJson, realized); else __tvRunPendingFx();
  var vol = __D.volume[i];
  var bar = { timestamp: new Date(__D.time[i]).toISOString(), open: __D.open[i], high: __D.high[i], low: __D.low[i], close: __D.close[i],
    upVolume: vol / 2, downVolume: vol / 2, upTicks: 0, downTicks: 0, bidVolume: vol / 2, offerVolume: vol / 2 };
  __tvDispatch(__tv.ev.Chart, { data: { id: 1, td: 0, bars: [bar] }, props: __tv.props });
  return __tvFlush();
}
