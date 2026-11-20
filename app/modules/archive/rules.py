import hashlib,json

def freeze(state):
    # 封存指纹覆盖选定结果、访视窗、偏离，以及统一截止口径与晚到暂缓清单；
    # 任一截止裁决变化都会改变 seal，保证冻结凭证与锁库共用同一口径且不可被补录覆盖。
    basis={'selected':state['selected_results'],'windows':state['windows'],'deviations':state['deviations'],
           'cutoff':state['context']['cutoff'],
           'late_register':[{'id':r['id'],'code':r['code'],'received_at':r['received_at'],'event_at':r['event_at']} for r in state.get('late_register',[])]}
    return {'status':'可冻结' if state['balance']['status']=='可锁库' else '待处理',
            'seal':hashlib.sha256(json.dumps(basis,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'cutoff_at':state['context']['cutoff']['cutoff_at'],
            'basis_field':state['context']['cutoff']['basis_field'],
            'held_late':len(state.get('late_register',[])),
            'subjects':len(state['context']['subjects']),'results':len(state['selected_results'])}
def apply(state):
    state['archive']=freeze(state);state['views']['archive']={'title':'冻结清单（截止 %s）'%state['context']['cutoff']['cutoff_at'],'rows':state['selected_results'],'metrics':{'受试者':state['archive']['subjects'],'结果':state['archive']['results'],'晚到暂缓':state['archive']['held_late'],'状态':state['archive']['status']}}
