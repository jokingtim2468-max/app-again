// Tradovate graphics helpers. Tickbench does not render custom graphics; calls return plain descriptors.
var handler = { get: function (t, p) { if (!(p in t)) t[p] = function () { return { op: p, args: Array.prototype.slice.call(arguments) }; }; return t[p]; } };
module.exports = new Proxy({}, handler);
