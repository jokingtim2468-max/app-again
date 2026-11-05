// Tradovate API strategy in the AutoTrade style (github.com/tradovate/example-api-trading-strategy).
// Goes long on a positive SMA crossover and flattens on a negative one.
const { Strategy } = require("../strategy/strategy");
const { TdEvent } = require("../strategy/tdEvent");
const { LongShortMode } = require("../common/longShortMode");
const { DataBuffer, BarsTransformer } = require("../../utils/dataBuffer");

class SmaCrossStrategy extends Strategy {
    constructor(params) {
        super(params);
    }

    init(props) {
        return {
            mode: LongShortMode.Watch,
            buffer: new DataBuffer(BarsTransformer),
            prevDistance: NaN,
            position: null,
        };
    }

    next(prevState, [event, payload]) {
        switch (event) {
            case TdEvent.Chart: {
                const { data, props } = payload;
                const { contract, orderQuantity, shortPeriod, longPeriod } = props;
                prevState.buffer.push(data);
                const bars = prevState.buffer.getData();
                const sma = n => bars.length < n ? NaN
                    : bars.slice(bars.length - n).reduce((a, b) => a + b.close, 0) / n;
                const distance = sma(shortPeriod) - sma(longPeriod);
                const crossedUp = distance > 0 && prevState.prevDistance <= 0;
                const crossedDown = distance < 0 && prevState.prevDistance >= 0;
                const state = { ...prevState, prevDistance: distance };

                if (prevState.mode === LongShortMode.Watch && crossedUp) {
                    return {
                        state: { ...state, mode: LongShortMode.Long },
                        effects: [{
                            url: "order/placeOrder",
                            data: { contract, action: "Buy", orderQty: orderQuantity, orderType: "Market" }
                        }]
                    };
                }
                if (prevState.mode === LongShortMode.Long && crossedDown) {
                    return {
                        state: { ...state, mode: LongShortMode.Watch },
                        effects: [{
                            url: "order/placeOrder",
                            data: { contract, action: "Sell", orderQty: orderQuantity, orderType: "Market" }
                        }]
                    };
                }
                return { state };
            }
            case TdEvent.Props: {
                const { entityType, entity } = payload.data;
                if (entityType === "position") {
                    return { state: { ...prevState, position: entity } };
                }
                return { state: prevState };
            }
            default:
                return { state: prevState };
        }
    }

    static params = {
        ...super.params,
        shortPeriod: "int",
        longPeriod: "int",
        orderQuantity: "int",
    };
}

module.exports = { SmaCrossStrategy };
