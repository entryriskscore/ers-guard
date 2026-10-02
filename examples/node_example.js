// node examples/node_example.js   (Node 18+, ERS_API_KEY set)
const { ErsGuard } = require('../js/ers-guard.js');

(async () => {
  const guard = new ErsGuard();
  console.log(await guard.check('ETHUSDT', 'LONG', '60m'));
  console.log('allow LONG ETH:', await guard.allowEntry('ETH/USDT:USDT', 'LONG', { block: ['HIGH'] }));
})();
