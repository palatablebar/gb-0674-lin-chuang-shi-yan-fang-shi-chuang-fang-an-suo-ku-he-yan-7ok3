"""锁库登记：仅追加（append-only）的正式锁库与审计链。

设计约束（对应需求）：
- 截止后补录不能覆盖正式锁库结果：formal_locks 写入后触发器拒绝 UPDATE/DELETE。
- 同一批重跑不能改换正式结果：recompute 只做校验，比对快照指纹，绝不改写封存行。
- 重算失败保留旧版：失败只追加 lock_attempts，formal_locks 旧行不动。
- 原始记录可追溯：封存完整 input_snapshot、晚到清单与逐记录裁决，证书随包导出。
"""
import sqlite3, json, hashlib
from datetime import datetime, timezone
from pathlib import Path
from app.errors import BusinessError

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS formal_locks(
        lock_no TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        source TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        cutoff_at TEXT NOT NULL,
        basis_field TEXT NOT NULL,
        snapshot_sha256 TEXT NOT NULL,
        seal_sha256 TEXT NOT NULL,
        result_json TEXT NOT NULL,
        sealed_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS lock_attempts(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        lock_no TEXT,
        run_id TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL,
        detail TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        entry_hash TEXT NOT NULL
    )""",
]
# 仅追加：任何改写/删除正式锁库与审计链的尝试都被数据库直接拒绝。
_BLOCK = """CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}
BEGIN SELECT RAISE(ABORT,'{table} is append-only'); END"""
_BLOCK_DEL = """CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}
BEGIN SELECT RAISE(ABORT,'{table} is append-only'); END"""
APPEND_ONLY_TABLES = ('formal_locks', 'audit_log')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    for stmt in SCHEMA:
        con.execute(stmt)
    for table in APPEND_ONLY_TABLES:
        con.execute(_BLOCK.format(table=table))
        con.execute(_BLOCK_DEL.format(table=table))
    return con


def _entry_hash(prev_hash, action, entity, detail_json, recorded_at):
    payload = '|'.join([prev_hash, action, entity, detail_json, recorded_at])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def append_audit(con, action, entity, detail):
    recorded_at = now_iso()
    detail_json = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    prev = con.execute('SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1').fetchone()
    prev_hash = prev['entry_hash'] if prev else hashlib.sha256(b'GENESIS').hexdigest()
    entry_hash = _entry_hash(prev_hash, action, entity, detail_json, recorded_at)
    con.execute('INSERT INTO audit_log(action,entity,detail_json,recorded_at,prev_hash,entry_hash) VALUES(?,?,?,?,?,?)',
                (action, entity, detail_json, recorded_at, prev_hash, entry_hash))
    return entry_hash


def _attempt(con, lock_no, run_id, action, status, detail):
    con.execute('INSERT INTO lock_attempts(lock_no,run_id,action,status,detail,recorded_at) VALUES(?,?,?,?,?,?)',
                (lock_no, run_id, action, status, detail, now_iso()))


def snapshot_fingerprint(result):
    """正式快照指纹：仅由不可变输入快照、规则版本与统一截止口径决定。

    同输入+同规则+同截止点必然得到同一指纹；截止后到达的补录不在 input_snapshot 内，无法改变它。
    """
    material = {
        'input_snapshot': result['input_snapshot'],
        'rule_version': result['manifest']['rule_version'],
        'cutoff': result['context']['cutoff'],
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _certificate(result, lock_no, snapshot_sha, sealed_at):
    return {
        'lock_no': lock_no,
        'run_id': result['manifest']['run_id'],
        'source': result['source'],
        'rule_version': result['manifest']['rule_version'],
        'cutoff': result['context']['cutoff'],
        'snapshot_sha256': snapshot_sha,
        'seal_sha256': result['archive']['seal'],
        'counts': result['balance'],
        'selected_results': result['selected_results'],
        'held_late': [{'id': r['id'], 'subject': r['subject'], 'visit': r['visit'],
                       'code': r['code'], 'detail': r['detail'],
                       'event_at': r['event_at'], 'received_at': r['received_at'],
                       'entry_mode': r['entry_mode'], 'line': r.get('_line', 0)}
                      for r in result.get('late_register', [])],
        'sealed_at': sealed_at,
        'immutability': 'formal_locks 与 audit_log 仅追加；重跑只校验不改写；重算失败保留旧版；补录不覆盖正式结果。',
    }


def seal_lock(path, result):
    if result.get('balance', {}).get('status') != '可锁库':
        raise BusinessError('LOCK_NOT_READY', '存在阻断项或晚到暂缓，不能封存正式锁库')
    run_id = result['manifest']['run_id']
    snapshot_sha = snapshot_fingerprint(result)
    with connect(path) as con:
        existing = con.execute('SELECT * FROM formal_locks WHERE run_id=?', (run_id,)).fetchone()
        if existing:
            # 同批重复封存幂等：不新建、不改写，直接返回已封存的正式结果。
            _attempt(con, existing['lock_no'], run_id, 'SEAL_REPEAT', 'IGNORED', '该批已封存，重复请求被忽略')
            append_audit(con, 'SEAL_REPEAT', existing['lock_no'], {'run_id': run_id})
            return _row_to_lock(existing), False
        sealed_at = now_iso()
        lock_no = 'LOCK-' + snapshot_sha[:12].upper()
        cert = _certificate(result, lock_no, snapshot_sha, sealed_at)
        stored = {'certificate': cert, 'result': result}
        con.execute("""INSERT INTO formal_locks(lock_no,run_id,source,rule_version,cutoff_at,basis_field,
                     snapshot_sha256,seal_sha256,result_json,sealed_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (lock_no, run_id, result['source'], result['manifest']['rule_version'],
                     result['context']['cutoff']['cutoff_at'], result['context']['cutoff']['basis_field'],
                     snapshot_sha, result['archive']['seal'],
                     json.dumps(stored, ensure_ascii=False), sealed_at))
        _attempt(con, lock_no, run_id, 'SEAL', 'OK', '正式锁库封存，仅追加')
        append_audit(con, 'SEAL', lock_no, {'run_id': run_id, 'snapshot_sha256': snapshot_sha,
                                            'cutoff_at': result['context']['cutoff']['cutoff_at']})
        row = con.execute('SELECT * FROM formal_locks WHERE lock_no=?', (lock_no,)).fetchone()
    return _row_to_lock(row), True


def _row_to_lock(row):
    stored = json.loads(row['result_json'])
    return {'lock_no': row['lock_no'], 'run_id': row['run_id'], 'source': row['source'],
            'rule_version': row['rule_version'], 'cutoff_at': row['cutoff_at'],
            'basis_field': row['basis_field'], 'snapshot_sha256': row['snapshot_sha256'],
            'seal_sha256': row['seal_sha256'], 'sealed_at': row['sealed_at'],
            'certificate': stored['certificate']}


def list_locks(path):
    with connect(path) as con:
        rows = con.execute('SELECT lock_no,run_id,source,rule_version,cutoff_at,basis_field,'
                           'snapshot_sha256,seal_sha256,sealed_at FROM formal_locks ORDER BY rowid DESC').fetchall()
    return [dict(r) for r in rows]


def get_lock(path, lock_no):
    with connect(path) as con:
        row = con.execute('SELECT * FROM formal_locks WHERE lock_no=?', (lock_no,)).fetchone()
    if not row:
        raise BusinessError('NOT_FOUND', '正式锁库不存在', 404)
    return _row_to_lock(row)


def get_lock_by_run(path, run_id):
    with connect(path) as con:
        row = con.execute('SELECT * FROM formal_locks WHERE run_id=?', (run_id,)).fetchone()
    return _row_to_lock(row) if row else None


def list_attempts(path, lock_no=None):
    with connect(path) as con:
        if lock_no:
            rows = con.execute('SELECT * FROM lock_attempts WHERE lock_no=? ORDER BY seq', (lock_no,)).fetchall()
        else:
            rows = con.execute('SELECT * FROM lock_attempts ORDER BY seq DESC LIMIT 100').fetchall()
    return [dict(r) for r in rows]


def recompute(path, lock_no, fresh_evaluate, fail=False):
    """同一批重跑：只校验正式结果是否保持，绝不改写封存行。

    - 重新读取封存的不可变输入快照计算；
    - 快照指纹一致 → 正式结果保持（UNCHANGED）；
    - 不一致或计算异常 → 保留旧版，追加失败尝试，返回可复核错误。
    """
    lock = get_lock(path, lock_no)
    if fail:
        # 注入失败：在独立事务中留痕后再抛错，确保失败记录不被外层回滚，旧版正式结果原样保留。
        with connect(path) as con:
            _attempt(con, lock_no, lock['run_id'], 'RECOMPUTE', 'FAILED', '注入失败：重算异常，旧版正式结果保留')
            append_audit(con, 'RECOMPUTE_FAILED', lock_no, {'run_id': lock['run_id']})
        raise BusinessError('LOCK_FAILED', '重算失败：已保留旧版正式锁库，未做任何改写')
    with connect(path) as con:
        try:
            stored = json.loads(con.execute('SELECT result_json FROM formal_locks WHERE lock_no=?',
                                            (lock_no,)).fetchone()['result_json'])
            snapshot = stored['result']['input_snapshot']
            fresh = fresh_evaluate({'dataset': lock['source']}, snapshot=snapshot)
            fresh_sha = snapshot_fingerprint(fresh)
        except BusinessError:
            raise
        except Exception as exc:  # 重算失败：旧版原样保留，失败留痕独立提交
            con.rollback()
            with connect(path) as con2:
                _attempt(con2, lock_no, lock['run_id'], 'RECOMPUTE', 'FAILED', f'重算异常：{exc}；旧版保留')
                append_audit(con2, 'RECOMPUTE_FAILED', lock_no, {'run_id': lock['run_id'], 'error': str(exc)})
            raise BusinessError('LOCK_FAILED', '重算失败：已保留旧版正式锁库，未做任何改写')
        if fresh_sha != lock['snapshot_sha256']:
            _attempt(con, lock_no, lock['run_id'], 'RECOMPUTE', 'MISMATCH',
                     '重算快照指纹与正式结果不一致，拒绝改换正式结果')
            append_audit(con, 'RECOMPUTE_MISMATCH', lock_no,
                         {'run_id': lock['run_id'], 'expected': lock['snapshot_sha256'], 'actual': fresh_sha})
            raise BusinessError('LOCK_MISMATCH', '重算结果与正式快照不一致，已保留旧版正式锁库')
        _attempt(con, lock_no, lock['run_id'], 'RECOMPUTE', 'UNCHANGED',
                 '同输入同规则同截止点重算，正式结果保持不变')
        append_audit(con, 'RECOMPUTE_OK', lock_no, {'run_id': lock['run_id'], 'snapshot_sha256': fresh_sha})
    return {'lock_no': lock_no, 'status': 'UNCHANGED', 'snapshot_sha256': lock['snapshot_sha256'],
            'message': '重算确认：正式锁库结果保持不变'}


def verify_audit(path):
    with connect(path) as con:
        rows = con.execute('SELECT * FROM audit_log ORDER BY seq').fetchall()
    prev = hashlib.sha256(b'GENESIS').hexdigest()
    for row in rows:
        expect = _entry_hash(prev, row['action'], row['entity'], row['detail_json'], row['recorded_at'])
        if row['prev_hash'] != prev or row['entry_hash'] != expect:
            raise BusinessError('AUDIT_BROKEN', f'审计链在第 {row["seq"]} 条断裂', 409)
        prev = row['entry_hash']
    return {'ok': True, 'entries': len(rows), 'head_hash': prev}


def audit_tail(path, limit=100):
    with connect(path) as con:
        rows = con.execute('SELECT seq,action,entity,detail_json,recorded_at,prev_hash,entry_hash '
                           'FROM audit_log ORDER BY seq DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]
