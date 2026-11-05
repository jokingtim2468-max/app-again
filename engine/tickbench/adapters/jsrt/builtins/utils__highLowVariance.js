// highest high minus lowest low over `period` buffered bars
module.exports = function highLowVariance(period) {
  function next(prevState, data) {
    var pts = data.slice(Math.max(0, data.length - period));
    var hi = -Infinity, lo = Infinity;
    pts.forEach(function (b) { hi = Math.max(hi, b.high !== undefined ? b.high : b.price); lo = Math.min(lo, b.low !== undefined ? b.low : b.price); });
    var r = { variance: pts.length ? hi - lo : 0 };
    next.state = r;
    return r;
  }
  next.init = function () { next.state = { variance: 0 }; };
  next.init();
  return next;
};
