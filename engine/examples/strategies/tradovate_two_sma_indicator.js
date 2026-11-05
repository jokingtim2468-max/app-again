// Tradovate Code Explorer custom indicator: two simple moving averages.
// Paste into Tradovate's Code Explorer as-is; in Tickbench the default signal rule is
// "fast crosses above slow -> long, crosses below -> exit".
const predef = require("./tools/predef");
const SMA = require("./tools/SMA");

class twoSma {
    init() {
        this.fastSma = SMA(this.props.fastPeriod);
        this.slowSma = SMA(this.props.slowPeriod);
        this.count = 0;
    }

    map(d) {
        this.count++;
        const fast = this.fastSma(d.value());
        const slow = this.slowSma(d.value());
        return {
            fast: this.count >= this.props.fastPeriod ? fast : undefined,
            slow: this.count >= this.props.slowPeriod ? slow : undefined
        };
    }
}

module.exports = {
    name: "twoSmaCross",
    description: "Two SMA Cross",
    calculator: twoSma,
    params: {
        fastPeriod: predef.paramSpecs.period(10),
        slowPeriod: predef.paramSpecs.period(30)
    },
    plots: {
        fast: { title: "Fast SMA" },
        slow: { title: "Slow SMA" }
    },
    tags: ["Tickbench examples"],
    schemeStyles: {
        dark: {
            fast: predef.styles.plot("#F2A93B"),
            slow: predef.styles.plot("#6FA8DC")
        }
    }
};
