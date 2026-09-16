# 模块化架构

项目按依赖方向分为五个区域：

```text
strategy  ->  services  ->  core  <-  adapters
                 ^                    易盛 / CTP / Mock
                 |
              runtime
```

## core

`quant_framework.core` 只包含统一枚举、数据模型、事件总线和底层接口，不依赖任何柜台 SDK。策略和中间件只能使用这里定义的 `Tick`、`Bar`、`OrderRequest` 等对象。

## adapters

- `adapters.esunny`：易盛 V10 行情、交易、配置和组合模块。
- `adapters.ctp`：标准 CTP 行情、交易、配置和组合模块。
- `adapters.mock`：测试与回放使用的行情、交易实现。

易盛和 CTP 特有的合约编号、字符枚举、DLL 和 `ctypes` 调用不能泄漏到策略层。

## services

- `TradingEngine`：委托生命周期和统一买卖接口。
- `RiskManager`：下单前风控。
- `BarService`：Tick 合成任意秒数周期的 OHLCV K线。
- `TimelineService`：生成分时价和当日成交量加权均价。

## strategy

策略继承 `Strategy`，通过 `on_tick`、`on_bar`、`on_timeline`、`on_order` 和 `on_trade` 接收数据。策略通过 `buy`、`sell`、`close_long`、`close_short` 交易，不直接调用底层适配器。

## runtime

- `LiveRuntime`：组装实时行情、交易、中间件和策略。
- `ReplayRuntime`：将历史 Tick 注入同一套中间件和策略。

项目统一使用 `quant_framework.*` 导入路径；柜台实现分别位于 `adapters.esunny` 和 `adapters.ctp`。

## K线周期

`BarService` 接受秒数周期，例如：

```python
BarService(event_bus, intervals=(60, 600, 3600))
```

分别产生一分钟、十分钟和一小时 K线。当前版本按行情时间的自然时间边界切分；接入生产交易前应继续增加各交易所夜盘、休市和交易日历规则。
