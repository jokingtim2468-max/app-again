// Socket-free Strategy base class. Tickbench replays chart events into next() and routes order effects to its broker.
class Strategy {
  constructor(props) { this.props = props; this.mws = this.mws || []; }
  init(props) { return {}; }
  addMiddleware() { this.mws = (this.mws || []).concat(Array.prototype.slice.call(arguments)); }
  next(prevState, action) { return { state: prevState }; }
  catchReplaySessionsDefault(prevState, action) { return null; }
}
Strategy.params = { contract: "object", barType: "string", barInterval: "int", elementSizeUnit: "string",
  histogram: "boolean", timeRangeType: "string", timeRangeValue: "int", dev_mode: "boolean", replay_periods: "object" };
module.exports = { Strategy: Strategy };
