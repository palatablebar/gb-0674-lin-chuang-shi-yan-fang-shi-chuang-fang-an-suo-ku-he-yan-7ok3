// 锁库登记：封存（仅追加）、同批重跑校验、失败保留旧版、审计链渲染。
const sealBtn=document.querySelector('#seal-btn');
const sealFeedback=document.querySelector('#seal-feedback');
const locksBody=document.querySelector('#locks-table tbody');
const auditBody=document.querySelector('#audit-table tbody');
const auditVerify=document.querySelector('#audit-verify');

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function short(h){return h?h.slice(0,16)+'…':'';}

async function refreshLocks(){
  const r=await fetch('/api/locks');const data=await r.json();
  if(!data.locks.length){locksBody.innerHTML='<tr><td colspan="5" class="muted">尚无正式锁库。</td></tr>';return;}
  locksBody.innerHTML=data.locks.map(l=>`
    <tr>
      <td class="lock-no">${esc(l.lock_no)}</td>
      <td>${esc(l.run_id)}</td>
      <td>${esc(l.cutoff_at)}</td>
      <td>${esc(l.sealed_at)}</td>
      <td style="text-align:left;white-space:normal">
        <button class="ghost" data-recompute="${esc(l.lock_no)}">同批重跑校验</button>
        <a class="ghost-link" href="/api/locks/${esc(l.lock_no)}/certificate">下载锁库证书</a>
      </td>
    </tr>`).join('');
  locksBody.querySelectorAll('[data-recompute]').forEach(b=>b.addEventListener('click',()=>recompute(b.dataset.recompute,false)));
}

async function refreshAudit(){
  const r=await fetch('/api/audit');const data=await r.json();
  auditVerify.textContent=data.verify.ok?`链完整 · ${data.verify.entries} 条`:'链断裂';
  auditVerify.style.color=data.verify.ok?'var(--ok)':'var(--bad)';
  const entries=[...data.entries].reverse();
  if(!entries.length){auditBody.innerHTML='<tr><td colspan="6" class="muted">暂无审计记录。</td></tr>';return;}
  auditBody.innerHTML=entries.map(e=>`
    <tr><td>${e.seq}</td><td>${esc(e.action)}</td><td class="lock-no">${esc(e.entity)}</td>
    <td>${esc(e.recorded_at)}</td><td title="${esc(e.prev_hash)}">${short(e.prev_hash)}</td>
    <td title="${esc(e.entry_hash)}">${short(e.entry_hash)}</td></tr>`).join('');
}

async function recompute(lockNo,injectFailure){
  const r=await fetch(`/api/locks/${lockNo}/recompute`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({inject_failure:injectFailure})});
  const data=await r.json();
  if(r.ok){sealFeedback.className='seal-feedback ok';sealFeedback.textContent=`${lockNo}：${data.message}`;}
  else{sealFeedback.className='seal-feedback err';sealFeedback.textContent=`${lockNo}：${data.detail||'重算失败，旧版已保留'}`;}
  refreshLocks();refreshAudit();
}

if(sealBtn){
  sealBtn.addEventListener('click',async()=>{
    sealBtn.disabled=true;sealFeedback.className='seal-feedback';sealFeedback.textContent='封存中…';
    try{
      const r=await fetch('/api/locks/seal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:CURRENT_RUN_ID})});
      const data=await r.json();
      if(!r.ok)throw new Error(data.detail||'封存失败');
      sealFeedback.className='seal-feedback ok';
      sealFeedback.textContent=(data.created?'已封存正式锁库':'该批此前已封存，幂等返回')+'：'+data.lock.lock_no;
      refreshLocks();refreshAudit();
    }catch(e){sealFeedback.className='seal-feedback err';sealFeedback.textContent=e.message;}
    finally{sealBtn.disabled=false;}
  });
  document.querySelector('#recompute-fail').addEventListener('click',async()=>{
    // 先确保有正式锁库，再注入一次失败重算，验证旧版保留。
    const r=await fetch('/api/locks');const data=await r.json();
    if(!data.locks.length){sealFeedback.className='seal-feedback err';sealFeedback.textContent='请先封存一个正式锁库，再验证失败重算。';return;}
    recompute(data.locks[0].lock_no,true);
  });
  refreshLocks();refreshAudit();
}
