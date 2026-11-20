import io, csv, json, zipfile, hashlib
from app.errors import BusinessError

def _timing_rows(result):
    rows=[]
    # 每条在册记录采用的时间口径与裁决原因
    for r in result.get('records',[]):
        if 'received_at' in r:
            rows.append({'id':r['id'],'subject':r.get('subject',''),'visit':r.get('visit',''),
                         'event_at':r.get('event_at',r.get('at','')),'received_at':r['received_at'],
                         'cutoff_at':r.get('cutoff_at',''),'basis_time':r.get('basis_time',''),
                         'entry_mode':r.get('entry_mode',''),'timing_decision':r.get('timing_decision','纳入'),
                         'code':r.get('code',''),'detail':r.get('detail',''),'line':r.get('_line',0)})
    # 晚到暂缓记录同样留痕，保证原始记录可追溯
    for r in result.get('late_register',[]):
        rows.append({'id':r['id'],'subject':r.get('subject',''),'visit':r.get('visit',''),
                     'event_at':r.get('event_at',r.get('at','')),'received_at':r['received_at'],
                     'cutoff_at':r.get('cutoff_at',''),'basis_time':r.get('basis_time',''),
                     'entry_mode':r.get('entry_mode',''),'timing_decision':'暂缓',
                     'code':r.get('code',''),'detail':r.get('detail',''),'line':r.get('_line',0)})
    return rows

def serialize(result):
    if not result.get('manifest') or not result.get('views'):
        raise BusinessError('INCOMPLETE_RUN','批次尚未完成')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps({**result['manifest'],'revision':result.get('revision',1),'status':result.get('status','待复核')},ensure_ascii=False,indent=2))
        archive.writestr('cutoff_policy.json',json.dumps(result['context']['cutoff'],ensure_ascii=False,indent=2))
        archive.writestr('evidence.json',json.dumps({'counts':result['counts'],'views':result['views'],'quarantine':result['quarantine'],
                                                     'late_register':result.get('late_register',[]),
                                                     'timing_decisions':_timing_rows(result)},ensure_ascii=False,indent=2))
        # 不可变原始输入快照，保证原始记录可追溯
        archive.writestr('input_snapshot.json',json.dumps(result['input_snapshot'],ensure_ascii=False,indent=2))
    return buffer.getvalue()

def serialize_lock(lock):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('lock_certificate.json',json.dumps(lock['certificate'],ensure_ascii=False,indent=2))
        archive.writestr('lock_manifest.json',json.dumps({k:lock[k] for k in ('lock_no','run_id','source','rule_version','cutoff_at','basis_field','snapshot_sha256','seal_sha256','sealed_at')},ensure_ascii=False,indent=2))
    return buffer.getvalue()
