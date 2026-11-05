// Short/long simple moving averages of buffered bars and whether they just crossed.
module.exports = function twoLineCrossover(shortPeriod, longPeriod) {
  function avg(data, n) {
    if (data.length < n) return NaN;
    var s = 0; for (var i = data.length - n; i < data.length; i++) { var b = data[i]; s += (b.close !== undefined ? b.close : b.price); }
    return s / n;
  }
  function next(prevState, data) {
    var shortSma = avg(data, shortPeriod), longSma = avg(data, longPeriod), distance = shortSma - longSma;
    var r = { shortSma: shortSma, longSma: longSma, distance: distance,
      positiveCrossover: distance > 0 && prevState.distance <= 0,
      negativeCrossover: distance < 0 && prevState.distance >= 0 };
    next.state = r;
    return r;
  }
  next.init = function () { next.state = { shortSma: 0, longSma: 0, distance: NaN, positiveCrossover: false, negativeCrossover: false }; };
  next.init();
  return next;
};
