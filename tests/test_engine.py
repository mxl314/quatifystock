import unittest

from quant_framework.core import Offset, OrderRequest, OrderStatus, Side
from quant_framework.services import TradingEngine
from quant_framework.adapters.mock import MockGateway
from quant_framework.services import RiskLimits, RiskManager, RiskRejected


class TradingEngineTests(unittest.TestCase):
    def test_buy_and_sell_are_filled(self):
        engine = TradingEngine(lambda sink: MockGateway(sink, auto_fill=True))
        engine.connect()
        buy = engine.buy("ZCE|F|SR701", 5000, 1)
        sell = engine.sell("ZCE|F|SR701", 5001, 1)
        self.assertEqual(engine.orders[buy].status, OrderStatus.FILLED)
        self.assertEqual(engine.orders[sell].status, OrderStatus.FILLED)
        self.assertEqual(engine.risk.active_orders, 0)

    def test_cancel(self):
        engine = TradingEngine(lambda sink: MockGateway(sink, auto_fill=False))
        engine.connect()
        client_id = engine.buy("ZCE|F|SR701", 5000, 1)
        engine.cancel(client_id)
        self.assertEqual(engine.orders[client_id].status, OrderStatus.CANCELLED)

    def test_risk_rejects_large_order(self):
        risk = RiskManager(RiskLimits(max_order_volume=1))
        engine = TradingEngine(lambda sink: MockGateway(sink), risk=risk)
        engine.connect()
        with self.assertRaises(RiskRejected):
            engine.submit(OrderRequest("ZCE|F|SR701", Side.BUY, Offset.OPEN, 2, 5000))


if __name__ == "__main__":
    unittest.main()

