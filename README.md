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
└── runtime/    # 实时运行和历史回放容器
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

`quant-framework ... run` 会在一个进程中连接交易和行情网关，等待二者 Ready，启动 Tick 存储、K线和已注册策略，再订阅合约。默认策略只观察信号，不允许发单：

```powershell
quant-framework --gateway v10 --config config/esunny.toml run `
  --quote-config config/quote.toml `
  --contract 'DCE|F|P|2701' `
  --strategy five-minute-pivot `
  --trading-day 2026-09-16
```

CTP 使用同一入口，只需切换网关和配置：

```powershell
quant-framework --gateway ctp --config config/ctp.toml run `
  --contract 'DCE|F|P|2701' `
  --strategy five-minute-pivot `
  --trading-day 2026-09-16
```

自定义策略使用 `Python模块:策略类`，该类必须继承 `Strategy` 且可无参数构造。只有显式增加 `--execute` 并设置对应网关的确认环境变量，策略才可发单。按 `Ctrl+C` 后，运行容器停止行情、排空事件并提交剩余 Tick。

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
