# CTP 接入

项目使用标准 CTP v6.7.13 Windows x64 API，并把官方 C++ 接口封装成两个 C ABI DLL：

- `ctp_md_bridge.dll`：行情登录、订阅、退订和 Tick 推送。
- `ctp_td_bridge.dll`：客户端认证、登录、结算确认、报单、撤单、资金、持仓和合约查询。

策略和中间件只依赖 `MarketDataGateway`、`TradingGateway` 与统一事件模型，因此切换易盛和 CTP 时不需要修改策略。

## 构建

官方 SDK 已整理为：

```text
.sdk/ctp/md_x64/
.sdk/ctp/trader_x64/
```

运行：

```powershell
.\scripts\build_native.ps1
```

输出在 `build/native/`。该目录还会包含 CTP 官方运行库 `thostmduserapi_se.dll` 和 `thosttraderapi_se.dll`。

## SimNow 行情

复制示例配置，凭据只放环境变量，不要写入 TOML 或提交 Git：

```powershell
Copy-Item config\ctp.example.toml config\ctp.toml
$env:CTP_USER_ID="你的SimNow账号"
$env:CTP_PASSWORD="你的SimNow密码"
.\.venv\Scripts\python.exe examples\ctp_quotes.py 'DCE|F|P|2701' --config config\ctp.toml
```

第一套环境第一组的默认地址已经写入示例配置：交易前置
`182.254.243.31:30001`、行情前置 `182.254.243.31:30011`。CTP
行情登录也需要 SimNow 账号密码。SimNow 可能调整前置地址，连接异常时应以
其官网“产品与服务”的环境介绍为准。

## 合约格式

框架统一使用 `交易所|F|品种|交割月份`，例如：

- `DCE|F|P|2701` 对应 CTP `p2701`
- `SHFE|F|RB|2701` 对应 CTP `rb2701`
- `CFFEX|F|IF|2612` 对应 CTP `IF2612`

## 命令行接入

复制配置并通过环境变量提供 SimNow 凭据：

```powershell
Copy-Item config\ctp.example.toml config\ctp.toml
$env:CTP_USER_ID="你的SimNow账号"
$env:CTP_PASSWORD="你的SimNow密码"
quant-framework --gateway ctp --config config\ctp.toml funds
quant-framework --gateway ctp --config config\ctp.toml positions
```

未指定 `--config` 时，CTP 默认读取 `config/ctp.toml`。
## 交易保护

发单和撤单默认锁定。只有配置 `live_trading = true`，并设置下面的明确确认变量后才会调用 CTP 报单接口：

```powershell
$env:CTP_LIVE_CONFIRM="I_UNDERSTAND"
```

这只是程序侧保护，不代替策略风控。首次接入应先在 SimNow 验证登录、合约查询、行情、资金和持仓，再用远离市价的限价单验证报撤单链路。
