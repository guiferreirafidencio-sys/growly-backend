# bot.py
# =========================================================
# BOT CENTRAL DE SCRAPING — versão MULTI-CONTA
# =========================================================
#
# O QUE MUDOU em relação à versão anterior:
#
#   ANTES:
#     - PROFILE_DIR = "ig_profile" (hardcoded)
#     - _bot_instance = Bot()  (singleton único)
#     - 1 browser, 1 contexto, 1 fila
#
#   AGORA:
#     - Cada conta tem seu próprio Bot(conta)
#     - Bot usa sessions/<profile_dir> como user_data_dir
#     - _bots = { "username": Bot, ... }  (pool dinâmico)
#     - scrape_url() escolhe conta via account_manager
#     - Múltiplos scrapes podem rodar em paralelo
#
# COMO O SISTEMA DISTRIBUI CONTAS:
#   1. scrape_url(url) chama account_manager.obter_conta_livre()
#   2. account_manager escolhe a conta com menos scrapes
#   3. Marca como "ocupado" no contas.json
#   4. scrape_url recupera (ou cria) o Bot dessa conta
#   5. Executa o scrape naquele Bot
#   6. account_manager.liberar_conta() devolve ao pool
#
# COMO ADICIONAR NOVAS CONTAS:
#   - Use o painel admin (/admin/config)
#   - O admin_config.py já salva storage.json e atualiza contas.json
#   - Na próxima chamada a get_or_create_bot(conta), um novo Bot
#     é criado automaticamente para a conta recém-cadastrada
#   - Nenhuma reinicialização do servidor é necessária
#
# =========================================================

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import threading
import queue
import time
import random
import re
from pathlib import Path

from account_manager import (
    carregar_contas,
    obter_conta_livre,
    liberar_conta,
    marcar_banida,
    caminho_sessao,
)

# =========================================================
# CONFIG
# =========================================================

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# =========================================================
# HELPERS
# =========================================================

def detectar_rede(url):
    url = url.lower()
    if "instagram" in url:
        return "instagram"
    if "youtube" in url or "youtu.be" in url:
        return "youtube"
    if "github" in url:
        return "github"
    return "web"


def corrigir_likes_pela_caption(caption):
    """Extrai likes da string da caption do og:description."""
    if not caption:
        return 0
    m = re.search(r'([\d.,]+)\s*(mil|k|m)?\s*like', caption, re.IGNORECASE)
    if not m:
        return 0
    num = float(m.group(1).replace('.', '').replace(',', '.'))
    mult = {"mil": 1000, "k": 1000, "m": 1_000_000}.get(
        (m.group(2) or "").lower(), 1
    )
    return int(num * mult)


def corrigir_comentarios_pela_caption(caption):
    """Extrai comentários da string da caption do og:description."""
    if not caption:
        return 0
    m = re.search(r'([\d.,]+)\s*(mil|k|m)?\s*comment', caption, re.IGNORECASE)
    if not m:
        m = re.search(r'([\d.,]+)\s*(mil|k|m)?\s*comentário', caption, re.IGNORECASE)
    if not m:
        return 0
    num = float(m.group(1).replace('.', '').replace(',', '.'))
    mult = {"mil": 1000, "k": 1000, "m": 1_000_000}.get(
        (m.group(2) or "").lower(), 1
    )
    return int(num * mult)


# =========================================================
# BOT — instância por conta
# =========================================================

class Bot:
    """
    Representa um browser Playwright dedicado a UMA conta Instagram.

    Cada instância de Bot:
      - Recebe um dict 'conta' com username e profile_dir
      - Usa sessions/<profile_dir> como diretório persistente
      - Roda em uma thread dedicada (Playwright é single-thread)
      - Possui sua própria fila de tarefas

    NOVO vs versão anterior:
      - Antes: __init__(self) sem parâmetros, PROFILE_DIR hardcoded
      - Agora: __init__(self, conta) usa conta["profile_dir"]
    """

    def __init__(self, conta: dict):
        """
        conta: dict com pelo menos:
          {
            "username":    "conta1",
            "profile_dir": "ig_profile_conta1",
            ...
          }
        """
        self.username    = conta["username"]
        self.profile_dir = conta["profile_dir"]

        # Pasta de sessão: sessions/ig_profile_conta1
        self.session_path = str(caminho_sessao(self.profile_dir))

        self._fila   = queue.Queue()
        self._pronto = threading.Event()

        self._thread = threading.Thread(
            target=self._loop,
            name=f"playwright-{self.username}",
            daemon=True
        )
        self._thread.start()

        # Aguarda o browser estar pronto (max 30s)
        if not self._pronto.wait(timeout=30):
            raise RuntimeError(f"[BOT:{self.username}] timeout ao iniciar browser")

    # =====================================================
    # LOOP DA THREAD DEDICADA
    # =====================================================

    def _loop(self):
        """
        Toda interação com Playwright acontece aqui.
        Playwright exige que sync_api seja usada sempre
        na mesma thread que a criou — por isso o modelo
        de fila + thread dedicada é mantido.
        """
        try:
            self._pw = sync_playwright().start()
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=self.session_path,   # <- sessão isolada por conta
                headless=True,
                
                user_agent=UA,
                viewport={"width": 1400, "height": 900},
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox"
                ]
            )
            self._page = self._context.new_page()
            self._page.set_default_timeout(60000)
            self._stealth()

            print(f"[BOT:{self.username}] thread pronta — sessão: {self.session_path}")
            self._pronto.set()

            while True:
                fn, ctx = self._fila.get()
                try:
                    ctx["valor"] = fn()
                except Exception as e:
                    ctx["erro"] = e
                finally:
                    ctx["evento"].set()

        except Exception as e:
            print(f"[BOT:{self.username}] ERRO FATAL no loop: {e}")
            self._pronto.set()  # desbloqueia o wait mesmo em erro

    # =====================================================
    # EXECUTOR — envia tarefa para a thread dedicada
    # =====================================================

    def _run(self, fn, timeout=90):
        """
        CORRIGIDO: timeout explícito evita que o worker do Gunicorn
        seja morto por SIGABRT enquanto aguarda indefinidamente.
        O timeout aqui (90s) deve ser MENOR que o timeout do Gunicorn.
        """
        ctx = {"valor": None, "erro": None, "evento": threading.Event()}
        self._fila.put((fn, ctx))
        concluiu = ctx["evento"].wait(timeout=timeout)
        if not concluiu:
            raise TimeoutError(
                f"[BOT:{self.username}] scrape excedeu {timeout}s — "
                "verifique a conexão com Instagram ou aumente o timeout"
            )
        if ctx["erro"] is not None:
            raise ctx["erro"]
        return ctx["valor"]

    # =====================================================
    # STEALTH
    # =====================================================

    def _stealth(self):
        self._page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        window.chrome = { runtime: {} };
        """)

    # =====================================================
    # HUMANIZAÇÃO
    # =====================================================

    def _human_scroll(self):
        for _ in range(random.randint(3, 6)):
            self._page.mouse.wheel(0, random.randint(1000, 3000))
            time.sleep(random.uniform(1, 2))

    # =====================================================
    # SCROLL PROGRESSIVO
    # =====================================================

    def _scroll_carregar_posts(self, quantidade_alvo=15):
        print(f"[SCROLL:{self.username}] carregando posts (alvo: {quantidade_alvo})...")
        sem_novos       = 0
        ultima_contagem = 0

        for rodada in range(25):
            links = self._page.eval_on_selector_all(
                "a[href*='/p/'], a[href*='/reel/']",
                "els => [...new Set(els.map(e => e.getAttribute('href')))].filter(Boolean).length"
            )
            print(f"  [{self.username}] rodada {rodada+1}: {links} links")

            if links >= quantidade_alvo:
                print(f"[SCROLL:{self.username}] alvo atingido ({links})")
                break

            if links == ultima_contagem:
                sem_novos += 1
                if sem_novos >= 4:
                    print(f"[SCROLL:{self.username}] sem novos posts, parando com {links}")
                    break
            else:
                sem_novos = 0

            ultima_contagem = links
            self._page.mouse.wheel(0, random.randint(2000, 4000))
            time.sleep(random.uniform(1.5, 2.5))

            if rodada % 5 == 4:
                time.sleep(random.uniform(2, 3))

    # =====================================================
    # INSTAGRAM — interno
    # =====================================================

    def _scrape_instagram(self, url):
        print(f"\n[IG:{self.username}] {url}")
        self._page.goto(url, wait_until="networkidle")
        time.sleep(random.uniform(4, 6))

        # Se Instagram redirecionou para login, a sessão expirou
        if "/accounts/login" in self._page.url:
            # Marca conta como banida para não ser escolhida novamente
            marcar_banida(self.username)
            raise Exception(f"SESSAO_EXPIRADA:{self.username}")

        # ── CHECAGEM DE PERFIL PRIVADO ────────────────────
        eh_privado = self._page.evaluate("""
        () => {
            const desc = document.querySelector("meta[property='og:description']")?.content || "";
            if (/this account is private/i.test(desc)) return true;

            const svgs = [...document.querySelectorAll("svg[aria-label]")];
            if (svgs.some(s => /private|privad/i.test(s.getAttribute("aria-label") || ""))) return true;

            const body = document.body?.innerText || "";
            if (/esta conta é privada|this account is private/i.test(body)) return true;

            return false;
        }
        """)

        if eh_privado:
            raise Exception("PERFIL_PRIVADO")

        self._scroll_carregar_posts(quantidade_alvo=15)

        # ── PERFIL ────────────────────────────────────────
        perfil = self._page.evaluate("""
        () => {
            function limparNumero(txt) {
                if (!txt) return 0;
                txt = txt.toLowerCase().trim();
                let mult = 1;
                if (/\\bmil\\b/.test(txt))    mult = 1000;
                else if (/k/.test(txt))       mult = 1000;
                else if (/\\bm\\b/.test(txt)) mult = 1000000;
                const n = txt.match(/[\\d.,]+/);
                if (!n) return 0;
                return parseFloat(n[0].replace(/\\./g, '').replace(',', '.')) * mult;
            }

            let seguidores = 0, seguindo = 0, publicacoes = 0;

            document.querySelectorAll("a, span, li").forEach(el => {
                const aria  = (el.getAttribute("aria-label") || "").toLowerCase();
                const title = (el.getAttribute("title")      || "").toLowerCase();
                if (aria.includes("seguidores") || title.includes("seguidores")) {
                    const v = limparNumero(aria || title); if (v > seguidores) seguidores = v;
                }
                if (aria.includes("seguindo") || title.includes("seguindo")) {
                    const v = limparNumero(aria || title); if (v > seguindo) seguindo = v;
                }
                if (aria.includes("publicações") || title.includes("publicações")) {
                    const v = limparNumero(aria || title); if (v > publicacoes) publicacoes = v;
                }
            });

            if (seguidores === 0 || seguindo === 0) {
                document.querySelectorAll("span").forEach(s => {
                    const title = (s.getAttribute("title") || "").toLowerCase();
                    const txt   = (s.innerText || "").toLowerCase().trim();
                    const src   = title || txt;
                    if (src.includes("seguidores")) { const v = limparNumero(src); if (v > seguidores) seguidores = v; }
                    if (src.includes("seguindo"))   { const v = limparNumero(src); if (v > seguindo)   seguindo   = v; }
                    if (src.includes("publicações") || src.includes("posts")) {
                        const v = limparNumero(src); if (v > publicacoes) publicacoes = v;
                    }
                });
            }

            return {
                seguidores, seguindo, publicacoes,
                bio:    document.querySelector("h1")?.innerText || "",
                titulo: document.title || ""
            };
        }
        """)

        # ── LINKS DOS POSTS ───────────────────────────────
        hrefs = self._page.eval_on_selector_all(
            "a[href*='/p/'], a[href*='/reel/']",
            """els => [...new Set(
                els.map(e => e.getAttribute('href'))
                   .filter(h => h && (h.includes('/p/') || h.includes('/reel/')))
            )]"""
        )
        username_alvo = url.rstrip("/").split("/")[-1].lower()
        links_posts = [
            "https://www.instagram.com" + h for h in hrefs
            if h.lower().startswith(f"/{username_alvo}/")
        ]
        print(f"[IG:{self.username}] {len(links_posts)} posts encontrados")

        if perfil.get("publicacoes", 0) > 0 and len(links_posts) == 0:
            print(f"[IG:{self.username}] perfil aparenta ser privado/restrito")
            raise Exception("PERFIL_PRIVADO")

        # ── SCRAPING DE CADA POST ─────────────────────────
        posts = []

        for full in links_posts[:15]:
            try:
                print(f"POST [{self.username}]:", full)
                self._page.goto(full, wait_until="networkidle")
                time.sleep(random.uniform(2, 4))

                post = self._page.evaluate("""
                () => {
                    function limparNumero(txt) {
                        if (!txt) return 0;
                        txt = txt.toLowerCase().trim();
                        let mult = 1;
                        if (/\\bmil\\b/.test(txt))    mult = 1000;
                        else if (/k/.test(txt))       mult = 1000;
                        else if (/\\bm\\b/.test(txt)) mult = 1000000;
                        const n = txt.match(/[\\d.,]+/);
                        if (!n) return 0;
                        return parseFloat(n[0].replace(/\\./g, '').replace(',', '.')) * mult;
                    }

                    let likes = 0;
                    const likedByLink = document.querySelector("a[href*='/liked_by/']");
                    if (likedByLink) { const v = limparNumero(likedByLink.innerText); if (v > 0) likes = v; }

                    if (likes === 0) {
                        for (const sec of document.querySelectorAll("section")) {
                            const txt = (sec.innerText || "").toLowerCase();
                            if (txt.includes("curtir") || txt.includes("compartilhar")) {
                                const m = txt.match(/([\\d.,]+\\s*[km]?)\\s*curtida/i);
                                if (m) { likes = limparNumero(m[1]); break; }
                            }
                        }
                    }

                    if (likes === 0) {
                        const metaOg = document.querySelector("meta[property='og:description']")?.content || "";
                        if (metaOg) {
                            const m = metaOg.match(/([\\d.,]+\\s*(?:mil|k|m)?)\\s*(?:curtida|like)/i);
                            if (m) likes = limparNumero(m[1]);
                        }
                    }

                    if (likes === 0) {
                        document.querySelectorAll("[aria-label]").forEach(el => {
                            const aria = (el.getAttribute("aria-label") || "").toLowerCase();
                            if (aria.includes("curtida") || aria.includes("like")) {
                                const v = limparNumero(aria); if (v > likes) likes = v;
                            }
                        });
                    }

                    if (likes === 0) {
                        document.querySelectorAll("span, a").forEach(el => {
                            const txt = (el.innerText || "").toLowerCase().trim();
                            if (txt.includes("curtida") || txt.includes("like")) {
                                const v = limparNumero(txt); if (v > likes) likes = v;
                            }
                        });
                    }

                    let comentarios = 0;
                    const metaDesc = document.querySelector("meta[property='og:description']")?.content || "";
                    if (metaDesc) {
                        const mEn = metaDesc.match(/([\\d.,]+\\s*(?:mil|k|m)?)\\s*comments?/i);
                        if (mEn) comentarios = limparNumero(mEn[1]);
                        if (comentarios === 0) {
                            const mPt = metaDesc.match(/([\\d.,]+\\s*(?:mil|k|m)?)\\s*comentário/i);
                            if (mPt) comentarios = limparNumero(mPt[1]);
                        }
                    }
                    if (comentarios === 0) {
                        const commLink = document.querySelector("a[href*='/comments/']");
                        if (commLink) { const v = limparNumero(commLink.innerText); if (v > 0) comentarios = v; }
                    }
                    if (comentarios === 0) {
                        document.querySelectorAll("span, a, [aria-label]").forEach(el => {
                            const src = (el.getAttribute("aria-label") || el.innerText || "").toLowerCase().trim();
                            if (src.includes("comentário") || src.includes("comment")) {
                                const v = limparNumero(src); if (v > comentarios) comentarios = v;
                            }
                        });
                    }

                    let views = 0;
                    document.querySelectorAll("span, [aria-label]").forEach(el => {
                        const src = (el.getAttribute("aria-label") || el.innerText || "").toLowerCase().trim();
                        if (src.includes("visualiza") || src.includes("reprodução") ||
                            src.includes("view")      || src.includes("plays")) {
                            const v = limparNumero(src); if (v > views) views = v;
                        }
                    });

                    const caption = document.querySelector("meta[property='og:description']")?.content || "";
                    const thumb   = document.querySelector("meta[property='og:image']")?.content || "";

                    return { likes, comentarios, views, caption, thumb };
                }
                """)

                caption = post.get("caption", "")

                likes_caption = corrigir_likes_pela_caption(caption)
                if likes_caption > post["likes"]:
                    print(f"  [FIX:{self.username}] likes: {post['likes']} → {likes_caption}")
                    post["likes"] = likes_caption

                comentarios_caption = corrigir_comentarios_pela_caption(caption)
                if comentarios_caption > post["comentarios"]:
                    print(f"  [FIX:{self.username}] comentarios: {post['comentarios']} → {comentarios_caption}")
                    post["comentarios"] = comentarios_caption

                post["url"]  = full
                post["tipo"] = "reel" if "/reel/" in full else "post"
                posts.append(post)
                print(f"  [{self.username}] likes={post['likes']} comentarios={post['comentarios']} views={post['views']}")

            except Exception as e:
                print(f"ERRO POST [{self.username}]:", e)
                continue

        total_likes    = sum(p["likes"]       for p in posts)
        total_comments = sum(p["comentarios"] for p in posts)
        total_views    = sum(p["views"]        for p in posts)
        media_likes    = (total_likes / len(posts)) if posts else 0

        engajamento = 0
        if perfil["seguidores"] > 0:
            engajamento = ((total_likes + total_comments) / perfil["seguidores"]) * 100

        melhor_post = max(posts, key=lambda p: p["likes"] + p["comentarios"] + p["views"]) if posts else None

        return {
            "rede": "instagram",
            "conta_usada": self.username,   # NOVO: indica qual conta foi usada
            "perfil": perfil,
            "estatisticas": {
                "total_likes":    total_likes,
                "total_comments": total_comments,
                "total_views":    total_views,
                "media_likes":    round(media_likes, 2),
                "engajamento":    round(engajamento, 2)
            },
            "melhor_post": melhor_post,
            "posts": posts
        }

    # =====================================================
    # YOUTUBE — interno (inalterado)
    # =====================================================

    def _scrape_youtube(self, url):
        if "/videos" not in url:
            url = url.rstrip("/") + "/videos"
        self._page.goto(url, wait_until="networkidle")
        time.sleep(3)
        self._human_scroll()
        return self._page.evaluate("""
        () => {
            const videos = [...document.querySelectorAll('ytd-rich-item-renderer')]
            .slice(0, 10)
            .map(v => {
                const spans = v.querySelectorAll('#metadata-line span');
                return {
                    title: v.querySelector('#video-title')?.innerText || '',
                    views: spans[0]?.innerText || '0',
                    data:  spans[1]?.innerText || '',
                    thumb: v.querySelector('img')?.src || '',
                    link:  v.querySelector('a#video-title-link')?.href || ''
                };
            });
            return { rede: 'youtube', titulo: document.title, videos };
        }
        """)

    # =====================================================
    # GITHUB — interno (inalterado)
    # =====================================================

    def _scrape_github(self, url):
        self._page.goto(url, wait_until="networkidle")
        time.sleep(2)
        return self._page.evaluate("""
        () => {
            const repos = [...document.querySelectorAll('article')]
            .slice(0, 10)
            .map(el => ({
                nome:  el.querySelector('h3 a')?.innerText || '',
                desc:  el.querySelector('p')?.innerText || '',
                stars: el.querySelector('#repo-stars-counter-star')?.innerText || '0',
                link:  el.querySelector('h3 a')?.href || ''
            }));
            return { rede: 'github', titulo: document.title, repos };
        }
        """)

    # =====================================================
    # GENÉRICO — interno (inalterado)
    # =====================================================

    def _scrape_generico(self, url):
        self._page.goto(url, wait_until="domcontentloaded")
        time.sleep(2)
        return self._page.evaluate("""
        () => ({
            rede:   'web',
            titulo: document.title || '',
            texto:  document.body.innerText.slice(0, 3000),
            h1:     [...document.querySelectorAll('h1')].map(e => e.innerText)
        })
        """)

    # =====================================================
    # CENTRAL DO BOT
    # =====================================================

    def scrape_url(self, url):
        rede = detectar_rede(url)
        if rede == "instagram":
            return self._run(lambda: self._scrape_instagram(url))
        elif rede == "youtube":
            return self._run(lambda: self._scrape_youtube(url))
        elif rede == "github":
            return self._run(lambda: self._scrape_github(url))
        return self._run(lambda: self._scrape_generico(url))

    # =====================================================
    # CLOSE
    # =====================================================

    def close(self):
        def _close():
            try:
                self._context.close()
                self._pw.stop()
            except Exception as e:
                print(f"[BOT:{self.username}] erro ao fechar: {e}")
        self._run(_close)


# =========================================================
# POOL DE BOTS — substitui o singleton _bot_instance
# =========================================================
#
# _bots é um dict { username: Bot }
# Lock protege criação/remoção concorrente de bots
#
# NOVO vs versão anterior:
#   Antes: _bot_instance = None (um único bot)
#   Agora: _bots = {}           (um bot por conta)
#
# =========================================================

_bots      : dict[str, Bot] = {}
_bots_lock : threading.Lock = threading.Lock()


def get_or_create_bot(conta: dict) -> Bot:
    """
    Retorna o Bot da conta se já existir no cache.
    Caso contrário, cria um novo Bot e o armazena.

    Isso permite que novas contas cadastradas pelo admin
    sejam usadas imediatamente, sem reiniciar o servidor.
    """
    username = conta["username"]

    with _bots_lock:
        if username not in _bots:
            print(f"[POOL] criando Bot para conta: {username}")
            _bots[username] = Bot(conta)
        return _bots[username]


def remover_bot(username: str) -> None:
    """
    Remove um bot do pool (ex: conta banida ou deletada).
    Fecha o browser associado.
    """
    with _bots_lock:
        if username in _bots:
            try:
                _bots[username].close()
            except Exception as e:
                print(f"[POOL] erro ao fechar bot {username}: {e}")
            del _bots[username]
            print(f"[POOL] bot removido: {username}")


# =========================================================
# SCRAPE_URL — ponto de entrada público
# =========================================================
#
# FLUXO COMPLETO:
#   1. Detecta a rede da URL
#   2. Se for Instagram:
#      a. Pega uma conta livre do pool (account_manager)
#      b. Recupera/cria o Bot dessa conta
#      c. Executa o scrape
#      d. Libera a conta no account_manager
#   3. Se não for Instagram:
#      a. Usa qualquer bot disponível (ou cria um)
#      b. Sem necessidade de gerenciar pool para não-IG
#
# =========================================================

def scrape_url(url: str) -> dict:
    """
    Ponto de entrada único — compatível com a API anterior.
    Chamadas externas continuam usando scrape_url(url) sem mudança.
    """
    rede = detectar_rede(url)

    if rede == "instagram":
        return _scrape_instagram_com_pool(url)
    else:
        return _scrape_generico_com_pool(url, rede)


def _scrape_instagram_com_pool(url: str) -> dict:
    """
    Gerencia o ciclo completo de uma requisição Instagram:
    pega conta → scrape → libera conta.

    Se não houver contas disponíveis, lança exceção clara.
    """
    conta = obter_conta_livre()

    if conta is None:
        raise Exception(
            "SEM_CONTAS_DISPONIVEIS: todas as contas estão ocupadas ou banidas. "
            "Aguarde ou cadastre novas contas no painel admin."
        )

    username = conta["username"]
    print(f"[POOL] usando conta: {username}")

    try:
        bot    = get_or_create_bot(conta)
        result = bot.scrape_url(url)
        return result

    except TimeoutError as e:
        # CORRIGIDO: captura timeout do _run antes que o Gunicorn mate o worker
        print(f"[POOL] timeout na conta {username}: {e}")
        raise Exception(f"TIMEOUT_SCRAPE: {e}")

    except Exception as e:
        erro_str = str(e)

        # Sessão expirou — bot já marcou como banida internamente
        if "SESSAO_EXPIRADA" in erro_str:
            print(f"[POOL] conta {username} com sessão expirada, removendo do pool")
            remover_bot(username)

        raise

    finally:
        # Sempre libera a conta, mesmo que o scrape tenha falhado
        # (exceto se foi banida — status já foi alterado pelo bot)
        contas = __import__("account_manager").carregar_contas()
        conta_atual = next((c for c in contas if c["username"] == username), None)
        if conta_atual and conta_atual.get("status") != "banida":
            liberar_conta(username)
            print(f"[POOL] conta liberada: {username}")


def _scrape_generico_com_pool(url: str, rede: str) -> dict:
    """
    Para YouTube, GitHub e web genérica:
    usa a primeira conta disponível como base do browser.
    Se não houver nenhuma conta cadastrada, cria um bot
    sem sessão (anônimo) para esses sites.
    """
    contas = carregar_contas()

    if contas:
        # Usa a primeira conta como base (não precisa de login para YT/GH)
        conta = contas[0]
        bot   = get_or_create_bot(conta)
    else:
        # Fallback: bot anônimo sem sessão Instagram
        # Cria uma conta fictícia apenas para iniciar o browser
        conta_anonima = {
            "username":    "_anonimo",
            "profile_dir": "ig_profile_anonimo"
        }
        bot = get_or_create_bot(conta_anonima)

    return bot.scrape_url(url)