"""晚到记录截止裁决测试：唯一纳入判据为系统接收时刻。"""
from app.engine import evaluate
from app.modules.cutoff.rules import classify
from app.coerce import instant
import pytest

POLICY = {
    'cutoff_at': '2026-11-20T18:00:00+08:00', 'timezone': 'Asia/Shanghai',
    'basis_field': 'received_at', 'event_field': 'at',
    'rule': 'RECEIPT_AT_OR_BEFORE_CUTOFF', 'decision': '',
}


def _row(at, received, mode='LIVE'):
    return {'id': 'X', 'subject': '00001', 'visit': 'V1', 'at': at,
            'received_at': received, 'entry_mode': mode, 'enrolled': '2026-10-01T00:00:00+08:00'}


def test_late_arrival_after_completed_is_held():
    # 访视截止前已完成（10-08 采样），记录 11-20 19:12 才到 → 暂缓
    v = classify(_row('2026-10-08T08:00:00+08:00', '2026-11-20T19:12:40+08:00'), POLICY)
    assert v['in_scope'] is False
    assert v['code'] == 'LATE_RECEIPT_COMPLETED'
    assert v['basis_time'] == instant('2026-11-20T19:12:40+08:00').isoformat()


def test_backfill_pointing_earlier_is_held():
    # 补录更晚（11-21）却指向更早采样（10-08）→ 暂缓，不能冒充截止前数据
    v = classify(_row('2026-10-08T08:00:00+08:00', '2026-11-21T09:05:00+08:00', 'BACKFILL'), POLICY)
    assert v['in_scope'] is False
    assert v['code'] == 'LATE_BACKFILL_EARLIER'


def test_receipt_at_or_before_cutoff_included_even_if_backfill():
    # 即便补录，只要在截止点前接收，仍纳入；判据是接收时刻而非采样时刻
    v = classify(_row('2026-10-08T08:00:00+08:00', '2026-11-20T17:59:59+08:00', 'BACKFILL'), POLICY)
    assert v['in_scope'] is True
    assert v['code'] == 'ON_TIME_BACKFILL'


def test_cutoff_boundary_is_inclusive():
    v = classify(_row('2026-10-08T08:00:00+08:00', '2026-11-20T18:00:00+08:00'), POLICY)
    assert v['in_scope'] is True and v['code'] == 'ON_TIME_RECEIPT'


def test_event_before_cutoff_but_ignored_for_admission():
    # 采样在截止前不构成纳入理由：接收晚到照样暂缓（防止"按现场时间带进截止后才知的结果"）
    v = classify(_row('2026-11-20T10:00:00+08:00', '2026-11-20T18:30:00+08:00'), POLICY)
    assert v['in_scope'] is False
    assert v['code'] == 'LATE_RECEIPT_COMPLETED'


def test_both_after_cutoff():
    v = classify(_row('2026-11-21T10:00:00+08:00', '2026-11-21T11:00:00+08:00'), POLICY)
    assert v['in_scope'] is False and v['code'] == 'LATE_AFTER_EVENT'


def test_legacy_dataset_without_receipt_column_defaults():
    # 旧批无 received_at：按采样时刻视同在册并显式标注，不静默
    state = evaluate({'dataset': 'clean'})
    assert state['balance']['held_late'] == 0
    assert all(r['code'] == 'LEGACY_RECEIPT_DEFAULT' for r in state['records'])
    assert all('received_at' in r and r['basis_time'] == r['event_at'] for r in state['records'])


def test_late_dataset_two_held_and_blocked():
    state = evaluate({'dataset': 'late'})
    ids = {r['id']: r['code'] for r in state['late_register']}
    assert ids == {'00001-V1': 'LATE_RECEIPT_COMPLETED', '00002-V1': 'LATE_BACKFILL_EARLIER'}
    assert state['balance']['held_late'] == 2
    assert state['balance']['blocked'] >= 2
    assert state['balance']['status'] == '待处理'
    # 晚到记录不在在册集合，但其原始信息仍在 late_register 可追溯
    assert '00001-V1' not in {r['id'] for r in state['records']}
    held = next(r for r in state['late_register'] if r['id'] == '00001-V1')
    assert held['_line'] and held['event_at'] and held['received_at'] and held['detail']


def test_unified_cutoff_shared_across_modules():
    state = evaluate({'dataset': 'late'})
    t = state['context']['cutoff']['cutoff_at']
    assert state['balance']['cutoff_at'] == t
    assert state['archive']['cutoff_at'] == t
    assert state['lock_preview']['cutoff_at'] == t
    assert state['views']['cutoff']['metrics']['截止点'] == t


def test_row_conservation_includes_held():
    state = evaluate({'dataset': 'late'})
    c = state['counts']
    explained = len(state['records']) + len(state['quarantine']) + len(state['late_register']) \
        + c['blank'] + c['duplicate'] + c['repeated_header']
    assert c['input'] == explained
    assert state['balance']['row_balanced'] is True
