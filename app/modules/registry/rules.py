from app.lockstore import snapshot_fingerprint

def apply(state):
    """引擎内只做封存预览，不触碰数据库；正式封存由 registry handler 走仅追加存储。

    部分运行（until<全量）尚无 input_snapshot，本模块直接跳过，待全量运行再生成预览。
    run_id/rule_version 由 engine 在生成 manifest 后回填（见 engine.py）。
    """
    if 'input_snapshot' not in state and 'archive' not in state:
        return
    state['lock_preview']={
        'run_id':'',
        'source':state['source'],
        'rule_version':'',
        'cutoff_at':state['context']['cutoff']['cutoff_at'],
        'basis_field':state['context']['cutoff']['basis_field'],
        'snapshot_sha256':snapshot_fingerprint(state) if 'input_snapshot' in state else '',
        'seal_sha256':state.get('archive',{}).get('seal',''),
        'status':state.get('balance',{}).get('status',''),
        'held_late':len(state.get('late_register',[])),
        'results':len(state.get('selected_results',[])),
    }
    state['views']['registry']={
        'title':'锁库登记（截止 %s）'%state['context']['cutoff']['cutoff_at'],
        'rows':[state['lock_preview']],
        'metrics':{'可封存':1 if state.get('balance',{}).get('status')=='可锁库' else 0,
                   '晚到暂缓':len(state.get('late_register',[])),
                   '结果数':len(state.get('selected_results',[]))},
    }
