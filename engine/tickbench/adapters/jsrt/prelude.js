// Tickbench JavaScript runtime prelude (runs inside an isolated V8 context, no network/file access).
"use strict";

var __logs = [];
function __fmt(v) {
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch (e) { return String(v); }
}
var console = {
  log: function () { __logs.push(Array.prototype.map.call(arguments, __fmt).join(" ")); },
};
console.info = console.log; console.debug = console.log;
console.warn = function () { __logs.push("[warn] " + Array.prototype.map.call(arguments, __fmt).join(" ")); };
console.error = function () { __logs.push("[error] " + Array.prototype.map.call(arguments, __fmt).join(" ")); };
console.table = console.log;
var process = { env: {}, argv: [], exit: function () {}, on: function () {} };
var setTimeout = function (fn) { return 0; }, clearTimeout = function () {}, setInterval = function () { return 0; }, clearInterval = function () {};

// ------------------------------------------------------------------ CommonJS modules
var __sources = {};   // normalised path -> source
var __builtins = {};  // short name -> source (resolved by basename when a relative path is missing)
var __cache = {};
function __register(path, src) { __sources[path] = src; return true; }
function __registerBuiltin(name, src) { __builtins[name] = src; return true; }

function __normalize(base, req) {
  var parts = (req.charAt(0) === "/" ? [] : base.split("/").slice(0, -1));
  req.split("/").forEach(function (p) {
    if (p === "" || p === ".") return;
    if (p === "..") parts.pop(); else parts.push(p);
  });
  return parts.join("/");
}

// Modules that would open sockets in Tradovate's AutoTrade project are always replaced by Tickbench's versions.
var __forced = { "strategy/strategy": 1 };
function __lookup(from, req) {
  var fseg = req.replace(/\.js$/, "").split("/").filter(function (s) { return s && s !== "." && s !== ".."; }).slice(-2).join("/");
  if (__forced[fseg] && __builtins.hasOwnProperty(fseg)) return { key: "builtin:" + fseg, src: __builtins[fseg] };
  if (req.charAt(0) === "." || req.charAt(0) === "/") {
    var p = __normalize(from, req);
    var tries = [p, p + ".js", p + "/index.js"];
    for (var i = 0; i < tries.length; i++) if (__sources.hasOwnProperty(tries[i])) return { key: tries[i], src: __sources[tries[i]] };
  }
  var base = req.split("/").pop().replace(/\.js$/, "");
  // Built-in shims are keyed by the last one or two path segments, e.g. "tools/SMA", "strategy/tdEvent".
  var segs = req.replace(/\.js$/, "").split("/").filter(function (s) { return s && s !== "." && s !== ".."; });
  var two = segs.slice(-2).join("/");
  if (__builtins.hasOwnProperty(two)) return { key: "builtin:" + two, src: __builtins[two] };
  if (__builtins.hasOwnProperty(base)) return { key: "builtin:" + base, src: __builtins[base] };
  return null;
}

function __makeRequire(from) {
  return function require(req) {
    var found = __lookup(from, req);
    if (!found) throw new Error("Cannot find module '" + req + "' (required from " + from + "). " +
      "Import the whole strategy folder, or remove the dependency.");
    if (__cache.hasOwnProperty(found.key)) return __cache[found.key].exports;
    var module = { exports: {}, id: found.key };
    __cache[found.key] = module;
    var fn = new Function("module", "exports", "require", "__filename", "__dirname", found.src + "\n//# sourceURL=" + found.key);
    fn(module, module.exports, __makeRequire(found.key.replace(/^builtin:/, "builtin/")), found.key, found.key.split("/").slice(0, -1).join("/"));
    return module.exports;
  };
}

function __loadMain(path) {
  var r = __makeRequire(path);
  // load through require so relative requires resolve against the main file
  var module = { exports: {}, id: path };
  __cache[path] = module;
  var fn = new Function("module", "exports", "require", "__filename", "__dirname",
    __sources[path] + "\n;try{if(typeof onBar==='function'&&!module.exports.onBar)module.exports.onBar=onBar}catch(e){}" +
    "\n;try{if(typeof init==='function'&&!module.exports.init)module.exports.init=init}catch(e){}" +
    "\n;try{if(typeof params==='object'&&params&&!module.exports.params)module.exports.params=params}catch(e){}" +
    "\n//# sourceURL=" + path);
  fn(module, module.exports, r, path, "");
  return module.exports;
}

// ------------------------------------------------------------------ market data
var __D = null;   // {time, open, high, low, close, volume} as Float64Arrays
var __i = 0;      // current bar index
function __load(json) {
  var d = JSON.parse(json);
  __D = {};
  ["time", "open", "high", "low", "close", "volume"].forEach(function (k) { __D[k] = Float64Array.from(d[k]); });
  __D.symbol = d.symbol; __D.timeframe = d.timeframe; __D.length = __D.close.length;
  __D.hl2 = __D.close.map(function (_, i) { return (__D.high[i] + __D.low[i]) / 2; });
  __D.hlc3 = __D.close.map(function (_, i) { return (__D.high[i] + __D.low[i] + __D.close[i]) / 3; });
  __D.ohlc4 = __D.close.map(function (_, i) { return (__D.open[i] + __D.high[i] + __D.low[i] + __D.close[i]) / 4; });
  return true;
}

// Series: s[0] / s.get(0) is the current bar, s[1] one bar ago. Future values are unreachable.
function Series(arr, name) { this.a = arr; this.name = name || ""; }
Series.prototype.get = function (k) { k = k || 0; var j = __i - k; return (k >= 0 && j >= 0) ? this.a[j] : NaN; };
Series.prototype.values = function () { return Array.prototype.slice.call(this.a, 0, __i + 1); };
Series.prototype.valueOf = function () { return this.get(0); };
Series.prototype.toString = function () { return String(this.get(0)); };
function __series(arr, name) {
  var s = new Series(arr, name);
  return new Proxy(s, {
    get: function (t, p) {
      if (typeof p === "string" && /^\d+$/.test(p)) return t.get(+p);
      if (p === "length") return __i + 1;
      var v = t[p];
      return typeof v === "function" ? v.bind(t) : v;
    }
  });
}
function __arr(src) {
  if (src === undefined || src === null) return __D.close;
  if (typeof src === "string") { if (!__D[src]) throw new Error("Unknown source '" + src + "'"); return __D[src]; }
  if (src instanceof Series || (src && src.a && src.get)) return src.a;
  return src;
}

// Indicator formulas match the Python engine (TradingView definitions).
var ta = (function () {
  function out(n) { var o = new Float64Array(n); o.fill(NaN); return o; }
  function sma(src, len) {
    var a = __arr(src), n = a.length, o = out(n), s = 0, bad = 0;
    for (var i = 0; i < n; i++) {
      var v = a[i]; if (isNaN(v)) bad++; else s += v;
      if (i >= len) { var w = a[i - len]; if (isNaN(w)) bad--; else s -= w; }
      if (i >= len - 1 && !bad) { var t = 0; for (var k = i - len + 1; k <= i; k++) t += a[k]; o[i] = t / len; }
    }
    return o;
  }
  function emaCore(a, len, alpha) {
    var n = a.length, o = out(n), prev = NaN, seed = 0, cnt = 0;
    for (var i = 0; i < n; i++) {
      var v = a[i];
      if (isNaN(v)) { o[i] = prev; continue; }
      if (isNaN(prev)) { seed += v; cnt++; if (cnt === len) { prev = seed / len; } o[i] = prev; }
      else { prev = alpha * v + (1 - alpha) * prev; o[i] = prev; }
    }
    return o;
  }
  function ema(src, len) { return emaCore(__arr(src), len, 2 / (len + 1)); }
  function rma(src, len) { return emaCore(__arr(src), len, 1 / len); }
  function wma(src, len) {
    var a = __arr(src), n = a.length, o = out(n), den = len * (len + 1) / 2;
    for (var i = len - 1; i < n; i++) { var t = 0; for (var k = 0; k < len; k++) t += a[i - len + 1 + k] * (k + 1); o[i] = t / den; }
    return o;
  }
  function rsi(src, len) {
    var a = __arr(src), n = a.length, up = new Float64Array(Math.max(n - 1, 0)), dn = new Float64Array(Math.max(n - 1, 0));
    for (var i = 1; i < n; i++) { var c = a[i] - a[i - 1]; up[i - 1] = Math.max(c, 0); dn[i - 1] = Math.max(-c, 0); }
    var u = emaCore(up, len, 1 / len), d = emaCore(dn, len, 1 / len), o = out(n);
    for (var j = 1; j < n; j++) { var uu = u[j - 1], dd = d[j - 1]; if (!isNaN(uu) && !isNaN(dd)) o[j] = dd === 0 ? 100 : 100 - 100 / (1 + uu / dd); }
    return o;
  }
  function tr() {
    var n = __D.length, o = new Float64Array(n);
    for (var i = 0; i < n; i++) {
      var h = __D.high[i], l = __D.low[i];
      o[i] = i === 0 ? h - l : Math.max(h - l, Math.abs(h - __D.close[i - 1]), Math.abs(l - __D.close[i - 1]));
    }
    return o;
  }
  function atr(len) { return emaCore(tr(), len, 1 / len); }
  function rolling(src, len, f) {
    var a = __arr(src), n = a.length, o = out(n);
    for (var i = len - 1; i < n; i++) o[i] = f(Array.prototype.slice.call(a, i - len + 1, i + 1));
    return o;
  }
  function highest(src, len) { return rolling(src === undefined ? "high" : src, len, function (w) { return Math.max.apply(null, w); }); }
  function lowest(src, len) { return rolling(src === undefined ? "low" : src, len, function (w) { return Math.min.apply(null, w); }); }
  function stdev(src, len) {
    return rolling(src, len, function (w) { var m = w.reduce(function (x, y) { return x + y; }, 0) / w.length; return Math.sqrt(w.reduce(function (x, y) { return x + (y - m) * (y - m); }, 0) / w.length); });
  }
  function macd(src, fast, slow, signal) {
    fast = fast || 12; slow = slow || 26; signal = signal || 9;
    var f = ema(src, fast), s = ema(src, slow), n = f.length, m = out(n);
    for (var i = 0; i < n; i++) m[i] = f[i] - s[i];
    var sg = emaCore(m, signal, 2 / (signal + 1)), h = out(n);
    for (var j = 0; j < n; j++) h[j] = m[j] - sg[j];
    return { macd: m, signal: sg, hist: h };
  }
  function bb(src, len, mult) {
    mult = mult === undefined ? 2 : mult;
    var m = sma(src, len), d = stdev(src, len), n = m.length, u = out(n), l = out(n);
    for (var i = 0; i < n; i++) { u[i] = m[i] + mult * d[i]; l[i] = m[i] - mult * d[i]; }
    return { basis: m, upper: u, lower: l };
  }
  var wrap = function (f) { return function () { var r = f.apply(null, arguments); return __series(r); }; };
  var wrapObj = function (f) {
    return function () { var r = f.apply(null, arguments), o = {}; Object.keys(r).forEach(function (k) { o[k] = __series(r[k], k); }); return o; };
  };
  return {
    sma: wrap(sma), ema: wrap(ema), rma: wrap(rma), wma: wrap(wma), rsi: wrap(rsi), atr: wrap(atr),
    highest: wrap(highest), lowest: wrap(lowest), stdev: wrap(stdev), macd: wrapObj(macd), bb: wrapObj(bb),
    tr: function () { return __series(tr()); },
    raw: { sma: sma, ema: ema, rma: rma, wma: wma, rsi: rsi, atr: atr, highest: highest, lowest: lowest, stdev: stdev },
  };
})();

function __val(x, k) {
  k = k || 0;
  if (x && typeof x.get === "function") return x.get(k);
  if (Array.isArray(x) || ArrayBuffer.isView(x)) return x[x.length - 1 - k];
  return Number(x);
}
function __crossover(a, b) {
  var a0 = __val(a, 0), a1 = __val(a, 1), b0 = __val(b, 0), b1 = __val(b, 1);
  if ([a0, a1, b0, b1].some(isNaN)) return false;
  return a0 > b0 && a1 <= b1;
}
function __crossunder(a, b) {
  var a0 = __val(a, 0), a1 = __val(a, 1), b0 = __val(b, 0), b1 = __val(b, 1);
  if ([a0, a1, b0, b1].some(isNaN)) return false;
  return a0 < b0 && a1 >= b1;
}
