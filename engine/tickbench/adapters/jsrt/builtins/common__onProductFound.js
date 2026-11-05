var onProductFound = function (ns, prevState, payload) {
  return { state: Object.assign({}, prevState, { product: (payload && payload.data) || prevState.product }), effects: [{ event: ns + "/draw" }] };
};
module.exports = { onProductFound: onProductFound };
