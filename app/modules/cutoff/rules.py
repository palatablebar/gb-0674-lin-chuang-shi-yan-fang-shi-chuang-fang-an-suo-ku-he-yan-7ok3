from app.coerce import instant
from app.errors import BusinessError

# 截止裁决原因码（稳定、可复核、可测试）
# 纳入侧
ON_TIME_RECEIPT='ON_TIME_RECEIPT'                       # 截止前接收，正常纳入
ON_TIME_BACKFILL='ON_TIME_BACKFILL'                     # 补录但在截止前接收，仍纳入
LEGACY_RECEIPT_DEFAULT='LEGACY_RECEIPT_DEFAULT'         # 旧批无接收时刻，按采样时刻视同在册
# 暂缓侧
LATE_RECEIPT_COMPLETED='LATE_RECEIPT_COMPLETED'         # 访视截止前已完成，记录晚到 → 暂缓
LATE_BACKFILL_EARLIER='LATE_BACKFILL_EARLIER'           # 补录更晚却指向更早采样 → 暂缓
LATE_AFTER_EVENT='LATE_AFTER_EVENT'                     # 采样与接收均在截止后 → 暂缓

REASON_TEXT={
    ON_TIME_RECEIPT:'接收时刻不晚于截止点，纳入本次锁库',
    ON_TIME_BACKFILL:'补录记录在截止前已接收，纳入本次锁库',
    LEGACY_RECEIPT_DEFAULT:'旧批缺接收时刻，按采样时刻视同截止前在册',
    LATE_RECEIPT_COMPLETED:'访视在截止前完成但记录晚到，按接收口径暂缓，留待下一版',
    LATE_BACKFILL_EARLIER:'补录晚于截止且指向更早采样，不能冒充截止前数据，暂缓',
    LATE_AFTER_EVENT:'采样与接收均晚于截止，不属于本次锁库，暂缓',
}

def _timing(row, cutoff):
    event=instant(row['at'])
    mode=(row.get('entry_mode') or 'LIVE').strip().upper() or 'LIVE'
    raw_receipt=(row.get('received_at') or '').strip()
    receipt_defaulted=False
    if raw_receipt:
        receipt=instant(raw_receipt)
    else:
        # 旧编码/历史批没有接收时刻：保守按现场采样时刻视同在册，并显式标注，不静默处理。
        receipt=event;receipt_defaulted=True
    return event,receipt,mode,receipt_defaulted

def classify(row, policy):
    cutoff=instant(policy['cutoff_at'])
    event,receipt,mode,defaulted=_timing(row,cutoff)
    common={'cutoff_at':policy['cutoff_at'],'event_at':event.isoformat(),
            'received_at':receipt.isoformat(),'entry_mode':mode,
            'basis_time':receipt.isoformat(),'basis_field':policy['basis_field']}
    if receipt<=cutoff:
        if defaulted:
            code=LEGACY_RECEIPT_DEFAULT
        elif mode=='BACKFILL':
            code=ON_TIME_BACKFILL
        else:
            code=ON_TIME_RECEIPT
        return {'in_scope':True,'code':code,'detail':REASON_TEXT[code],**common}
    # 接收时刻晚于截止：一律暂缓，无论采样发生在何时。
    if mode=='BACKFILL' and event<=cutoff:
        code=LATE_BACKFILL_EARLIER
    elif event<=cutoff:
        code=LATE_RECEIPT_COMPLETED
    else:
        code=LATE_AFTER_EVENT
    return {'in_scope':False,'code':code,'detail':REASON_TEXT[code],**common}

def apply(state):
    policy=state['context'].get('cutoff')
    if not policy or 'cutoff_at' not in policy:
        raise BusinessError('CUTOFF_POLICY_MISSING','缺少统一截止口径，无法裁决')
    in_scope=[];held=[]
    for row in state['records']:
        verdict=classify(row,policy)
        enriched={**row,**{k:v for k,v in verdict.items() if k!='in_scope'},
                  'timing_decision':'纳入' if verdict['in_scope'] else '暂缓'}
        if verdict['in_scope']:
            in_scope.append(enriched)
        else:
            held.append(enriched)
    state['records']=in_scope
    state['late_register']=held
    state['timing_issues']=[{'id':r['id'],'code':r['code'],'detail':r['detail'],
                             'line':r.get('_line',0)} for r in held]
    state['views']['cutoff']={
        'title':'截止裁决（统一口径：%s）'%policy['cutoff_at'],
        'rows':[{'id':r['id'],'subject':r['subject'],'visit':r['visit'],'entry_mode':r['entry_mode'],
                 'event_at':r['event_at'],'received_at':r['received_at'],'cutoff_at':r['cutoff_at'],
                 'basis_time':r['basis_time'],'timing_decision':r['timing_decision'],
                 'code':r['code'],'detail':r['detail'],'line':r.get('_line',0)} for r in in_scope],
        'late_rows':[{'id':r['id'],'subject':r['subject'],'visit':r['visit'],'entry_mode':r['entry_mode'],
                      'event_at':r['event_at'],'received_at':r['received_at'],'cutoff_at':r['cutoff_at'],
                      'basis_time':r['basis_time'],'timing_decision':r['timing_decision'],
                      'code':r['code'],'detail':r['detail'],'line':r.get('_line',0)} for r in held],
        'metrics':{'在册记录':len(in_scope),'晚到暂缓':len(held),
                   '截止点':policy['cutoff_at'],'纳入判据':'系统接收时刻 received_at ≤ 截止点'},
    }
