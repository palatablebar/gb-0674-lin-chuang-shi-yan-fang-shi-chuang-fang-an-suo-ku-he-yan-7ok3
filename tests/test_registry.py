"""锁库登记测试：正式结果不可覆盖、同批重跑不改换、重算失败保留旧版、仅追加、原始可追溯。"""
import sqlite3
import zipfile, io, json
import pytest
from fastapi.testclient import TestClient
from app import main, store, lockstore
from app.engine import evaluate
from app.errors import BusinessError
from app.archive import serialize, serialize_lock


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / 'lock.sqlite')
    monkeypatch.setattr(main, 'DB_PATH', path)
    return path


@pytest.fixture
def sealed(db):
    result = store.save(db, evaluate({'dataset': 'clean'}))
    lock, created = lockstore.seal_lock(db, result)
    assert created
    return result, lock


def test_seal_creates_formal_lock_with_unified_cutoff(sealed):
    result, lock = sealed
    assert lock['cutoff_at'] == result['context']['cutoff']['cutoff_at']
    assert lock['basis_field'] == 'received_at'
    assert lock['snapshot_sha256'] and lock['seal_sha256']
    assert lock['certificate']['cutoff'] == result['context']['cutoff']


def test_repeat_seal_is_idempotent_no_duplicate(db, sealed):
    result, lock = sealed
    again, created = lockstore.seal_lock(db, result)
    assert created is False
    assert again['lock_no'] == lock['lock_no']
    assert len(lockstore.list_locks(db)) == 1


def test_late_batch_cannot_be_sealed(db):
    late = store.save(db, evaluate({'dataset': 'late'}))
    with pytest.raises(BusinessError) as e:
        lockstore.seal_lock(db, late)
    assert e.value.code == 'LOCK_NOT_READY'
    assert lockstore.list_locks(db) == []


def test_recompute_keeps_formal_result_unchanged(db, sealed):
    result, lock = sealed
    out = lockstore.recompute(db, lock['lock_no'], evaluate)
    assert out['status'] == 'UNCHANGED'
    assert lockstore.get_lock(db, lock['lock_no'])['seal_sha256'] == lock['seal_sha256']


def test_recompute_failure_preserves_old_version(db, sealed):
    result, lock = sealed
    with pytest.raises(BusinessError) as e:
        lockstore.recompute(db, lock['lock_no'], evaluate, fail=True)
    assert e.value.code == 'LOCK_FAILED'
    # 旧版正式结果原样保留
    kept = lockstore.get_lock(db, lock['lock_no'])
    assert kept['seal_sha256'] == lock['seal_sha256']
    attempts = lockstore.list_attempts(db, lock['lock_no'])
    assert any(a['status'] == 'FAILED' for a in attempts)


def test_append_only_blocks_update_and_delete(db, sealed):
    result, lock = sealed
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE formal_locks SET seal_sha256='tampered' WHERE lock_no=?", (lock['lock_no'],))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM formal_locks WHERE lock_no=?", (lock['lock_no'],))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE audit_log SET action='x' WHERE seq=1")
    con.close()
    assert lockstore.get_lock(db, lock['lock_no'])['seal_sha256'] == lock['seal_sha256']


def test_audit_chain_verifies_and_links(db, sealed):
    result, lock = sealed
    lockstore.recompute(db, lock['lock_no'], evaluate)
    report = lockstore.verify_audit(db)
    assert report['ok'] is True and report['entries'] >= 2
    tail = lockstore.audit_tail(db)
    # 哈希链：按 seq 正序每条 prev_hash 指向前一条 entry_hash
    ordered = sorted(tail, key=lambda r: r['seq'])
    for prev, cur in zip(ordered, ordered[1:]):
        assert cur['prev_hash'] == prev['entry_hash']


def test_tampered_audit_detected(db, sealed):
    result, lock = sealed
    # 正式表的 UPDATE 触发器会拒绝应用层改写；这里模拟攻击者拿到库后先 DROP 触发器再物理篡改，
    # 验证哈希链本身（而非仅靠触发器）能够发现内容被改。
    con = sqlite3.connect(db)
    con.execute("DROP TRIGGER audit_log_no_update")
    con.execute("UPDATE audit_log SET detail_json='{}' WHERE seq=1")
    con.commit(); con.close()
    with pytest.raises(BusinessError) as e:
        lockstore.verify_audit(db)
    assert e.value.code == 'AUDIT_BROKEN'


def test_backfill_after_lock_cannot_overwrite(db, sealed):
    # 正式封存后，即使出现新的晚到补录数据，重跑同一不可变快照指纹不变、正式结果不改
    result, lock = sealed
    fresh = evaluate({'dataset': result['source']}, snapshot=result['input_snapshot'])
    assert lockstore.snapshot_fingerprint(fresh) == lock['snapshot_sha256']
    assert lockstore.list_locks(db)[0]['lock_no'] == lock['lock_no']


def test_certificate_bundle_has_traceability(db, sealed):
    result, lock = sealed
    z = zipfile.ZipFile(io.BytesIO(serialize_lock(lock)))
    cert = json.loads(z.read('lock_certificate.json'))
    assert cert['lock_no'] == lock['lock_no']
    assert cert['cutoff']['cutoff_at'] == lock['cutoff_at']
    assert 'selected_results' in cert and 'held_late' in cert
    manifest = json.loads(z.read('lock_manifest.json'))
    assert manifest['snapshot_sha256'] == lock['snapshot_sha256']


def test_run_export_contains_timing_and_snapshot():
    late = evaluate({'dataset': 'late'})
    z = zipfile.ZipFile(io.BytesIO(serialize(late)))
    names = set(z.namelist())
    assert {'cutoff_policy.json', 'input_snapshot.json', 'evidence.json', 'manifest.json'} <= names
    policy = json.loads(z.read('cutoff_policy.json'))
    assert policy['basis_field'] == 'received_at'
    evidence = json.loads(z.read('evidence.json'))
    decisions = {d['id']: d for d in evidence['timing_decisions']}
    assert decisions['00001-V1']['timing_decision'] == '暂缓'
    assert decisions['00001-V1']['code'] == 'LATE_RECEIPT_COMPLETED'
    assert len(evidence['late_register']) == 2
    # 原始输入快照字节可还原
    snap = json.loads(z.read('input_snapshot.json'))
    assert snap['bytes_b64'] == late['input_snapshot']['bytes_b64']


# ---- HTTP 层 ----
def test_api_seal_and_recompute_flow(db):
    c = TestClient(main.app)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    r = c.post('/api/locks/seal', json={'run_id': rid})
    assert r.status_code == 200 and r.json()['created'] is True
    lock_no = r.json()['lock']['lock_no']
    rec = c.post(f'/api/locks/{lock_no}/recompute', json={})
    assert rec.status_code == 200 and rec.json()['status'] == 'UNCHANGED'
    fail = c.post(f'/api/locks/{lock_no}/recompute', json={'inject_failure': True})
    assert fail.status_code == 422 and fail.json()['code'] == 'LOCK_FAILED'
    assert c.get(f'/api/locks/{lock_no}/certificate').status_code == 200
    audit = c.get('/api/audit').json()
    assert audit['verify']['ok'] is True


def test_api_pages_render_for_all_modules(db):
    c = TestClient(main.app)
    run = c.post('/api/runs', json={'dataset': 'late'}).json()
    rid = run['manifest']['run_id']
    for k in main.MODULES:
        resp = c.get(f'/{k}?run_id={rid}')
        assert resp.status_code == 200, resp.text
    cutoff_html = c.get(f'/cutoff?run_id={rid}').text
    assert 'LATE_RECEIPT_COMPLETED' in cutoff_html and '晚到暂缓区' in cutoff_html
    registry_html = c.get(f'/registry?run_id={rid}').text
    assert '锁库登记' in registry_html and 'snapshot' not in registry_html.lower() or '快照指纹' in registry_html
