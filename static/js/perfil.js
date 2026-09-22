const historico = [];
    async function sendMessage() {
      const input = document.getElementById('chatInput');
      const sendBtn = document.getElementById('sendBtn');
      const msg = input.value.trim();
      if (!msg) return;
      appendMsg(msg, 'user');
      input.value = '';
      sendBtn.disabled = true;
      const typing = appendTyping();
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mensagem: msg, historico })
        });
        const data = await res.json();
        typing.remove();
        if (data.resposta) {
          appendMsg(data.resposta, 'ai');
          historico.push({ role: 'user', parts: msg });
          historico.push({ role: 'model', parts: data.resposta });
          if (historico.length > 20) historico.splice(0, 2);
        } else {
          appendMsg('erro da API: ' + (data.error || 'algo deu errado'), 'ai');
        }
      } catch (e) {
        typing.remove();
        appendMsg('erro real: ' + e.message, 'ai');
      }
      sendBtn.disabled = false;
      input.focus();
    }
    function appendMsg(text, who) {
      const box = document.getElementById('chatMessages');
      const div = document.createElement('div');
      div.className = `msg msg-${who}`;
      div.innerHTML = `<div class="msg-bubble">${escapeHtml(text)}</div>`;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
      return div;
    }
    function appendTyping() {
      const box = document.getElementById('chatMessages');
      const div = document.createElement('div');
      div.className = 'msg msg-ai';
      div.innerHTML = `<div class="msg-bubble typing"><span></span><span></span><span></span></div>`;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
      return div;
    }
    function escapeHtml(t) {
      return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    }
    document.getElementById('chatInput').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

