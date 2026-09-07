# 模块化 Python 量化交易框架

事件驱动、分层设计的 Python 期货量化框架。当前已接入易盛启明星 V10 行情和交易 API，并为快期适配器预留统一接口。

> 期货和期权交易风险很高。请先在模拟环境完成验收。实盘需要期货公司开通 API 权限并提供应用程序号、授权码和服务器地址。

## 项目结构

```text
src/quant_framework/
├── core/       # 统一模型、枚举、事件总线和接口
├── adapters/   # 易盛、Mock、快期底层适配器
├── services/   # K线、分时、交易管理和风控中间件
├── strategy/   # 策略基类和策略引擎
└── runtime/    # 实时运行和历史回放容器
```

易盛行情和交易集中在 `adapters/esunny`。易盛特有的 DLL、合约索引、字符枚举和 `ctypes` 调用不会进入策略层。详细设计见 [架构文档](docs/architecture.md)。

## 快速开始

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python examples\mock_buy_sell.py
.venv\Scripts\python examples\modular_strategy.py
```

## 中间件

- `BarService`：由 Tick 生成一分钟、十分钟等任意秒数周期的 OHLCV K线。
- `TimelineService`：生成逐 Tick 分时价格和当日成交量加权均价。
- `TradingEngine`：统一买卖、开平仓、撤单和委托状态。
- `RiskManager`：单笔量、累计量、活动委托数、价格偏离和合约白名单控制。
- `StrategyEngine`：分发 Tick、K线、分时、委托和成交事件。
- `LiveRuntime/ReplayRuntime`：同一策略可运行于实时环境或历史回放。

## 易盛原生库

```powershell
.\scripts\build_native.ps1
```

构建与 SDK 配置见 [Windows 构建说明](docs/windows-build.md) 和 [易盛 V10 接入说明](docs/esunny-v10.md)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

旧的 `esunny_quant.gateway.*`、`esunny_quant.models` 等导入路径继续兼容；新代码应优先从分层包导入。
