REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'LATE_RECEIPT_COMPLETED':'晚到-访视已完成', 'LATE_BACKFILL_EARLIER':'晚到-补录指向更早采样',
    'LATE_AFTER_EVENT':'晚到-采样在截止后', 'ON_TIME_RECEIPT':'按时接收',
    'ON_TIME_BACKFILL':'截止前补录', 'LEGACY_RECEIPT_DEFAULT':'旧批缺接收时刻',
    'LOCK_HELD':'晚到暂缓未清', 'LOCK_BUSY':'锁库已封存', 'LOCK_MISMATCH':'重算结果与正式快照不一致',
    'LOCK_FAILED':'重算失败保留旧版', 'AUDIT_BROKEN':'审计链校验失败',
}
def reject(state, record, code, detail):
    state['quarantine'].append({'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}})
