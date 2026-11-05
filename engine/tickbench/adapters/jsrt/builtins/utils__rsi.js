// Simple-average RSI over the last `period` buffered bars.
module.exports = function relativeStrengthIndex(period, overbought, oversold) {
  overbought = overbought || 70; oversold = oversold || 30;
  function next(prevState, data) {
    var pts = data.slice(Math.max(0, data.length - period - 1)), up = 0, dn = 0;
    for (var i = 1; i < pts.length; i++) {
      var a = pts[i].close !== undefined ? pts[i].close : pts[i].price, b = pts[i - 1].close !== undefined ? pts[i - 1].close : pts[i - 1].price;
      var c = a - b; if (c > 0) up += c; else dn -= c;
    }
    var rsi = pts.length > period ? (dn === 0 ? 100 : 100 - 100 / (1 + (up / period) / (dn / period))) : NaN;
    var r = { rsi: rsi, overbought: rsi > overbought, oversold: rsi < oversold };
    next.state = r;
    return r;
  }
  next.init = function () { next.state = { rsi: NaN }; };
  next.init();
  return next;
};
