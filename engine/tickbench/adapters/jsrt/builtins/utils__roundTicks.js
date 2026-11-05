var roundTicks = function (coeff, divisor, contract, variance) {
  var t = contract.providerTickSize || 0.25;
  return Math.round((coeff * variance / divisor) / t) * t;
};
module.exports = { roundTicks: roundTicks };
