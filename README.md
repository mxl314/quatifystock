# 易盛 V10 Python 量化交易框架

面向易盛启明星 V10 交易 API 的事件驱动 Python 框架。默认使用可测试的 `mock` 网关；真实交易通过仓库内的 C++ C-ABI 桥接层连接官方 `libdstartradeapi`。

> 期货和期权交易风险很高。请先在易盛/期货公司的模拟环境完成验收。实盘模式需要期货公司开通 API 权限并提供应用程序号、软件授权码和服务器地址。

## 快速开始（模拟成交）

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python examples\mock_buy_sell.py
```

也可直接运行 CLI：

```powershell
esunny-quant --gateway mock buy --contract 'ZCE|F|SR701' --price 5000 --volume 1
esunny-quant --gateway mock sell --contract 'ZCE|F|SR701' --price 5001 --volume 1
```

完整的 SDK 构建、配置和实盘接入步骤见 [docs/esunny-v10.md](docs/esunny-v10.md)。

## 功能

- `TradingEngine.buy/sell/close_long/close_short()`：买卖、开平仓
- `TradingEngine.cancel()`：撤单
- `TradingEngine.query_funds/query_positions()`：资金与持仓查询
- `RiskManager`：单笔量、累计量、活动委托数、价格偏离和合约白名单控制
- `MockGateway`：不连接柜台的确定性测试网关
- `V10NativeGateway`：通过 `ctypes` 调用项目内的 C++ 桥接库
- 双重实盘闸门：`live_trading = true` 与 `ESUNNY_LIVE_CONFIRM=I_UNDERSTAND`

## 测试

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
```

