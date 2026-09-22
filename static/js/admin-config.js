let pollTimer = null;
let ultimoScreenshot = null; // evita resetar imagem desnecessariamente

function renderizar(data) {
  const contas = data.contas || [];
  document.getElementById('stat-total').textContent   = data.total   ?? contas.length;
  document.getElementById('stat-livre').textContent   = data.livres  ?? contas.filter(c => c.status === 'livre').length;
  document.getElementById('stat-scrapes').textContent = data.total_scrapes ?? 0;
  document.getElementById('count-badge').textContent  = contas.length + (contas.length === 1 ? ' conta' : ' contas');

  const list = document.getElementById('accounts-list');
  if (!contas.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
        </div>
        <div class="empty-title">Nenhuma conta cadastrada</div>
        <div class="empty-sub">Cadastre uma conta acima para começar.</div>
      </div>`;
    return;
  }
  list.innerHTML = contas.map(c => {
    const inicial     = (c.username || '?')[0].toUpperCase();
    const statusClass = {livre:'status-livre',ocupado:'status-ocupado',banido:'status-banido',pendente:'status-pendente'}[c.status] || 'status-livre';
    const statusLabel = {livre:'livre',ocupado:'ocupado',banido:'banido',pendente:'aguardando login'}[c.status] || c.status;
    const ultimoLogin = c.ultimo_login ? new Date(c.ultimo_login).toLocaleDateString('pt-BR') : 'nunca';
    return `
      <div class="account-row">
        <div class="account-avatar">${inicial}</div>
        <div class="account-info">
          <div class="account-username">@${c.username}</div>
          <div class="account-meta">cadastrado ${c.data_cadastro||'—'} · último login ${ultimoLogin}</div>
        </div>
        <span class="account-status ${statusClass}">
          <span class="status-dot"></span>${statusLabel}
        </span>
        <div class="account-scrapes"><strong>${c.scrapes||0}</strong><br>scrapes</div>
        <div class="account-actions">
          <button class="icon-btn" onclick="relogar('${c.username}','${c.profile_dir||''}')" title="Refazer login">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg>
          </button>
          <button class="icon-btn danger" onclick="remover('${c.username}')" title="Remover">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>
      </div>`;
  }).join('');
}

function atualizarLoginBar(ls) {
  const bar = document.getElementById('login-bar');
  const msg = document.getElementById('login-bar-msg');
  const stg = document.getElementById('login-bar-stage');
  const scBox = document.getElementById('login-screenshot');
  const scImg = document.getElementById('login-screenshot-img');

  // Sem login ativo — esconde tudo
  if (!ls || (!ls.running && !ls.stage)) {
    bar.className = 'login-bar';
    scBox.style.display = 'none';
    ultimoScreenshot = null;
    return;
  }

  bar.classList.add('show');
  msg.textContent = ls.message || '…';
  stg.textContent = ls.stage   || '';
  bar.classList.remove('done', 'error');
  if (ls.stage === 'done')  bar.classList.add('done');
  if (ls.stage === 'error') bar.classList.add('error');

  // Só atualiza screenshot se for diferente do anterior (evita piscar)
  if (ls.screenshot && ls.screenshot !== ultimoScreenshot) {
    ultimoScreenshot = ls.screenshot;
    scImg.src = ls.screenshot;
    scBox.style.display = 'block';
  } else if (!ls.screenshot) {
    scBox.style.display = 'none';
  }

  if (ls.stage === 'waiting_2fa') {
    document.getElementById('modal-2fa').classList.add('open');
  }

  if (ls.stage === 'done' || ls.stage === 'error') {
    document.getElementById('modal-2fa').classList.remove('open');
    clearInterval(pollTimer);  // para o polling
    pollTimer = null;
    atualizarStatus();
    setTimeout(() => {
        bar.className = 'login-bar';
        scBox.style.display = 'none';
        ultimoScreenshot = null;
    }, 5000);
}}

async function atualizarStatus() {
  try {
    const r = await fetch('/admin/config/status');
    if (!r.ok) return;
    const data = await r.json();
    renderizar(data);
    atualizarLoginBar(data.login_status);
  } catch(e) { console.warn(e); }
}

function iniciarPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(atualizarStatus, 3000);
}

async function iniciarLogin() {
  const username = document.getElementById('input-username').value.replace('@','').trim();
  const password = document.getElementById('input-password').value.trim();
  const profile  = document.getElementById('input-profile').value.trim() || ('ig_profile_' + username);

  if (!username) { toast('Digite o usuário', true); return; }
  if (!password) { toast('Digite a senha', true); return; }

  const btn = document.getElementById('btn-add');
  btn.disabled = true;

  try {
    const r = await fetch('/admin/config/login-instagram', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username, password, profile_dir: profile})
    });
    const data = await r.json();
    if (data.ok) {
      toast('Fazendo login…');
      document.getElementById('input-password').value = '';
      iniciarPolling();
    } else {
      toast(data.error || 'Erro ao iniciar login', true);
    }
  } catch(e) {
    toast('Erro de conexão', true);
  }
  btn.disabled = false;
}

function fechar2FA() {
  document.getElementById('modal-2fa').classList.remove('open');
}

async function enviar2FA() {
  const code = document.getElementById('input-2fa').value.trim();
  if (!code) { toast('Digite o código', true); return; }

  const btn = document.getElementById('btn-2fa');
  const txt = document.getElementById('btn-2fa-text');
  btn.disabled = true;
  txt.textContent = 'Enviando…';

  try {
    const r = await fetch('/admin/config/enviar-2fa', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({code})
    });
    const data = await r.json();
    if (data.ok) {
      toast('Código enviado!');
      document.getElementById('input-2fa').value = '';
    } else {
      toast(data.error || 'Erro ao enviar código', true);
    }
  } catch(e) {
    toast('Erro de conexão', true);
  }
  btn.disabled = false;
  txt.textContent = 'Confirmar';
}

function relogar(username, profileDir) {
  document.getElementById('input-username').value = username;
  document.getElementById('input-profile').value  = profileDir || ('ig_profile_' + username);
  document.getElementById('input-password').value = '';
  document.getElementById('input-password').focus();
  toast('Digite a senha e clique em Cadastrar');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function remover(username) {
  if (!confirm('Remover @' + username + '?')) return;
  try {
    const r = await fetch('/admin/config/remover/' + encodeURIComponent(username), {method:'DELETE'});
    if (r.ok) { toast('Conta removida'); await atualizarStatus(); }
    else toast('Erro ao remover', true);
  } catch(e) { toast('Erro de conexão', true); }
}

let toastTimer;
function toast(msg, erro=false) {
  const el = document.getElementById('toast');
  document.getElementById('toast-msg').textContent = msg;
  el.classList.toggle('error', erro);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

document.getElementById('input-username').addEventListener('input', function() {
  const u = this.value.replace('@','').trim();
  const p = document.getElementById('input-profile');
  if (!p.dataset.touched) p.value = u ? 'ig_profile_' + u : '';
});
document.getElementById('input-profile').addEventListener('input', function() {
  this.dataset.touched = '1';
});
document.getElementById('input-2fa').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') enviar2FA();
});
document.getElementById('modal-2fa').addEventListener('click', function(e) {
  if (e.target === this) fechar2FA();
});

// INIT — só carrega uma vez, sem polling contínuo
atualizarStatus();

