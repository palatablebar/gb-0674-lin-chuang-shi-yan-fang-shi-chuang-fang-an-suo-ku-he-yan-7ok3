def decide(state):
    c=state['counts'];explained=len(state['records'])+len(state['quarantine'])+len(state.get('late_register',[]))+c['blank']+c['duplicate']+c['repeated_header']
    held=len(state.get('late_register',[]))
    blocked=len(state['deviations'])+len(state['retest_issues'])+len(state['quarantine'])+held
    return {'input':c['input'],'accepted':len(state['records']),'quarantined':len(state['quarantine']),
            'held_late':held,
            'row_balanced':c['input']==explained,'completed':len(state['completed']),
            'expected':len(state['context']['subjects'])*len(state['context']['required_visits']),
            'deviations':len(state['deviations']),'retest_issues':len(state['retest_issues']),
            'blocked':blocked,
            'cutoff_at':state['context']['cutoff']['cutoff_at'],
            'basis_field':state['context']['cutoff']['basis_field'],
            'status':'可锁库' if not blocked and c['input']==explained else '待处理'}
def apply(state):
    state['balance']=decide(state);state['views']['locking']={'title':'锁库闸门（截止 %s）'%state['context']['cutoff']['cutoff_at'],'rows':[state['balance']],'metrics':{'应访视':state['balance']['expected'],'已完成':state['balance']['completed'],'阻断项':state['balance']['blocked'],'晚到暂缓':state['balance']['held_late']}}
