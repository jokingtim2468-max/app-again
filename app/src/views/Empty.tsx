export interface Example { name: string; path: string }

const LANG: Record<string, [string, string, string]> = {
  "sma_cross.pine": ["PINE", "SMA cross in Pine Script", "TradingView v5 strategy"],
  "sma_cross.mq5": ["MQ5", "SMA cross Expert Advisor", "MetaTrader 5 with CTrade and CopyBuffer"],
  "sma_cross.mq4": ["MQ4", "SMA cross Expert Advisor", "MetaTrader 4 with OrderSend"],
  "sma_cross_native.py": ["PY", "SMA cross in Python", "Tickbench on_bar(ctx) API"],
  "sma_cross_backtesting.py": ["PY", "backtesting.py strategy", "Runs unchanged, no library needed"],
  "sma_cross_backtrader.py": ["PY", "backtrader strategy", "Runs unchanged, no library needed"],
  "sma_cross.js": ["JS", "SMA cross in JavaScript", "module.exports with onBar(ctx)"],
  "sma_cross_rules.json": ["JSON", "No-code rules", "Indicators and crossing conditions"],
  "tradovate_two_sma_indicator.js": ["TDV", "Tradovate custom indicator", "Code Explorer calculator on ES futures"],
  "tradovate_crossover_strategy.js": ["TDV", "Tradovate API strategy", "AutoTrade style, on ES futures"],
};

export function Empty({ examples, onExample, busy }: { examples: Example[]; onExample: (e: Example) => void; busy: boolean }) {
  const shown = examples.filter((e) => LANG[e.name]);
  return (
    <div className="empty">
      <h2>Test a trading bot on real history before it touches real money</h2>
      <p className="lead">
        Drop a strategy file into the panel on the left and load prices from a CSV, a MetaTrader export or Yahoo Finance.
        Tickbench identifies the language, runs every bar, and shows each trade with the reason it was taken.
      </p>
      {shown.length > 0 && (
        <>
          <p className="hint" style={{ marginBottom: 10 }}>Or start from one of these. Each one is the same moving-average cross written in a different language, so their results line up.</p>
          <div className="examples">
            {shown.map((e) => {
              const [lang, title, sub] = LANG[e.name];
              return (
                <button key={e.name} className="example" disabled={busy} onClick={() => onExample(e)}>
                  <span className="lang">{lang}</span>
                  <b>{title}</b>
                  <small>{sub}</small>
                </button>
              );
            })}
          </div>
        </>
      )}
      <div className="support">
        <div><b>Pine Script v4, v5, v6</b><span>ta.*, strategy.entry, exit and close, inputs, arrays</span></div>
        <div><b>MQL4 and MQL5</b><span>OnTick, iMA, iRSI, CopyBuffer, OrderSend, CTrade</span></div>
        <div><b>Tradovate JavaScript</b><span>Custom indicators and AutoTrade API strategies</span></div>
        <div><b>Python</b><span>on_bar(ctx), backtesting.py and backtrader classes</span></div>
        <div><b>JavaScript</b><span>onBar(ctx) strategies in a sealed V8 sandbox</span></div>
        <div><b>No-code rules</b><span>JSON or YAML conditions, stops and targets</span></div>
      </div>
    </div>
  );
}
