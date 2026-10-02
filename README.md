# task26100323

网关策略周历裁决库。调用方完成 URL 与类别匹配后，把候选规则集交给本库，
由库负责时间窗口、优先级与有效决策区间的计算。所有规则固定使用
`America/New_York` 时区（标准库 `zoneinfo`），无第三方依赖。

## 公开接口

```python
from gateway_policy import Rule, Decision, Segment, resolve, segments
```

- `Rule(id, priority, action, weekdays, start, end)`
  - `id`：唯一策略标识；`priority`：唯一整数，越小优先级越高。
  - `action`：`"ALLOW"` 或 `"BLOCK"`。
  - `weekdays`：周一为 0、周日为 6 的编号集合（`frozenset`）。
  - `start` / `end`：精确到秒的本地钟表时间（`datetime.time`），不相等。
    窗口左闭右开；`end < start` 时跨午夜，凌晨部分是否有效由开始日的
    weekday 决定。
- `resolve(rules, at_utc) -> Decision(action, policy_id)`
  - `at_utc` 必须是带 UTC 时区的 `datetime`。返回该时刻最高优先级有效
    规则的决策；无有效规则时返回 `Decision("ALLOW", None)`。
- `segments(rules, begin_utc, end_utc) -> list[Segment]`
  - 返回 `[begin_utc, end_utc)` 上的有效决策区间
    `Segment(start, end, action, policy_id)`。段恰好覆盖查询范围一次：
    无重叠、无空洞、无零长度段；相邻同结果（含 `policy_id`）已合并；
    被遮蔽的低优先级规则不产生多余分段。空范围返回空列表。

DST 语义：秋季回拨中重复出现的钟表时间每次独立裁决；春季跳过的钟表
时间不产生有效时刻；跨午夜日期关系按本地日历计算。

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖 2025-11-02 回拨（重复窗口两段生效、跨回拨窗口断开再续）、
2025-03-09 跳时（部分跳过窗口仅 07:00-07:10 UTC 生效、完全跳过窗口不
生效）、优先级遮蔽、跨午夜 weekday 归属、秒级精度与输入校验。
