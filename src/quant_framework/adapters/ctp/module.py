from __future__ import annotations

from ...core.interfaces import AdapterCapabilities, EventSink
from .config import CtpConfig
from .market import CtpMarketGateway
from .trading import CtpTradingGateway


class CtpAdapter:
    capabilities = AdapterCapabilities(
        market_data=True,
        trading=True,
        market_order=True,
        native_condition_order=False,
        historical_data=False,
    )

    def __init__(self, event_sink: EventSink, config: CtpConfig) -> None:
        self.market = CtpMarketGateway(event_sink, config)
        self.trading = CtpTradingGateway(event_sink, config)

    def connect_market(self) -> None:
        self.market.connect()

    def connect_trading(self) -> None:
        self.trading.connect()

    def close(self) -> None:
        self.trading.close()
        self.market.close()
