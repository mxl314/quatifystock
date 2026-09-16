# 易盛启明星 V10 接入说明

## 已核对的官方版本

本框架依据易盛官网在 2026-09-04 提供的开发包接口设计：交易 API 1.0.1.19、行情 API 1.0.0.7。官方包只有 C++ 头文件及 Windows/Linux 动态库，没有 Python binding，所以项目使用 `native/esunny/esunny_v10_bridge.cpp` 将 C++ 虚接口转换成稳定 C ABI，再由 Python `ctypes` 调用。

官方页面：<https://www.esunny.com.cn/market/info/155>

## 1. 申请与测试

1. 从官方页面下载“启明星 V10 API”开发包。
2. 模拟环境可使用包内 `V10测试环境.txt` 的说明注册/使用测试账户。
3. 实盘必须联系开户期货公司，开通该账户的 API 权限，并取得实盘前置地址、应用程序号（AppId）和软件授权码（LicenseNo）。行情 API 本身不校验授权，但交易 API 会校验。
4. 先用官方 C++ Demo/极星客户端核对账号、合约号、合约索引、席位和开平规则。

不要把密码、授权码、官方测试密钥库或官方 DLL 提交到 Git。

## 2. 构建交易桥接库（Windows x64）

将官方包中的交易目录解压到本机，例如 `D:\sdk\esunny-trade-v10`，目录下应有 `include` 和 `lib/win/x64`：

```powershell
cmake -S native -B build/native -A x64 `
  -DESUNNY_TRADE_SDK=D:\sdk\esunny-trade-v10
cmake --build build/native --config Release
Copy-Item D:\sdk\esunny-trade-v10\lib\win\x64\libdstartradeapi.dll build\native\Release\
```

桥接库、官方 DLL、Python 必须同为 x64。Linux 使用同一 CMake 项目，并确保 `libdstartradeapi.so` 位于动态链接器搜索路径。

## 3. 配置

```powershell
Copy-Item config\esunny.example.toml config\esunny.toml
$env:ESUNNY_ACCOUNT='模拟账号'
$env:ESUNNY_PASSWORD='模拟密码'
$env:ESUNNY_APP_ID='应用程序号'
$env:ESUNNY_LICENSE_NO='软件授权码'
```

默认可从环境变量或 Windows DPAPI 本机凭据读取敏感项。仅针对本机模拟账号，也可在被 Git 忽略的 `config/esunny.local.toml` 中放置 `[esunny]` 段的 `password`，这样无需每次设置密码环境变量；这是明文文件，勿复制到实盘配置或提交到仓库。`front_ip/front_port` 必须使用期货公司或开发包提供的环境地址。

## 4. 验证与下单

先保持 `live_trading = false`，验证登录、Ready、资金、持仓：

```powershell
quant-framework --gateway v10 --config config/esunny.toml funds
quant-framework --gateway v10 --config config/esunny.toml positions
```

确认模拟环境后才打开下单闸门：

```powershell
$env:ESUNNY_LIVE_CONFIRM='I_UNDERSTAND'
# 同时把 config/esunny.toml 的 live_trading 改为 true
quant-framework --gateway v10 --config config/esunny.toml buy `
  --contract '交易柜台返回的完整合约号' --contract-index 交易柜台返回的索引 --price 5000 --volume 1
```

`contract_index` 和完整 `contract` 必须使用 V10 初始化合约回调提供的值，不应自行猜测。上期所等交易所还要按柜台规则区分平仓和平今。

## 5. 运行模型和注意事项

- API 的 `OnApiReady` 之前禁止交易；CLI 会等待 Ready，业务程序应监听 `gateway.ready`。
- 回调发生在 SDK 工作线程。Python 层只发布事件，不应在回调里做阻塞操作。
- 官方 API 资金/持仓查询最小间隔为 1 秒；最新请求号查询间隔不小于 5 秒。
- 订单的 `Reference` 默认等于 Python 请求号，用于把异步委托回报映射回本地订单。
- 断线回调只更新状态；重连应由上层在回调之外调度，避免在 SDK 回调中阻塞。
- 当前桥接层覆盖登录、报单、撤单、资金、持仓、委托与成交回报。行情接口可按同样模式独立进程接入，生产环境通常也建议行情与交易进程隔离。

## 6. P2701 模拟盘 5 分钟底拐点一次性买入

Windows 用户可在自己的终端交互式设置本机凭据（密码不会显示在命令行，凭据由当前 Windows 用户的 DPAPI 加密，保存在 `%APPDATA%\quatifystock\esunny-sim.dpapi`，不写入仓库）：

```powershell
python -m quant_framework.adapters.esunny.credentials set --account Q1062383955
```

设置时需要模拟账号密码和易盛交易 API 的 LicenseNo。`config/esunny.toml` 中的 AppId、交易前置、端口也必须与该模拟环境一致。设置完成并确认只连接模拟前置后，使用：

```powershell
$env:ESUNNY_LIVE_CONFIRM='I_UNDERSTAND'
python operations/esunny/esunny_sim_buy_five_minute_pivot.py --execute
```

该脚本监测行情合约 `DCE|F|P|2701`，只使用订阅后生成的 K 线；首根可能不完整，会丢弃。后续每根 5 分钟 K 线至少需在开头和末尾一分钟有 Tick，且三根连续：中间 K 线低点同时低于前后 K 线，后一根收盘价高于中间 K 线高点，才构成买入信号。脚本在信号后复核新鲜行情、交易登录账号、合约索引和资金回报，只提交一次 `P2701` 买开一手限价单。默认最多监测 30 分钟；未出现信号则不下单，委托回报不明时不自动重试。`submitted` 只表示发单请求已发送，不代表成交；须以柜台委托/成交回报核实最终状态。
