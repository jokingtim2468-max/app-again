// Driver for Tradovate Code Explorer custom indicators: module.exports = { name, calculator, params, plots, inputType, areaChoice }.
function __tiDef(path) {
  var m = __loadMain(path);
  if (!m || typeof m.calculator !== "function") throw new Error("This doesn't look like a Tradovate indicator: module.exports.calculator is missing.");
  return m;
}

function __tiDescribe(path) {
  var m = __tiDef(path);
  var params = [];
  Object.keys(m.params || {}).forEach(function (k) {
    var p = m.params[k];
    var def = (p && typeof p === "object" && "def" in p) ? p.def : p;
    if (typeof def === "number" || typeof def === "boolean" || typeof def === "string") params.push({ name: k, default: def, type: typeof def });
  });
  var plots = Object.keys(m.plots || {}).filter(function (k) { return !(m.plots[k] && m.plots[k].displayOnly); });
  return JSON.stringify({ name: m.name, description: m.description || m.name, params: params, plots: plots,
    areaChoice: m.areaChoice || "overlay", inputType: m.inputType || "any" });
}

function __tiEntity(i, inputType) {
  var t = new Date(__D.time[i]);
  var e = {
    timestamp: function () { return t; },
    tradeDate: function () { return Number(t.toISOString().slice(0, 10).replace(/-/g, "")); },
    value: function () { return inputType === "volume" ? __D.volume[i] : __D.close[i]; },
    open: function () { return __D.open[i]; }, high: function () { return __D.high[i]; },
    low: function () { return __D.low[i]; }, close: function () { return __D.close[i]; },
    volume: function () { return __D.volume[i]; },
    bidVolume: function () { return __D.volume[i] / 2; }, offerVolume: function () { return __D.volume[i] / 2; },
    profile: function () { return []; }, index: function () { return i; },
  };
  return e;
}

// Runs the calculator over every bar in order. history only ever holds bars up to the current one.
function __tiRun(path, paramsJson, contractJson) {
  var m = __tiDef(path);
  var props = {};
  Object.keys(m.params || {}).forEach(function (k) { var p = m.params[k]; props[k] = (p && typeof p === "object" && "def" in p) ? p.def : p; });
  var over = JSON.parse(paramsJson); Object.keys(over).forEach(function (k) { props[k] = over[k]; });
  var calc = new m.calculator();
  var c = JSON.parse(contractJson);
  calc.props = props;
  calc.contractInfo = { contract: c.contract, product: c.product, tickSize: c.tickSize };
  calc.chartDescription = { elementSize: 1, elementSizeUnit: "UnderlyingUnits", underlyingType: c.daily ? "DailyBar" : "MinuteBar", withHistogram: false };
  if (typeof calc.init === "function") calc.init();
  var inputType = m.inputType || "bars";
  var n = __D.length, fields = {}, items = [], cur = 0;
  var history = {
    data: items,
    get: function (k) { return items[k]; },
    size: function () { return items.length; },
    first: function () { return items[0]; },
    last: function () { return items[items.length - 1]; },
    prior: function () { return items[cur - 1]; },
    back: function (k) { return items[cur - k]; },
  };
  for (var i = 0; i < n; i++) {
    __i = i; cur = i;
    var d = __tiEntity(i, inputType);
    items.push(d);
    var r = calc.map(d, i, history);
    var out;
    if (typeof r === "number") out = { value: r };
    else if (r === undefined || r === null) out = {};
    else out = r;
    if (typeof calc.filter === "function" && !calc.filter(out)) out = {};
    Object.keys(out).forEach(function (k) {
      var v = out[k];
      if (k === "style" || k === "candlestick" || k === "graphics" || k === "candlestickColor") return;
      if (typeof v !== "number" && v !== null && v !== undefined) return;
      if (!fields[k]) { fields[k] = new Array(n); for (var z = 0; z < n; z++) fields[k][z] = null; }
      fields[k][i] = (typeof v === "number" && isFinite(v)) ? v : null;
    });
    // outputs are also readable from history items, as in Tradovate
    Object.keys(out).forEach(function (k) { if (!(k in d)) d[k] = out[k]; });
  }
  var plots = Object.keys(fields).filter(function (k) { return !(m.plots && m.plots[k] && m.plots[k].displayOnly); });
  var displayOnly = Object.keys(fields).filter(function (k) { return m.plots && m.plots[k] && m.plots[k].displayOnly; });
  return JSON.stringify({ name: m.name, fields: fields, plots: plots, displayOnly: displayOnly, areaChoice: m.areaChoice || "overlay",
    titles: Object.keys(m.plots || {}).reduce(function (o, k) { o[k] = (m.plots[k] && m.plots[k].title) || k; return o; }, {}),
    logs: __logs.splice(0) });
}
