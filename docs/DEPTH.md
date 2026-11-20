# 深度登记 临床试验访视窗与方案锁库核验

规模：中型。使用者：临床试验数据管理员。核心规则：按入组基准计算访视半开窗，方案修订按受试者生效时间选版；漏访不可用复检伪填。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 记录采信 | 执行并复核记录采信 | `POST /api/intake` | `app/modules/intake/rules.py` | `tests/test_intake.py` |
| M2 截止裁决 | 按接收时刻裁决纳入/暂缓 | `POST /api/cutoff` | `app/modules/cutoff/rules.py` | `tests/test_cutoff.py` |
| M3 方案版本 | 执行并复核方案版本 | `POST /api/protocol` | `app/modules/protocol/rules.py` | `tests/test_protocol.py` |
| M4 访视排窗 | 执行并复核访视排窗 | `POST /api/windows` | `app/modules/windows/rules.py` | `tests/test_windows.py` |
| M5 偏离复核 | 执行并复核偏离复核 | `POST /api/deviation` | `app/modules/deviation/rules.py` | `tests/test_deviation.py` |
| M6 复检裁决 | 执行并复核复检裁决 | `POST /api/retest` | `app/modules/retest/rules.py` | `tests/test_retest.py` |
| M7 锁库检查 | 执行并复核锁库检查 | `POST /api/locking` | `app/modules/locking/rules.py` | `tests/test_locking.py` |
| M8 冻结归档 | 执行并复核冻结归档 | `POST /api/archive` | `app/modules/archive/rules.py` | `tests/test_archive.py` |
| M9 锁库登记 | 封存/重跑校验/审计 | `POST /api/registry`、`POST /api/locks/seal` | `app/modules/registry/handler.py`、`app/lockstore.py` | `tests/test_registry.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码检验单位 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_legacy_real` |
| TRAP-02 | BOM表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bom_real` |
| TRAP-08 | 受试者前导零 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_leading_zero_real` |
| TRAP-04 | 分段表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_header_real` |
| TRAP-05 | 缺列记录 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_columns_real` |
| TRAP-18 | 空态 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_empty_types` |
| TRAP-07 | 缺失检验值 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/protocol/rules.py` | `tests/test_protocol.py::test_sentinel_real` |
| TRAP-25 | 个体方案生效重叠 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/protocol/rules.py` | `tests/test_protocol.py::test_overlap_assignment` |
| TRAP-15 | 检验单位换算 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/protocol/rules.py` | `tests/test_protocol.py::test_unit_conversion_real` |
| TRAP-23 | 访视窗末端 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/windows/rules.py` | `tests/test_windows.py::test_half_open_end` |
| TRAP-11 | UTC日历归一 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/windows/rules.py` | `tests/test_windows.py::test_utc_day_equivalence` |
| TRAP-31 | 晚到记录（访视已完成） | 按现场时间纳入带进截止后才知的结果 | 以系统接收时刻为唯一判据，晚到暂缓留痕 | `app/modules/cutoff/rules.py` | `tests/test_cutoff.py::test_late_arrival_after_completed_is_held` |
| TRAP-32 | 补录指向更早采样 | 用旧采样时刻冒充截止前数据 | 接收晚于截止即暂缓，原因码 `LATE_BACKFILL_EARLIER` | `app/modules/cutoff/rules.py` | `tests/test_cutoff.py::test_backfill_pointing_earlier_is_held` |
| TRAP-33 | 各模块截止口径不一致 | 方案/窗/锁库/冻结各取时间 | 同一 `context.cutoff` 对象贯穿全部模块与凭证 | `app/engine.py`、`app/config.py` | `tests/test_cutoff.py::test_unified_cutoff_shared_across_modules` |
| TRAP-34 | 补录覆盖正式锁库 | 截止后数据改写已封存结果 | 仅追加表+触发器+快照指纹，封存后不可改写 | `app/lockstore.py` | `tests/test_registry.py::test_append_only_blocks_update_and_delete` |
| TRAP-35 | 重算失败污染旧版 | 异常时旧正式结果丢失 | 失败只追加留痕，旧版原样保留 | `app/lockstore.py` | `tests/test_registry.py::test_recompute_failure_preserves_old_version` |
| TRAP-36 | 旧批缺接收时刻 | 缺列即整体拒绝或静默假设 | 按采样时刻视同在册并显式标注 `LEGACY_RECEIPT_DEFAULT` | `app/modules/cutoff/rules.py` | `tests/test_cutoff.py::test_legacy_dataset_without_receipt_column_defaults` |

## 对账规则

原始逻辑输入=采纳行+隔离行+晚到暂缓行+空行+重复表头+同值重复。业务计算按 DATA-DICTIONARY.md 分别核验，不能把上级与下级重复加总。所有隔离与晚到暂缓保留编号、原值、原始行号和稳定原因码。

## 已知不覆盖

数据来自仓内样例或用户粘贴文件，不连接外部业务生产系统。平台不执行实际资金划转或行政审批。
