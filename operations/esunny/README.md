# 易盛模拟盘一次性操作

此目录放需要人工明确发起、只执行一次的模拟盘操作入口；桥接、配置、K 线与策略等可复用实现仍在 `src/quant_framework/`。所有命令从项目根目录运行。

| 入口 | 用途 | 是否报单 |
| --- | --- | --- |
| `esunny_sim_login_check.py` | 核对模拟账号登录回报 | 否 |
| `collect_p2701_ticks.py` | 把 P2701 Tick 持续写入统一数据库 | 否 |
| `esunny_sim_buy_latest_once.py` | 取新鲜最新成交价，买开 P2701 一手 | 是，最多一次 |
| `esunny_sim_buy_five_minute_pivot.py` | 连续完整 5 分钟底拐点确认后买开 P2701 一手 | 是，最多一次 |

登录检查可临时使用开发包的模拟测试授权值，不会把授权号保存回本机凭据：

```powershell
$env:ESUNNY_LICENSE_NO='Demo_TestCollect'
python operations/esunny/esunny_sim_login_check.py
```

只有明确要在模拟盘报单时才打开一次性报单闸门：

```powershell
$env:ESUNNY_LIVE_CONFIRM='I_UNDERSTAND'
python operations/esunny/esunny_sim_buy_latest_once.py
# 或者：python operations/esunny/esunny_sim_buy_five_minute_pivot.py --execute
```

这两份下单入口仅接受已核对的模拟账号和模拟前置。账号密码从本机配置读取；缺少行情、合约索引、资金或所需信号时不报单，柜台回报不明时不自动重试。`submitted` 不等于成交，应以委托和成交回报确认。

## 保存 P2701 Tick

所有交易日和合约统一写入 `data/market_ticks.sqlite3` 的 `ticks` 表，不按日期拆数据库文件。`contract`、`trading_day` 和交易所时间有组合索引；重复行情会被忽略。夜盘属于下一交易日，所以应明确传入交易日：

```powershell
python operations/esunny/collect_p2701_ticks.py --trading-day 2026-09-16
```

默认累计 500 条 Tick 或经过 60 秒时批量提交，两个条件谁先达到就落库；正常退出还会强制提交剩余数据。采集会一直运行到按下 `Ctrl+C`。测试时可限制时长：

```powershell
python operations/esunny/collect_p2701_ticks.py `
  --trading-day 2026-09-16 --duration-seconds 60
```

查询某日数据：

```sql
SELECT * FROM ticks
WHERE contract = 'DCE|F|P|2701' AND trading_day = '2026-09-16'
ORDER BY exchange_timestamp;
```
