# 网关策略周历裁决库

调用方完成 URL 与类别匹配后，把候选规则集交给本库；库负责时间窗口、
优先级与有效决策区间。所有规则固定使用 `America/New_York` 时区
（`zoneinfo`），无第三方依赖，Python 3.9+。

## 公开接口（`policy.py`）

- `Rule(id, priority, action, weekdays, start, end)`：不可变数据类。
  `priority` 为唯一整数，越小优先级越高；`action` 为 `"ALLOW"` 或
  `"BLOCK"`；`weekdays` 为本地星期编号集合（周一=0 … 周日=6）；
  `start`/`end` 为精确到秒的本地钟表时间（`datetime.time`），且不相等。
- `resolve(rules, at_utc) -> (action, policy_id)`：返回该时刻最高优先级
  有效规则的决策；无有效规则时返回 `("ALLOW", None)`。
- `segments(rules, begin_utc, end_utc) -> list[Segment]`：把
  `[begin_utc, end_utc)` 切分为决策恒定的区间。`Segment` 含
  `begin`/`end`（左闭右开）、`action`、`policy_id`。段恰好覆盖整个
  查询范围一次，无重叠、无空洞、无零长度段；相邻段结果（含
  `policy_id`）必不相同。

输入时刻必须是带时区的 `datetime`（按 UTC 解释）。

## 窗口语义

- 本地窗口左闭右开。`end > start` 属于同一本地日；`end < start` 延续至
  次日，凌晨部分是否有效由开始日的 weekday 决定。
- 裁决定义：对每个真实 UTC 时刻，先按 `America/New_York` 得到本地日期
  与钟表时间，再判断窗口。秋季回拨中重复出现的钟表时间，两次各自独立
  判断；春季跳过的钟表时间不产生有效时刻。

## 运行测试

```sh
python3 -m unittest test_policy -v
```

覆盖 2025-11-02 回拨（01:15–01:45 与 00:30–01:30 窗口）、2025-03-09
跳时（02:10–03:10 与 02:10–02:50 窗口）、优先级遮蔽、跨午夜窗口、
以及分段不变量（覆盖性、合并、与 `resolve` 抽样一致）。
