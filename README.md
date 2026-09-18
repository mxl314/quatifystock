# 模块化 Python 量化交易框架

事件驱动、分层设计的 Python 期货量化框架。当前接入易盛启明星 V10 和标准 CTP 行情、交易 API。

> 期货和期权交易风险很高。请先在模拟环境完成验收。实盘需要期货公司开通 API 权限并提供应用程序号、授权码和服务器地址。

## 项目结构

```text
src/quant_framework/
├── core/       # 统一模型、枚举、事件总线和接口
├── adapters/   # 易盛、CTP 和 Mock 底层适配器
├── services/   # K线、分时、交易管理和风控中间件
├── storage/    # Tick 等行情数据的持久化
├── strategy/   # 策略基类和策略引擎
├── runtime/    # 实时运行和历史回放容器
└── visualization/ # 盘中K线网页和盘后HTML报告
```

易盛和 CTP 分别集中在 `adapters/esunny`、`adapters/ctp`。柜台特有的 DLL、合约标识和 `ctypes` 调用不会进入策略层。详细设计见 [架构文档](docs/architecture.md)。

模拟盘的登录和一次性下单入口放在 [operations/esunny](operations/esunny/README.md)；`scripts` 保留编译等维护脚本，复用逻辑仍在 `src/quant_framework`。

## 快速开始

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python examples\mock_buy_sell.py
.venv\Scripts\python examples\modular_strategy.py
```

## 统一运行入口

`quant-framework ... run` 会在一个进程中连接交易和行情网关，等待二者 Ready，启动 Tick 存储、K线和已注册策略，再订阅合约。Tick 存储使用有界非阻塞队列，SQLite 组装与提交在独立线程执行；队列默认容量为50000。默认策略只观察信号，不允许发单：

```powershell
quant-framework --gateway v10 --config config/esunny.toml run `
  --quote-config config/quote.toml `
  --contract 'DCE|F|P|2701' `
  --strategy five-minute-pivot `
  --trading-day 2026-09-16
```

内置拐点策略支持任意正整数秒周期，格式为 `pivot:周期秒数`。例如一分钟使用 `--strategy pivot:60`，五分钟使用 `--strategy pivot:300`；旧名称 `five-minute-pivot` 等价于 `pivot:300`。策略所需K线周期会自动加入运行时，不必额外指定 `--bar-interval`。图表需要显示一分钟K线时，可增加 `--bar-interval 60`。底部拐点确认后产生买入信号，顶部拐点确认后产生卖出开仓信号；未指定 `--execute` 时只检测和展示信号。

期货趋势策略使用 `--strategy futures-trend`；完整参数、信号、CTP 委托和运行限制见 [FuturesTrendStrategy 使用文档](docs/stategy/futures-trend-strategy.md)。

CTP 使用同一入口，只需切换网关和配置：

```powershell
quant-framework --gateway ctp --config config/ctp.toml run `
  --contract 'DCE|F|P|2701' `
  --strategy futures-trend `
  --trading-day 2026-09-16
```

以上命令默认只观察信号。发单安全锁和操作示例见独立的策略类文档。

自定义策略使用 `Python模块:策略类`，该类必须继承 `Strategy` 且可无参数构造。只有显式增加 `--execute` 并设置对应网关的确认环境变量，策略才可发单。按 `Ctrl+C` 后，运行容器停止行情、排空事件并提交剩余 Tick。

同一连接可重复指定 `--contract` 订阅多个合约。内置 `five-minute-pivot` 会为每个订阅合约自动创建一个彼此独立的策略实例；每个实例分别维护K线序列、最新报价和订单状态：

```powershell
quant-framework --gateway v10 --config config/esunny.toml run `
  --quote-config config/quote.toml `
  --contract 'DCE|F|P|2701' `
  --contract 'DCE|F|M|2701' `
  --contract 'DCE|F|Y|2701' `
  --strategy five-minute-pivot `
  --trading-day 2026-09-16
```

运行心跳包含 `storage_queue_size`、`storage_persisted_rows`、`storage_dropped_events` 和 `storage_failed_events`。正常运行时后两项应始终为零；存储速度落后时只增长队列，不阻塞策略事件线程。

真实委托与成交也通过独立非阻塞队列写入同一个数据库：`orders` 保存委托最新状态，`order_events` 保存完整状态变化，`trades` 保存真实成交明细。盘后K线会自动从 `trades` 读取买卖位置。订单存储心跳字段为 `order_queue_size`、`orders_persisted`、`trades_persisted`、`order_storage_dropped_events` 和 `order_storage_failed_events`。

```sql
SELECT * FROM orders ORDER BY updated_at DESC;
SELECT * FROM order_events ORDER BY id DESC;
SELECT * FROM trades ORDER BY trade_time DESC;
```

## K线图表

统一运行程序可直接启动内存实时图表。EventBus 只将行情事件无阻塞放入有界图表队列，独立工作线程负责K线聚合和快照维护，不在策略事件线程执行聚合、数据库查询或HTML生成：

```powershell
quant-framework --gateway v10 --config config/esunny.toml run `
  --quote-config config/quote.toml `
  --contract 'DCE|F|P|2701' `
  --strategy five-minute-pivot `
  --trading-day 2026-09-16 `
  --chart-port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。也可以单独启动读取已落库 Tick 的网页；这种方式最多滞后一个落盘周期：

```powershell
quant-framework chart-live --database data/market_ticks.sqlite3 `
  --contract 'DCE|F|P|2701' --trading-day 2026-09-16 --interval 300
```

盘后生成不依赖服务的独立HTML报告：

```powershell
quant-framework chart-report --database data/market_ticks.sqlite3 `
  --contract 'DCE|F|P|2701' --trading-day 2026-09-16 --interval 300 `
  --output reports/P2701_2026-09-16_5m.html
```

页面支持滚轮缩放、拖动平移、OHLCV悬停信息和成交标记。如果数据库存在包含 `contract`、`trading_day`、`trade_time`、`side`、`price` 字段的 `trades` 表，报告会自动加载买卖位置；`offset`、`volume` 和 `label` 字段可选。

## 中间件

- `BarService`：由 Tick 生成一分钟、十分钟等任意秒数周期的 OHLCV K线。
- `TimelineService`：生成逐 Tick 分时价格和当日成交量加权均价。
- `TradingEngine`：统一买卖、开平仓、撤单和委托状态。
- `RiskManager`：单笔量、累计量、活动委托数、价格偏离和合约白名单控制。
- `StrategyEngine`：分发 Tick、K线、分时、委托和成交事件。
- `LiveRuntime/ReplayRuntime`：同一策略可运行于实时环境或历史回放。

## 原生接口库

```powershell
.\scripts\build_native.ps1
```

构建与 SDK 配置见 [Windows 构建说明](docs/windows-build.md)、[易盛 V10 接入说明](docs/esunny-v10.md) 和 [CTP 接入说明](docs/ctp.md)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

统一包名为 `quant_framework`，新功能应从 `core`、`adapters`、`services`、`strategy` 和 `runtime` 分层导入。
