var calculateSma = function (data) { return data.length ? data.reduce(function (a, b) { return a + (b.close !== undefined ? b.close : b.price); }, 0) / data.length : NaN; };
var writeToLog = function (x) { console.log(typeof x === "string" ? x : JSON.stringify(x)); };
var pressEnterToContinue = function () {};
var getSessionSync = function () { return {}; };
var setAccessToken = function () {}, getAccessToken = function () { return {}; }, tokenIsValid = function () { return true; };
module.exports = { calculateSma: calculateSma, writeToLog: writeToLog, pressEnterToContinue: pressEnterToContinue,
  getSessionSync: getSessionSync, setAccessToken: setAccessToken, getAccessToken: getAccessToken, tokenIsValid: tokenIsValid };
