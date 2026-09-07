# 获取易盛 V10 行情

官方模拟行情地址目前为：

- `61.163.243.173:6161`
- `123.161.206.213:6161`

两个地址的 TCP 6161 端口已于 2026-09-07 从当前网络验证可连接。行情 API 不需要测试账号、密码、AppId 或 LicenseNo。

## 构建桥接库

从易盛官网下载 V10 API 包，将交易和行情 SDK 分别解压。例如：

```powershell
cmake -S native -B build/native -A x64 `
  -DESUNNY_TRADE_SDK=D:\sdk\esunny-trade-v10 `
  -DESUNNY_QUOTE_SDK=D:\sdk\esunny-quote-v10
cmake --build build/native --config Release
Copy-Item D:\sdk\esunny-quote-v10\lib\win\x64\libdstarquoteapi.dll build\native\Release\
```

`esunny_v10_quote_bridge.dll` 和官方 `libdstarquoteapi.dll` 必须放在同一目录，并与 Python 同为 x64。

## 配置与运行

```powershell
Copy-Item config\quote.example.toml config\quote.toml
$env:PYTHONPATH='src'
python examples\get_quotes.py 'ZCE|F|SR|701' --count 10
```

合约号不能凭简称猜测。可先调用 `QuoteClient.gateway.query_contracts()`，监听 `quote.contract` 事件获取服务器当前返回的完整合约号，然后再订阅。

正常事件顺序为：

```text
connect -> quote.ready -> subscribe -> tick -> tick ...
```

`tick` 的数据类型是 `MarketTick`，包括最新价、买卖一档、成交量、持仓量、开高低、昨结算和涨跌停价。

