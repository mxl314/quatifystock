from __future__ import annotations

from ...core.interfaces import AdapterCapabilities, EventSink
from .config import V10Config
from .market import V10QuoteGateway
from .quote_config import QuoteConfig
from .trading import V10NativeGateway


class EsunnyAdapter:
    """易盛行情和交易的统一底层模块。"""

    capabilities = AdapterCapabilities(
        market_data=True,
        trading=True,
        market_order=True,
        native_condition_order=False,
        historical_data=False,
    )

    def __init__(
        self,
        event_sink: EventSink,
        quote_config: QuoteConfig,
        trading_config: V10Config | None = None,
    ) -> None:
        self.market = V10QuoteGateway(event_sink, quote_config)
        self.trading = V10NativeGateway(event_sink, trading_config) if trading_config else None

    def connect_market(self) -> None:
        self.market.connect()

    def connect_trading(self) -> None:
        if self.trading is None:
            raise RuntimeError("未配置易盛交易模块")
        self.trading.connect()

    def close(self) -> None:
        if self.trading is not None:
            self.trading.close()
        self.market.close()
