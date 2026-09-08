import unittest

from quant_framework.core import EventBus
from quant_framework.adapters.mock import MockQuoteGateway
from quant_framework.runtime import QuoteClient


class QuoteClientTests(unittest.TestCase):
    def test_subscribe_and_receive_tick(self):
        bus = EventBus()
        ticks = []
        bus.subscribe("tick", lambda event: ticks.append(event.data))
        client = QuoteClient(lambda sink: MockQuoteGateway(sink), event_bus=bus)
        client.connect()
        client.subscribe("ZCE|F|SR|701")
        client.gateway.push_tick("ZCE|F|SR|701", 5000)
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0].last_price, 5000)
        client.unsubscribe("ZCE|F|SR|701")
        client.gateway.push_tick("ZCE|F|SR|701", 5001)
        self.assertEqual(len(ticks), 1)


if __name__ == "__main__":
    unittest.main()

