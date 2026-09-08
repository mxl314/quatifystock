from quant_framework.core import OrderStatus
from quant_framework.services import TradingEngine
from quant_framework.adapters.mock import MockGateway


engine = TradingEngine(lambda sink: MockGateway(sink, auto_fill=True))
engine.connect()
buy_id = engine.buy("ZCE|F|SR701", price=5000, volume=1)
sell_id = engine.sell("ZCE|F|SR701", price=5001, volume=1)
assert engine.orders[buy_id].status is OrderStatus.FILLED
assert engine.orders[sell_id].status is OrderStatus.FILLED
print("买入:", engine.orders[buy_id])
print("卖出:", engine.orders[sell_id])
engine.close()

