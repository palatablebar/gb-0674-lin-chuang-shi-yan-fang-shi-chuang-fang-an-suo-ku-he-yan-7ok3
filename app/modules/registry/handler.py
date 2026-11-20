from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
from app import store, lockstore
router=APIRouter()

def _db():
    from app.main import DB_PATH
    return DB_PATH

@router.get('/registry')
def page(request:Request):
    return render(request,'registry')

@router.post('/api/registry')
def calculate(payload:dict=Body(default={})):
    # 全量运行到锁库登记，返回封存预览（不写库）；正式封存走 /api/locks/seal。
    return evaluate(payload)

@router.post('/api/locks/seal')
def seal(payload:dict=Body(default={})):
    db=_db()
    run_id=payload.get('run_id')
    if run_id:
        result=store.get(db,run_id)
    else:
        result=store.save(db,evaluate({'dataset':payload.get('dataset','clean')}))
    lock,created=lockstore.seal_lock(db,result)
    return {'created':created,'lock':lock}

@router.post('/api/locks/{lock_no}/recompute')
def recompute(lock_no:str,payload:dict=Body(default={})):
    return lockstore.recompute(_db(),lock_no,evaluate,fail=bool(payload.get('inject_failure')))

@router.get('/api/locks')
def locks():
    db=_db()
    return {'locks':lockstore.list_locks(db),'attempts':lockstore.list_attempts(db)}

@router.get('/api/locks/{lock_no}')
def one(lock_no:str):
    return lockstore.get_lock(_db(),lock_no)

@router.get('/api/audit')
def audit():
    db=_db()
    return {'verify':lockstore.verify_audit(db),'entries':lockstore.audit_tail(db)}
