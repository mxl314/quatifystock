from quant_framework.adapters.mock import MockGateway, MockQuoteGateway
from quant_framework.runtime import LiveRuntime
from quant_framework.strategy import Strategy


class PrintBars(Strategy):
    def on_bar(self, bar) -> None:
        print("K线:", bar)

    def on_timeline(self, point) -> None:
        print("分时:", point)


runtime = LiveRuntime(
    market_factory=lambda sink: MockQuoteGateway(sink),
    trading_factory=lambda sink: MockGateway(sink, auto_fill=True),
    bar_intervals=(60, 600),
)
runtime.add_strategy("print-bars", PrintBars())
runtime.connect()
runtime.subscribe("DCE|F|P|2701")
runtime.market.gateway.push_tick("DCE|F|P|2701", 10000)
runtime.close()
