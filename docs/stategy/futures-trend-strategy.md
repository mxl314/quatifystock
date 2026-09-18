# FuturesTrendStrategy 使用文档

`FuturesTrendStrategy` 是框架内置的期货日内趋势策略类。本文只说明代码接入、运行参数和委托行为；策略思想与待回测参数见 [期货日内波段趋势策略 V1](期货日内波段趋势策略_V1.md)，项目分层见 [模块化架构](../architecture.md)。

## 类与入口

- Python 类：`quant_framework.strategy.FuturesTrendStrategy`
- CLI 名称：`futures-trend`
- 实现文件：`src/quant_framework/strategy/futures_trend.py`
- 每个合约创建一个独立实例，趋势、拐点、ATR、委托和持仓状态互不共享。

## 行情输入

CLI 会自动为该策略启用以下完成 K 线：

| 周期 | 用途 |
| --- | --- |
| 180 秒 | 计算 ATR，识别 `L1-H1-L2` 和 `H1-L1-H2` 入场结构 |
| 3600 秒 | 日线数据不足时判断备用趋势 |

策略同时接收 Tick，用于读取开盘价、更新买卖报价、触发入场和结构止损。日线达到预热要求时可以交给 `AdaptiveTrendFilter`；当前内置 CLI 不按自然日合成夜盘日线，避免错误划分交易日。

## 方向与信号

日线未达到 30 根时，策略使用 60 分钟已确认 Swing 高低点：

- 高点和低点同步抬高：多头趋势。
- 高点和低点同步降低：空头趋势。
- 未形成两组已确认高低点：`WAIT`。

趋势还必须与行情开盘价一致：多头趋势且当前价高于开盘价时只做多；空头趋势且当前价低于开盘价时只做空。

3 分钟结构确认后，策略使用 3 分钟 ATR：

- `L2 > L1`，价格达到 `L2 + 0.2 ATR`：触发开多。
- `H2 < H1`，价格达到 `H2 - 0.2 ATR`：触发开空。
- 多单止损为 `L2 - 0.15 ATR`。
- 空单止损为 `H2 + 0.15 ATR`。

趋势、ATR 或结构尚未预热完成时不会发单。

## 委托与仓位

- 开多调用 `TradingEngine.buy`。
- 开空调用 `TradingEngine.sell`。
- 多单止损调用 `close_long_today`。
- 空单止损调用 `close_short_today`。
- 使用 CTP 网关时，统一合约号由适配器转换为 CTP 合约并发送委托。
- 策略只维护本次启动后自身委托形成的仓位，不接管账户原有持仓。
- 同一策略实例只允许一个活动入场委托或一个活动止损委托。
- 部分成交后撤单时，已成交数量仍会保留为实际策略仓位。

## 构造参数

```python
FuturesTrendStrategy(
    contract,
    volume=1,
    execute=False,
    entry_interval_seconds=180,
    atr_period=14,
    entry_atr=0.2,
    stop_atr=0.15,
    min_daily_bars=30,
    min_hourly_bars=6,
)
```

`execute=False` 时只记录信号，不发送委托。CLI 的 `--strategy-volume` 控制每次开仓手数。

## CTP 观察模式

```powershell
.venv\Scripts\python.exe -m quant_framework.cli `
  --gateway ctp `
  --config config/ctp.toml `
  run `
  --contract "DCE|F|P|2701" `
  --strategy futures-trend `
  --strategy-volume 1 `
  --trading-day 2026-09-18
```

该命令连接行情和交易柜台，但策略不会发单。

## CTP 发单模式

发单需要同时设置确认环境变量并增加 `--execute`：

```powershell
$env:CTP_LIVE_CONFIRM="I_UNDERSTAND"

.venv\Scripts\python.exe -m quant_framework.cli `
  --gateway ctp `
  --config config/ctp.toml `
  run `
  --contract "DCE|F|P|2701" `
  --strategy futures-trend `
  --strategy-volume 1 `
  --trading-day 2026-09-18 `
  --execute
```

应先在 SimNow 验证目标合约、交易时段、最小变动价位、平今规则和断线恢复行为，再考虑连接实盘环境。

## 当前边界

- 内置 CLI 尚未加载历史日线；启动后主要使用实时积累的 60 分钟备用趋势。
- CTP 行情的 `open_price` 用作当前开盘价过滤依据，日盘和夜盘的独立 session 切分仍需交易日历支持。
- 尚未实现收盘前强制平仓、止损冷却时间、止盈、加仓和账户已有持仓同步。
- 程序重启后不会自动恢复策略内部的未完成结构和持仓状态。

在补齐上述生产约束前，应保持模拟盘运行。
