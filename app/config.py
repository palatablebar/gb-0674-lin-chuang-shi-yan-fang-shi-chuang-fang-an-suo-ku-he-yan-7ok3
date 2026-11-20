from pathlib import Path
import json, os
ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / 'app/project.json').read_text())
MODULES = META['keys']
RULE_VERSION = '2026.11.20-r3'
DB_PATH = os.environ.get('DB_PATH', '/data/workbench.sqlite')
SENTINELS = {'', '-', 'N/A', 'NULL', '未知'}
MAX_BYTES = 2_000_000

# 统一截止口径：方案、访视窗、锁库闸门、冻结凭证、锁库登记共用同一个对象。
# 唯一纳入判据是系统接收时刻 received_at；现场采样时刻 at 只用于访视窗，不决定能否进入锁库。
CUTOFF_POLICY = {
    'cutoff_at': '2026-11-20T18:00:00+08:00',
    'timezone': 'Asia/Shanghai',
    'basis_field': 'received_at',
    'event_field': 'at',
    'rule': 'RECEIPT_AT_OR_BEFORE_CUTOFF',
    'decision': '系统接收时刻不晚于截止点方可进入本次锁库；晚到（含补录指向更早采样）一律暂缓，留痕进入下一版冻结，不覆盖正式结果。',
}
DATASETS = {'dirty', 'clean', 'legacy', 'late'}
