// ═══════════════════════════════════════
// ESTADO
// ═══════════════════════════════════════
let graficoInstancia = null;
let _postLinks = [];
let _stepTimer = null;
let _currentStep = 0;
let _emFila = false;

// ═══════════════════════════════════════
// FORMATAÇÃO
// ═══════════════════════════════════════
function fmtNum(v) {
  v = Number(v) || 0;
  return v >= 1e9 ? `${(v/1e9).toFixed(1)}B`
       : v >= 1e6 ? `${(v/1e6).toFixed(1)}M`
       : v >= 1e4 ? `${(v/1000).toFixed(0)}K`
       : v >= 1000 ? `${(v/1000).toFixed(1)}K`
       : String(v);
}

// ═══════════════════════════════════════
// LOADING CARD — novo sistema
// ═══════════════════════════════════════
const LC_STEPS = [
  { icon: '🔍', step: 'acessando o perfil…',         detail: 'abrindo o Instagram',              pct: 12 },
  { icon: '📸', step: 'coletando posts…',             detail: 'lendo as publicações recentes',    pct: 30 },
  { icon: '📊', step: 'medindo engajamento…',         detail: 'calculando likes e comentários',   pct: 50 },
  { icon: '🤖', step: 'enviando para a IA…',          detail: 'a inteligência artificial acordou', pct: 68 },
  { icon: '💡', step: 'gerando insights…',            detail: 'descobrindo oportunidades de crescimento', pct: 83 },
  { icon: '✨', step: 'finalizando análise…',         detail: 'quase lá, só mais um segundo',     pct: 95 },
];

const LC_FILA = [
  { step: 'servidor ocupado — você está na fila…',   detail: 'outro perfil está sendo analisado' },
  { step: 'aguardando sua vez…',                      detail: 'fila de análise em andamento'      },
  { step: 'quase liberando…',                         detail: 'obrigado pela paciência!'           },
  { step: 'ainda na fila…',                           detail: 'logo logo é sua vez'                },
];

function _lcSet(icon, step, detail, pct) {
  const elIcon   = document.getElementById('lcIcon');
  const elStep   = document.getElementById('lcStep');
  const elDetail = document.getElementById('lcDetail');
  const elBar    = document.getElementById('lcBar');

  // fade out → troca → fade in
  elStep.classList.add('fade');
  elDetail.classList.add('fade');
  setTimeout(() => {
    if (icon)   elIcon.textContent   = icon;
    if (step)   elStep.textContent   = step;
    if (detail) elDetail.textContent = detail;
    if (pct !== undefined) elBar.style.width = pct + '%';
    elStep.classList.remove('fade');
    elDetail.classList.remove('fade');
  }, 280);
}

function _tickStep() {
  if (_emFila) return;
  if (_currentStep >= LC_STEPS.length) return;
  const s = LC_STEPS[_currentStep];
  _lcSet(s.icon, s.step, s.detail, s.pct);
  _currentStep++;
  const delay = _currentStep <= 2 ? 2000 : _currentStep <= 4 ? 3500 : 5500;
  _stepTimer = setTimeout(_tickStep, delay);
}

function _entrarModoFila() {
  if (_emFila) return;
  _emFila = true;
  clearTimeout(_stepTimer);
  document.getElementById('lcFilaBadge').classList.add('visible');
  document.getElementById('lcBar').style.width = '18%';
  let fi = 0;
  function _tickFila() {
    if (!_emFila) return;
    const s = LC_FILA[fi % LC_FILA.length];
    _lcSet('⏳', s.step, s.detail, undefined);
    fi++;
    _stepTimer = setTimeout(_tickFila, 7000);
  }
  _tickFila();
}

// mantém compatibilidade com o progressBox antigo (não quebra nada)
function _setProgress(pct, txt) {
  try {
    document.getElementById('progressBar').style.width   = pct + '%';
    document.getElementById('progressLabel').textContent = txt;
    document.getElementById('progressPct').textContent   = pct + '%';
  } catch(e) {}
}

// ═══════════════════════════════════════
// LOADING
// ═══════════════════════════════════════
function setLoading(on) {
  const btn     = document.getElementById('btnAnalisar');
  const label   = document.getElementById('btnLabel');
  const arrow   = document.getElementById('btnArrow');
  const spinner = document.getElementById('btnSpinner');
  const card    = document.getElementById('loadingCard');

  btn.disabled = on;
  arrow.classList.toggle('hidden', on);
  spinner.classList.toggle('hidden', !on);

  if (on) {
    label.textContent = 'analisando…';
    card.classList.add('visible');
    document.getElementById('lcFilaBadge').classList.remove('visible');
    document.getElementById('lcBar').style.width = '0%';
    _currentStep = 0;
    _emFila = false;
    _lcSet('🔍', 'iniciando análise…', 'preparando tudo pra você', 0);
    setTimeout(_tickStep, 600);

    // se após 18s ainda estiver nos primeiros steps → modo fila
    setTimeout(() => { if (_currentStep <= 2) _entrarModoFila(); }, 18000);

  } else {
    _emFila = false;
    clearTimeout(_stepTimer);
    label.textContent = 'analisar';

    // mostra "concluído" por 1s antes de sumir
    _lcSet('✅', 'análise concluída!', 'seus resultados estão abaixo', 100);
    setTimeout(() => { card.classList.remove('visible'); }, 1000);
  }
}

// ═══════════════════════════════════════
// ANÚNCIO
// ═══════════════════════════════════════
function fitAdBox() {
  const box   = document.getElementById('adBox');
  const inner = document.getElementById('container-92f088488ade5e217e5a7609b611e56a');
  if (!box || !inner) return;
  const apply = () => {
    const iframe = inner.querySelector('iframe');
    const target = iframe || inner;
    const rawW = iframe ? (parseInt(iframe.getAttribute('width')) || iframe.offsetWidth || inner.scrollWidth) : inner.scrollWidth;
    const rawH = iframe ? (parseInt(iframe.getAttribute('height')) || iframe.offsetHeight || inner.scrollHeight) : inner.scrollHeight;
    if (rawW > 10 && rawH > 10) {
      const maxW = Math.min(rawW, window.innerWidth * 0.88);
      box.style.width  = maxW + 'px';
      box.style.height = rawH + 'px';
      return true;
    }
    return false;
  };
  if (apply()) return;
  let attempts = 0;
  const obs = new MutationObserver(() => { if (apply()) obs.disconnect(); });
  obs.observe(inner, { childList: true, subtree: true, attributes: true });
  const poll = setInterval(() => {
    attempts++;
    if (apply() || attempts > 20) { clearInterval(poll); obs.disconnect(); }
  }, 250);
}

function mostrarAnuncio() {
  return new Promise((resolve) => {
    const overlay  = document.getElementById('adOverlay');
    const btn      = document.getElementById('btnFecharAd');
    const skipInfo = document.getElementById('adSkipInfo');
    btn.disabled = true;
    btn.textContent = 'aguarde 5s';
    if (skipInfo) skipInfo.textContent = 'aguarde para continuar…';
    overlay.classList.add('visible');
    requestAnimationFrame(() => setTimeout(fitAdBox, 100));
    let seg = 5;
    const timer = setInterval(() => {
      seg--;
      fitAdBox();
      if (seg > 0) { btn.textContent = `aguarde ${seg}s`; }
      else {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = 'continuar →';
        if (skipInfo) skipInfo.textContent = 'pronto! pode continuar.';
        fitAdBox();
      }
    }, 1000);
    btn.onclick = () => {
      if (btn.disabled) return;
      overlay.classList.remove('visible');
      setTimeout(resolve, 300);
    };
  });
}

// ═══════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════
function setUrl(url) { document.getElementById('urlInput').value = url; }
function escHtml(t) {
  return String(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function fillList(id, items, icon) {
  const el = document.getElementById(id);
  if (!items || !items.length) {
    el.innerHTML = `<li><span class="li-icon">${icon}</span>Nenhuma informação encontrada.</li>`;
    return;
  }
  el.innerHTML = items.map(i => `<li><span class="li-icon">${icon}</span>${escHtml(i)}</li>`).join('');
}
function mostrarErro(msg, classe='') {
  const el = document.getElementById('erroBox');
  el.className = 'erro-box' + (classe ? ' ' + classe : '');
  el.innerHTML = `⚠ ${escHtml(msg)}`;
  el.classList.remove('hidden');
}
function pulse() {
  const input = document.getElementById('urlInput');
  input.classList.add('pulse');
  setTimeout(() => input.classList.remove('pulse'), 600);
}
function resetar() {
  document.getElementById('resultado').classList.add('hidden');
  document.getElementById('erroBox').classList.add('hidden');
  document.getElementById('urlInput').value = '';
  document.getElementById('estatisticasArea').style.display = 'none';
  document.getElementById('cardPublicoAlvo').style.display  = 'none';
  if (graficoInstancia) { graficoInstancia.destroy(); graficoInstancia = null; }
  document.getElementById('inputSection').classList.remove('hidden');
  document.getElementById('heroText').classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ═══════════════════════════════════════
// PÚBLICO-ALVO
// ═══════════════════════════════════════
function renderizarPublicoAlvo(pa) {
  const card    = document.getElementById('cardPublicoAlvo');
  const content = document.getElementById('publicoAlvoContent');
  if (!pa || !Object.keys(pa).length) { card.style.display='none'; return; }
  const interesses = Array.isArray(pa.interesses) ? pa.interesses : [];
  content.innerHTML = `
    <div class="pa-stat"><h4>faixa etária</h4><p>${escHtml(pa.faixa_etaria||'—')}</p></div>
    <div class="pa-stat"><h4>gênero predominante</h4><p>${escHtml(pa.genero||'—')}</p></div>
    <div class="pa-stat"><h4>tom de comunicação</h4><p>${escHtml(pa.tom||'—')}</p></div>
    ${interesses.length ? `<div class="pa-interesses"><h4>interesses</h4><div class="pa-interesses-chips">${interesses.map(i=>`<span class="pa-chip">${escHtml(i)}</span>`).join('')}</div></div>` : ''}
    ${pa.resumo ? `<div class="pa-resumo"><span class="pa-resumo-label">✦ quem são os seguidores</span>${escHtml(pa.resumo)}</div>` : ''}
  `;
  card.style.display = 'block';
}

// ═══════════════════════════════════════
// IDEIAS
// ═══════════════════════════════════════
function renderizarIdeias(ideias) {
  const grid = document.getElementById('ideiasGrid');
  if (!ideias || !ideias.length) { grid.innerHTML='<p style="color:rgba(255,255,255,.3);font-size:.85rem">Nenhuma ideia encontrada.</p>'; return; }
  grid.innerHTML = ideias.map(ideia => {
    const texto = typeof ideia==='string' ? ideia : ideia.texto;
    const tags  = (typeof ideia==='object' && ideia.tags) ? ideia.tags : [];
    const linksHtml = tags.map(tag => {
      const igUrl  = `https://www.instagram.com/explore/tags/${encodeURIComponent(tag)}/`;
      const pinUrl = `https://www.pinterest.com/search/pins/?q=${encodeURIComponent(tag)}`;
      return `
        <a href="${igUrl}" target="_blank" class="ref-link-btn ig">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073z"/></svg>
          #${escHtml(tag)}
        </a>
        <a href="${pinUrl}" target="_blank" class="ref-link-btn pin">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.373 0 0 5.373 0 12c0 5.084 3.163 9.426 7.627 11.174-.105-.949-.2-2.405.042-3.441.218-.937 1.407-5.965 1.407-5.965s-.359-.719-.359-1.782c0-1.668.967-2.914 2.171-2.914 1.023 0 1.518.769 1.518 1.69 0 1.029-.655 2.568-.994 3.995-.283 1.194.599 2.169 1.777 2.169 2.133 0 3.772-2.249 3.772-5.495 0-2.873-2.064-4.882-5.012-4.882-3.414 0-5.418 2.561-5.418 5.207 0 1.031.397 2.138.893 2.738a.36.36 0 0 1 .083.345l-.333 1.36c-.053.22-.174.267-.402.161-1.499-.698-2.436-2.889-2.436-4.649 0-3.785 2.75-7.262 7.929-7.262 4.163 0 7.398 2.967 7.398 6.931 0 4.136-2.607 7.464-6.227 7.464-1.216 0-2.359-.632-2.75-1.378l-.748 2.853c-.271 1.043-1.002 2.35-1.492 3.146C9.57 23.812 10.763 24 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0z"/></svg>
          Pinterest
        </a>
      `;
    }).join('');
    const tagsHtml = tags.map(t=>`<span class="ideia-tag">#${escHtml(t)}</span>`).join('');
    return `
      <div class="ideia-card">
        <div class="ideia-texto"><span class="li-icon" style="color:var(--pink)">●</span><span>${escHtml(texto)}</span></div>
        ${tagsHtml ? `<div class="ideia-tags">${tagsHtml}</div>` : ''}
        ${linksHtml ? `<div class="refs-row" style="margin-top:.4rem;gap:.5rem;flex-wrap:wrap;">${linksHtml}</div>` : ''}
      </div>`;
  }).join('');
}

// ═══════════════════════════════════════
// LABEL DO POST
// ═══════════════════════════════════════
function labelDoPost(post, idx) {
  const url   = post.url || post.link || '';
  const match = url.match(/\/(p|reel)\/([^/]+)/);
  const tipo  = match ? match[1] : 'post';
  const caption = (post.caption||'').replace(/^[\d.,]+[KkMm]?\s*likes.*?:\s*[""]?/i,'').trim();
  if (caption && caption.length > 4) {
    const semEmoji = caption.replace(/[\u{1F300}-\u{1FFFF}]/gu,'').trim();
    const palavras = semEmoji.split(/\s+/).slice(0,4).join(' ');
    if (palavras.length > 3) return palavras;
  }
  return match ? `${tipo} ${match[2].slice(0,8)}` : `post ${idx+1}`;
}

// ═══════════════════════════════════════
// PLUGIN CLIQUE LABEL GRÁFICO
// ═══════════════════════════════════════
const clickLabelPlugin = {
  id: 'clickLabel',
  afterEvent(chart, args) {
    const e = args.event;
    if (e.type !== 'click') return;
    const xScale = chart.scales.x;
    if (!xScale || e.y < xScale.top) return;
    for (let i = 0; i < xScale.ticks.length; i++) {
      const px = xScale.getPixelForTick(i);
      if (Math.abs(e.x - px) < 55) {
        const link = _postLinks[i];
        if (link && link !== '#') window.open(link, '_blank');
        break;
      }
    }
  }
};

// ═══════════════════════════════════════
// ESTATÍSTICAS + GRÁFICO
// ═══════════════════════════════════════
function renderizarEstatisticas(posts) {
  const area = document.getElementById('estatisticasArea');
  if (!posts || !posts.length) { area.style.display='none'; return; }
  area.style.display = 'flex';
  const dados = posts.map((p,i) => ({
    titulo:      labelDoPost(p, i),
    likes:       Number(p.likes       || p.curtidas      || 0),
    comentarios: Number(p.comentarios ?? p.comments      ?? 0),
    views:       Number(p.views       || p.visualizacoes || 0),
    link:        p.url || p.link || '#'
  }));
  _postLinks = dados.map(d => d.link);
  let totalViews=0, totalEngajamento=0;
  dados.forEach(p => { totalViews += p.views; totalEngajamento += (p.likes + p.comentarios); });
  const melhorPost = dados.reduce((b,p) => (p.likes+p.comentarios)>(b.likes+b.comentarios)?p:b, dados[0]);
  const temViews = totalViews > 0;
  document.getElementById('labelViews').textContent   = temViews ? 'Total Visualizações (reels)' : 'Média de Likes';
  document.getElementById('totalViews').innerText     = temViews ? fmtNum(totalViews) : fmtNum(Math.round(totalEngajamento/dados.length));
  document.getElementById('totalLikes').innerText     = fmtNum(totalEngajamento);
  document.getElementById('melhorPostTitulo').innerText = `${fmtNum(melhorPost.likes)} likes · ${fmtNum(melhorPost.comentarios)} comentários`;
  const linkEl = document.getElementById('melhorPostLink');
  linkEl.style.display = (melhorPost.link && melhorPost.link !== '#') ? 'inline-block' : 'none';
  if (melhorPost.link) linkEl.href = melhorPost.link;
  const canvas = document.getElementById('meuGrafico');
  if (!canvas) return;
  if (graficoInstancia) { graficoInstancia.destroy(); graficoInstancia = null; }
  Chart.defaults.color = 'rgba(255,255,255,0.7)';
  Chart.defaults.font.family = "'Syne', sans-serif";
  const escalaX = {
    grid: { display: false },
    ticks: { maxRotation: 35, color: 'rgba(0,207,255,0.85)', font: { size: 11 },
      callback: function(val) { const l=this.getLabelForValue(val); return l.length>20?l.slice(0,20)+'…':l; } }
  };
  const datasets = temViews
    ? [
        { label:'Visualizações (reels)', data:dados.map(p=>p.views), backgroundColor:'rgba(56,189,248,0.6)', borderColor:'#38bdf8', borderWidth:1, borderRadius:6, yAxisID:'yViews' },
        { label:'Engajamento', data:dados.map(p=>p.likes+p.comentarios), backgroundColor:'rgba(52,211,153,0.6)', borderColor:'#34d399', borderWidth:1, borderRadius:6, yAxisID:'yEng' }
      ]
    : [
        { label:'Likes', data:dados.map(p=>p.likes), backgroundColor:'rgba(255,60,172,0.6)', borderColor:'#ff3cac', borderWidth:1, borderRadius:6 },
        { label:'Comentários', data:dados.map(p=>p.comentarios), backgroundColor:'rgba(200,255,0,0.5)', borderColor:'#c8ff00', borderWidth:1, borderRadius:6 }
      ];
  const scales = temViews
    ? { yViews:{type:'linear',position:'left',beginAtZero:true,grid:{color:'rgba(255,255,255,0.06)'},ticks:{callback:fmtNum}}, yEng:{type:'linear',position:'right',beginAtZero:true,grid:{drawOnChartArea:false},ticks:{callback:fmtNum}}, x:escalaX }
    : { y:{beginAtZero:true,grid:{color:'rgba(255,255,255,0.06)'},ticks:{callback:fmtNum}}, x:escalaX };
  graficoInstancia = new Chart(canvas.getContext('2d'), {
    type:'bar',
    data:{ labels:dados.map(d=>d.titulo), datasets },
    options:{ responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false},
      plugins:{ legend:{position:'top'}, tooltip:{callbacks:{label:ctx=>` ${ctx.dataset.label}: ${ctx.parsed.y.toLocaleString('pt-BR')}`}} },
      scales },
    plugins:[clickLabelPlugin]
  });
  canvas.style.cursor='default';
  canvas.addEventListener('mousemove', ev => {
    const rect=canvas.getBoundingClientRect(), mouseY=ev.clientY-rect.top;
    const xScale=graficoInstancia?.scales?.x;
    canvas.style.cursor=(xScale && mouseY>xScale.top)?'pointer':'default';
  });
}

// ═══════════════════════════════════════
// ANÁLISE PRINCIPAL
// ═══════════════════════════════════════
async function rodarAnalise() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) { pulse(); return; }

  const totalAnalises = (parseInt(localStorage.getItem('totalAnalises')||'0')) + 1;
  localStorage.setItem('totalAnalises', String(totalAnalises));
  if (totalAnalises > 1) await mostrarAnuncio();

  setLoading(true);
  document.getElementById('resultado').classList.add('hidden');
  document.getElementById('erroBox').classList.add('hidden');

  try {
    const res  = await fetch('/api/analisar', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ url }) });
    const data = await res.json();
    console.log('API:', data);

    if (res.status === 422 && data.erro === 'perfil_privado') {
      mostrarErro('🔒 Este perfil é privado. Só é possível analisar perfis públicos.', 'privado');
      return;
    }
    if (res.status === 422 && data.erro === 'url_invalida') {
      mostrarErro(data.mensagem || 'URL inválida.', 'invalida');
      return;
    }
    if (!data.ok || data.erro) { mostrarErro(data.erro || 'Erro desconhecido'); return; }

    const a = data.analise || {};
    const score = Math.max(0, Math.min(100, Math.round(a.score || 0)));
    document.getElementById('scoreNum').textContent    = `${score}/100`;
    document.getElementById('scoreMotivo').textContent = a.score_motivo || '';
    document.getElementById('resumoTxt').textContent   = a.resumo       || '';
    document.getElementById('redeTag').textContent     = data.rede      || 'web';
    setTimeout(() => { document.getElementById('scoreBar').style.width = `${score}%`; }, 100);

    const postsParaGrafico = (data.perfil?.posts?.length) ? data.perfil.posts : (data.dados_grafico || []);
    renderizarEstatisticas(postsParaGrafico);
    fillList('listFortes',        a.pontos_fortes || [], '✦');
    fillList('listOportunidades', a.oportunidades || [], '◆');
    fillList('listPassos',        a.estrategia_crescimento || a.proximos_passos || [], '→');
    renderizarIdeias(a.ideias_conteudo || []);
    renderizarPublicoAlvo(a.publico_alvo || {});

    document.getElementById('inputSection').classList.add('hidden');
    document.getElementById('heroText').classList.add('hidden');
    const secao = document.getElementById('resultado');
    secao.classList.remove('hidden');
    secao.scrollIntoView({ behavior:'smooth' });

  } catch(e) {
    console.error(e);
    mostrarErro('Erro de conexão: ' + e.message);
  } finally {
    setLoading(false);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('urlInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') rodarAnalise();
  });
});

