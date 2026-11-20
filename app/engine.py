from importlib import import_module
from pathlib import Path
from copy import deepcopy
import json, time, base64
from app.config import ROOT, MODULES, MAX_BYTES, CUTOFF_POLICY, DATASETS
from app.errors import BusinessError
from app.manifest import digest, make_manifest

def evaluate(payload=None, until=None, snapshot=None):
    payload=payload or {}
    until=len(MODULES) if until is None else until
    dataset=payload.get('dataset','dirty')
    if dataset not in DATASETS: raise BusinessError('BAD_DATASET','样例名称无效')
    if not isinstance(payload.get('overrides',{}),dict): raise BusinessError('BAD_CONTEXT','参数须为对象')
    raw=(base64.b64decode(snapshot['bytes_b64'],validate=True) if snapshot is not None else (str(payload['csv_text']).encode() if 'csv_text' in payload else (ROOT/'sample_data'/f'{dataset}.csv').read_bytes()))
    if len(raw)>MAX_BYTES: raise BusinessError('TOO_LARGE','文件超过2MB',413)
    context=deepcopy(snapshot['context']) if snapshot is not None else json.loads((ROOT/'sample_data/context.json').read_text())
    # 统一截止口径随上下文进入每个模块，方案/访视窗/锁库/冻结/登记共用同一对象。
    context['cutoff']=deepcopy(CUTOFF_POLICY)
    context.update(deepcopy(payload.get('overrides',{})))
    context['cutoff']=deepcopy(payload.get('overrides',{}).get('cutoff',context['cutoff']))
    start=time.perf_counter()
    state={'raw_bytes':raw,'context':context,'records':[],'quarantine':[], 'counts':{},'views':{},'source':dataset,
           'late_register':[],'timing_issues':[]}
    for index,key in enumerate(MODULES,1):
        if index>until: break
        import_module(f'app.modules.{key}.rules').apply(state)
    state['input_snapshot']={'bytes_b64':base64.b64encode(raw).decode(),'context':deepcopy(context)}
    state.pop('raw_bytes',None)
    state['manifest']=make_manifest(digest(raw,context),dataset,time.perf_counter()-start)
    if 'lock_preview' in state:
        state['lock_preview']['run_id']=state['manifest']['run_id']
        state['lock_preview']['rule_version']=state['manifest']['rule_version']
    return state
