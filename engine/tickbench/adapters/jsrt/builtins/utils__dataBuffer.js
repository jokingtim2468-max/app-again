function DataBuffer(transformer, data) {
  transformer = transformer || null;
  this.buffer = (data || []).slice();
  var lastTs;
  var self = this;
  this.push = function (tick) {
    var results = (transformer && typeof transformer === "function") ? transformer(tick) : tick;
    if (!Array.isArray(results)) results = [results];
    results = results.slice().sort(function (a, b) { return new Date(a.timestamp) - new Date(b.timestamp); });
    results.forEach(function (r) {
      var ts = new Date(r.timestamp).getTime();
      if (self.buffer.length === 0 || ts > lastTs) {
        self.buffer.push(r);
        if (self.maxLength && self.buffer.length > self.maxLength) self.buffer.shift();
        lastTs = ts;
      } else if (ts === lastTs) {
        self.buffer[self.buffer.length - 1] = Object.assign({}, r);
      }
    });
  };
  this.setMaxLength = function (m) { self.maxLength = m; };
  this.softPush = function (item) { self.buffer.push(item); };
  this.concat = function (tick) { self.push(tick); return self; };
  this.slicePeriod = function (period) { return period == null ? self.buffer.slice() : self.buffer.slice(self.buffer.length - period); };
  this.getData = function (i) { i = i === undefined ? -1 : i; return i > -1 ? self.buffer[i] : self.buffer; };
  ["forEach", "map", "reduce", "slice", "indexOf", "every", "filter", "some", "find"].forEach(function (m) {
    self[m] = function () { return Array.prototype[m].apply(self.buffer, arguments); };
  });
  this.last = function (i) { i = i || 0; return self.buffer[self.buffer.length - (1 + i)]; };
}
Object.defineProperty(DataBuffer.prototype, "length", { get: function () { return this.buffer.length; } });
var BarsTransformer = function (response) { return (response && response.bars) ? response.bars.slice() : []; };
var TicksTransformer = function (response) {
  var out = [];
  ((response && response.tks) || []).forEach(function (t) { out.push({ timestamp: t.t, price: t.p, volume: t.s, bid: t.b, ask: t.a }); });
  return out;
};
module.exports = { DataBuffer: DataBuffer, BarsTransformer: BarsTransformer, TicksTransformer: TicksTransformer };
