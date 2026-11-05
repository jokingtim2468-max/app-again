// Small lodash stand-in covering the functions Tradovate indicators commonly use.
function clone(v) { return Array.isArray(v) ? v.slice() : (v && typeof v === "object" ? Object.assign({}, v) : v); }
function cloneDeep(v) { return v === undefined ? v : JSON.parse(JSON.stringify(v)); }
function toPairs(o) { return Object.keys(o || {}).map(function (k) { return [k, o[k]]; }); }
function isNumber(v) { return typeof v === "number"; }
function isFinite_(v) { return typeof v === "number" && isFinite(v); }
function sum(a) { return (a || []).reduce(function (x, y) { return x + y; }, 0); }
function mean(a) { return a && a.length ? sum(a) / a.length : NaN; }
function max(a) { return a && a.length ? Math.max.apply(null, a) : undefined; }
function min(a) { return a && a.length ? Math.min.apply(null, a) : undefined; }
function last(a) { return a && a.length ? a[a.length - 1] : undefined; }
function first(a) { return a && a.length ? a[0] : undefined; }
function range(s, e, st) { if (e === undefined) { e = s; s = 0; } st = st || 1; var r = []; for (var i = s; st > 0 ? i < e : i > e; i += st) r.push(i); return r; }
function get(o, path, def) { var p = Array.isArray(path) ? path : String(path).split("."); for (var i = 0; i < p.length; i++) { if (o == null) return def; o = o[p[i]]; } return o === undefined ? def : o; }
function times(n, f) { var r = []; for (var i = 0; i < n; i++) r.push(f(i)); return r; }
function isEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function merge(t) { for (var i = 1; i < arguments.length; i++) Object.assign(t, arguments[i]); return t; }
function sumBy(a, f) { return sum((a || []).map(typeof f === "function" ? f : function (x) { return x[f]; })); }
function maxBy(a, f) { var g = typeof f === "function" ? f : function (x) { return x[f]; }; return (a || []).reduce(function (m, x) { return m === undefined || g(x) > g(m) ? x : m; }, undefined); }
function minBy(a, f) { var g = typeof f === "function" ? f : function (x) { return x[f]; }; return (a || []).reduce(function (m, x) { return m === undefined || g(x) < g(m) ? x : m; }, undefined); }
module.exports = { clone: clone, cloneDeep: cloneDeep, toPairs: toPairs, isNumber: isNumber, isFinite: isFinite_, sum: sum, mean: mean,
  max: max, min: min, last: last, first: first, head: first, range: range, get: get, times: times, isEqual: isEqual, merge: merge,
  assign: Object.assign, keys: Object.keys, values: Object.values, sumBy: sumBy, maxBy: maxBy, minBy: minBy,
  isNil: function (v) { return v == null; }, isUndefined: function (v) { return v === undefined; },
  isArray: Array.isArray, isFunction: function (v) { return typeof v === "function"; }, isObject: function (v) { return v !== null && typeof v === "object"; } };
