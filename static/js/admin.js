async function limparCache() {
  const btn = document.getElementById('btn-cache');
  const msg = document.getElementById('cache-msg');
  btn.disabled = true;
  btn.innerHTML = '<span class="icon">⏳</span> Limpando...';
  try {
    const res  = await fetch('/admin/config/limpar-cache', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      msg.textContent = `✅ ${data.liberado_mb} MB liberados com sucesso!`;
      btn.innerHTML   = '<span class="icon">✅</span> Limpo!';
      setTimeout(() => {
        btn.disabled  = false;
        btn.innerHTML = '<span class="icon">🧹</span> Limpar Cache';
        msg.textContent = 'Limpa o cache acumulado das contas de scraping (cookies são mantidos)';
      }, 4000);
    } else {
      throw new Error(data.error || 'Erro desconhecido');
    }
  } catch(e) {
    msg.textContent = '❌ Erro: ' + e.message;
    btn.disabled    = false;
    btn.innerHTML   = '<span class="icon">🧹</span> Limpar Cache';
  }
}

async function init() {
  try {
    const res = await fetch('/api/admin/stats');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    document.getElementById('val-usuarios').textContent = data.total_usuarios;
    document.getElementById('val-analises').textContent = data.total_analises;
    document.getElementById('val-ativos').textContent   = data.usuarios_ativos;

    // GRÁFICO
    const labels = data.grafico.map(d => {
      const [,m,dia] = d.dia.split('-');
      return dia + '/' + m;
    });
    const valores = data.grafico.map(d => d.total);

    new Chart(document.getElementById('chart'), {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: valores,
          backgroundColor: ctx => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 200);
            g.addColorStop(0, 'rgba(255,60,172,.7)');
            g.addColorStop(1, 'rgba(255,60,172,.1)');
            return g;
          },
          borderColor:  'rgba(255,60,172,.9)',
          borderWidth:  1,
          borderRadius: 5,
          hoverBackgroundColor: 'rgba(255,111,216,.8)',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#13131a',
            borderColor: 'rgba(255,60,172,.3)',
            borderWidth: 1,
            titleColor: 'rgba(255,255,255,.5)',
            bodyColor: '#ff6fd8',
            titleFont: { family: 'Syne Mono', size: 10 },
            bodyFont:  { family: 'Syne', size: 13, weight: '700' },
            callbacks: {
              title: i => i[0].label,
              label: i => ' ' + i.raw + ' análises'
            }
          }
        },
        scales: {
          x: {
            ticks: { color:'rgba(255,255,255,.22)', font:{ family:'Syne Mono', size:9 }, maxRotation:0 },
            grid:  { color:'rgba(255,255,255,.04)' }
          },
          y: {
            ticks: { color:'rgba(255,255,255,.22)', font:{ family:'Syne Mono', size:9 }, stepSize:1 },
            grid:  { color:'rgba(255,255,255,.04)' },
            beginAtZero: true
          }
        }
      }
    });

    // TABELA
    const tbody = document.getElementById('users-tbody');
    for (const u of data.usuarios) {
      const pill = u.analises > 0
        ? `<span class="pill">${u.analises}</span>`
        : `<span class="pill pill-zero">0</span>`;
      const foto = u.foto
        ? `<img class="user-avatar" src="${u.foto}" alt="">`
        : `<div class="user-avatar" style="background:rgba(255,60,172,.2);display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:800">${u.nome[0]}</div>`;

      tbody.innerHTML += `
        <tr>
          <td>
            <div class="user-cell">
              ${foto}
              <div>
                <div class="user-name">${u.nome}</div>
                <div class="user-email">${u.email}</div>
              </div>
            </div>
          </td>
          <td><span class="google-id" title="${u.google_id}">${u.google_id}</span></td>
          <td>${pill}</td>
          <td><span class="date-cell">${u.ultima}</span></td>
        </tr>`;
    }

    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';

  } catch(e) {
    document.getElementById('loading').innerHTML =
      '<div class="err">Erro ao carregar dados.<br><small>' + e.message + '</small></div>';
  }
}

init();

