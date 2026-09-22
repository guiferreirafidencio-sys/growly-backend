# bot.py
# =========================================================
# BOT DE SCRAPING — otimizado para Railway (baixa RAM)
#
# Arquitetura:
#   - Sem browser persistente em memória
#   - Perfil: abre browser, coleta links, fecha
#   - Posts: abre e fecha browser para CADA post (evita crash de RAM)
#   - Sem Semaphore global: o limite é o número de contas livres
#   - liberar_conta() chamado exatamente uma vez por caminho
#   - Sem locks aninhados
# =========================================================

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from pathlib import Path
import os
import time
import random
import re
import gc
import threading

from app.account_manager import (
    carregar_contas,
    obter_conta_livre,
    liberar_conta,
    marcar_banida,
    caminho_sessao,
    relogar_conta_em_background,
)
from app.storage.logging import get_logger

logger = get_logger("scraper")


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

FILA_TIMEOUT   = 120
MAX_TENTATIVAS = 3
_sem_browsers  = threading.Semaphore(1)

RELOGIN_WAIT = 20


# =========================================================
# LOG
# =========================================================

def log(tag: str, msg: str):
    import datetime
    ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}][{tag}] {msg}", flush=True)
    logger.info("[%s] %s", tag, msg)


# =========================================================
# DETECÇÃO DE REDE
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


# =========================================================
# HELPERS DE NÚMERO
# =========================================================

def corrigir_likes_pela_caption(caption):
    if not caption:
        return 0
    m = re.search(r'([\d][0-9,\.]*)\s*(mil|k|m)?\s*like', caption, re.IGNORECASE)
    if not m:
        return 0
    num_str = m.group(1).replace(',', '')
    try:
        num = float(num_str)
    except:
        return 0
    mult = {"mil": 1000, "k": 1000, "m": 1_000_000}.get(
        (m.group(2) or "").lower(), 1
    )
    return int(num * mult)


def corrigir_comentarios_pela_caption(caption):
    if not caption:
        return 0
    m = re.search(r'([\d][0-9,\.]*)\s*(mil|k|m)?\s*comment', caption, re.IGNORECASE)
    if not m:
        m = re.search(r'([\d][0-9,\.]*)\s*(mil|k|m)?\s*comentário', caption, re.IGNORECASE)
    if not m:
        return 0
    num_str = m.group(1).replace(',', '')
    try:
        num = float(num_str)
    except:
        return 0
    mult = {"mil": 1000, "k": 1000, "m": 1_000_000}.get(
        (m.group(2) or "").lower(), 1
    )
    return int(num * mult)


# =========================================================
# ERROS PÚBLICOS
# =========================================================

class ErroScrapePublico(Exception):
    pass


def _erro_publico(codigo: str) -> ErroScrapePublico:
    mensagens = {
        "PERFIL_PRIVADO":        "Este perfil é privado e não pode ser analisado.",
        "PERFIL_NAO_ENCONTRADO": "Perfil não encontrado. Verifique o link e tente novamente.",
        "SEM_CONTAS":            "Serviço temporariamente indisponível. Tente novamente em alguns minutos.",
        "TIMEOUT":               "A análise demorou mais que o esperado. Tente novamente.",
        "FILA_CHEIA":            "Muitas análises em andamento. Tente novamente em instantes.",
        "GENERICO":              "Não foi possível analisar este perfil agora. Tente novamente.",
    }
    return ErroScrapePublico(mensagens.get(codigo, mensagens["GENERICO"]))


# =========================================================
# EXCEÇÕES INTERNAS
# =========================================================

class _SessaoExpirada(Exception):
    pass


class _ErroNegocio(Exception):
    def __init__(self, codigo: str):
        self.codigo = codigo
        super().__init__(codigo)


def _is_crash(e: Exception) -> bool:
    nome = type(e).__name__
    msg  = str(e)
    return (
        "TargetClosedError"    in nome
        or "TargetClosedError" in msg
        or "Target page, context or browser has been closed" in msg
        or "Browser has been closed" in msg
        or "Connection closed"       in msg
        or "browser has been closed" in msg
        or "Page crashed"            in msg
    )


# =========================================================
# STEALTH
# =========================================================

def _aplicar_stealth(page):
    page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver',  { get: () => undefined });
    Object.defineProperty(navigator, 'languages',  { get: () => ['pt-BR', 'pt', 'en-US'] });
    Object.defineProperty(navigator, 'plugins',    { get: () => [1,2,3,4,5] });
    window.chrome = { runtime: {} };
    """)


# =========================================================
# ABRIR / FECHAR BROWSER
# =========================================================

def _abrir_browser(session_path: str):
    from pathlib import Path
    Path(session_path).mkdir(parents=True, exist_ok=True)

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=session_path,
        headless=True,
        user_agent=UA,
        viewport={"width": 1400, "height": 900},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-setuid-sandbox",
            "--no-zygote",
            "--single-process",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--disable-translate",
            "--hide-scrollbars",
            "--mute-audio",
            "--no-first-run",
        ]
    )
    page = context.new_page()
    page.set_default_timeout(60_000)
    _aplicar_stealth(page)
    return pw, context, page


def _fechar_browser(pw, context):
    try:
        context.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass
    # Limpa cache do Chromium após cada uso para manter volume leve
    try:
        import shutil
        pastas_cache = [
            "Cache", "Code Cache", "GPUCache", "DawnCache",
            "Service Worker", "CacheStorage", "blob_storage",
            "Network Persistent State",
        ]
        from app.storage.paths import SESSIONS_DIR
        sessions_dir = SESSIONS_DIR
        if sessions_dir.exists():
            for profile in sessions_dir.iterdir():
                if not profile.is_dir():
                    continue
                for sub in profile.rglob("*"):
                    if sub.name in pastas_cache and sub.is_dir():
                        shutil.rmtree(sub, ignore_errors=True)
    except Exception:
        pass
    gc.collect()


# =========================================================
# SCROLL
# =========================================================

def _scroll_carregar_posts(page, username: str, quantidade_alvo: int = 15):
    log(f"SCROLL:{username}", f"carregando posts (alvo: {quantidade_alvo})")
    sem_novos       = 0
    ultima_contagem = 0

    for rodada in range(25):
        links = page.eval_on_selector_all(
            "a[href*='/p/'], a[href*='/reel/']",
            "els => [...new Set(els.map(e => e.getAttribute('href')))].filter(Boolean).length"
        )
        log(f"SCROLL:{username}", f"rodada {rodada+1}: {links} links")

        if links >= quantidade_alvo:
            break

        if links == ultima_contagem:
            sem_novos += 1
            if sem_novos >= 4:
                log(f"SCROLL:{username}", f"sem novos posts — parando com {links}")
                break
        else:
            sem_novos = 0

        ultima_contagem = links
        page.mouse.wheel(0, random.randint(2000, 4000))
        time.sleep(random.uniform(1.5, 2.5))

        if rodada % 5 == 4:
            time.sleep(random.uniform(2, 3))


# =========================================================
# JS COMPARTILHADO
# =========================================================

_JS_LIMPAR_NUMERO = """
function limparNumero(txt) {
    if (!txt) return 0;
    txt = txt.trim();
    let mult = 1;
    // captura sufixo M/m/K/k/mil colado ou separado do número
    if (/mil/i.test(txt))                   mult = 1000;
    else if (/[0-9]\s*k/i.test(txt))        mult = 1000;
    else if (/[0-9]\s*m(?!il)/i.test(txt))  mult = 1000000;
    const n = txt.match(/[\d.,]+/);
    if (!n) return 0;
    return parseFloat(n[0].replace(/\./g,'').replace(',','.')) * mult;
}
"""


# =========================================================
# COLETAR PERFIL + LINKS (fase 1 — abre e fecha browser)
# =========================================================

def _coletar_perfil_e_links(url: str, conta: dict) -> tuple[dict, list[str]]:
    """
    Abre o browser, coleta dados do perfil e lista de links dos posts,
    fecha o browser e retorna. Não visita posts individuais.
    """
    username     = conta["username"]
    session_path = str(caminho_sessao(conta["profile_dir"]))

    log(f"IG:{username}", f"abrindo browser para: {url}")
    pw, context, page = _abrir_browser(session_path)

    try:
        page.goto(url, wait_until="networkidle")
        time.sleep(random.uniform(4, 6))

        url_atual = page.url
        titulo    = page.title()
        log(f"IG:{username}", f"URL atual: {url_atual} | título: {titulo}")

        if "/accounts/login" in url_atual:
            log(f"IG:{username}", "SESSÃO EXPIRADA — redirecionou para login")
            raise _SessaoExpirada()

        if "Page Not Found" in titulo or "Página não encontrada" in titulo:
            raise _ErroNegocio("PERFIL_NAO_ENCONTRADO")

        eh_privado = page.evaluate("""
        () => {
            const desc = document.querySelector("meta[property='og:description']")?.content || "";
            if (/this account is private/i.test(desc)) return true;
            const body = document.body?.innerText || "";
            if (/esta conta é privada|this account is private/i.test(body)) return true;
            return false;
        }
        """)

        if eh_privado:
            raise _ErroNegocio("PERFIL_PRIVADO")

        _scroll_carregar_posts(page, username, quantidade_alvo=15)

        perfil = page.evaluate(f"""
        () => {{
            {_JS_LIMPAR_NUMERO}
            let seguidores = 0, seguindo = 0, publicacoes = 0;
            const ogDesc = document.querySelector("meta[property='og:description']")?.content || "";
            if (ogDesc) {{
                const mSeg  = ogDesc.match(/([\d.,]+\s*(?:mil|k|m)?)\s*(?:Followers|Seguidores)/i);
                const mSeg2 = ogDesc.match(/([\d.,]+\s*(?:mil|k|m)?)\s*(?:Following|Seguindo)/i);
                const mPub  = ogDesc.match(/([\d.,]+\s*(?:mil|k|m)?)\s*(?:Posts?|Publicações)/i);
                if (mSeg)  seguidores  = limparNumero(mSeg[1]);
                if (mSeg2) seguindo    = limparNumero(mSeg2[1]);
                if (mPub)  publicacoes = limparNumero(mPub[1]);
            }}
            if (seguidores === 0) {{
                document.querySelectorAll("a, span, li").forEach(el => {{
                    const aria  = (el.getAttribute("aria-label") || "").toLowerCase();
                    const title = (el.getAttribute("title")      || "").toLowerCase();
                    if (aria.includes("seguidores") || aria.includes("followers") ||
                        title.includes("seguidores") || title.includes("followers")) {{
                        const v = limparNumero(aria || title); if (v > seguidores) seguidores = v;
                    }}
                    if (aria.includes("seguindo") || aria.includes("following") ||
                        title.includes("seguindo") || title.includes("following")) {{
                        const v = limparNumero(aria || title); if (v > seguindo) seguindo = v;
                    }}
                    if (aria.includes("publicações") || aria.includes("posts") ||
                        title.includes("publicações") || title.includes("posts")) {{
                        const v = limparNumero(aria || title); if (v > publicacoes) publicacoes = v;
                    }}
                }});
            }}
            return {{
                seguidores:  isNaN(seguidores)  ? 0 : seguidores,
                seguindo:    isNaN(seguindo)     ? 0 : seguindo,
                publicacoes: isNaN(publicacoes)  ? 0 : publicacoes,
                bio:    document.querySelector("meta[property='og:description']")?.content || "",
                titulo: document.title || ""
            }};
        }}
        """)

        for campo in ("seguidores", "seguindo", "publicacoes"):
            v = perfil.get(campo, 0)
            perfil[campo] = 0 if (v is None or (isinstance(v, float) and v != v)) else int(v)

        log(f"IG:{username}", f"perfil: seg={perfil['seguidores']} pub={perfil['publicacoes']}")

        hrefs = page.eval_on_selector_all(
            "a[href*='/p/'], a[href*='/reel/']",
            """els => [...new Set(
                els.map(e => e.getAttribute('href'))
                   .filter(h => h && (h.includes('/p/') || h.includes('/reel/')))
            )]"""
        )
        username_alvo = url.rstrip("/").split("/")[-1].lower()
        links_posts   = [
            "https://www.instagram.com" + h for h in hrefs
            if h.lower().startswith(f"/{username_alvo}/")
        ]
        log(f"IG:{username}", f"{len(links_posts)} posts de @{username_alvo}")

        if perfil.get("publicacoes", 0) > 0 and len(links_posts) == 0:
            raise _ErroNegocio("PERFIL_PRIVADO")

        return perfil, links_posts

    finally:
        log(f"IG:{username}", "fechando browser (fase perfil)")
        _fechar_browser(pw, context)


# =========================================================
# COLETAR UM ÚNICO POST (abre e fecha browser)
# =========================================================

def _coletar_post(full_url: str, username_alvo: str, conta: dict) -> dict | None:
    """
    Abre um browser apenas para um post, coleta dados e fecha.
    Retorna None se o post deve ser pulado.
    Lança _SessaoExpirada se sessão expirou.
    """
    username     = conta["username"]
    session_path = str(caminho_sessao(conta["profile_dir"]))

    pw, context, page = _abrir_browser(session_path)
    try:
        page.goto(full_url, wait_until="domcontentloaded")
        time.sleep(random.uniform(1, 2))

        post_url_atual = page.url
        if "/accounts/login" in post_url_atual:
            raise _SessaoExpirada()

        # Verifica se o post pertence ao dono certo
        partes = post_url_atual.rstrip("/").split("/")
        dominio_atual = partes[3].lower() if len(partes) > 3 else ""
        if dominio_atual and dominio_atual != username_alvo:
            log(f"IG:{username}", f"post de @{dominio_atual} — pulando")
            return None

        post = page.evaluate(f"""
        () => {{
            {_JS_LIMPAR_NUMERO}
            let likes = 0;
            const likedByLink = document.querySelector("a[href*='/liked_by/']");
            if (likedByLink) {{ const v = limparNumero(likedByLink.innerText); if (v > 0) likes = v; }}
            if (likes === 0) {{
                for (const sec of document.querySelectorAll("section")) {{
                    const txt = (sec.innerText || "").toLowerCase();
                    if (txt.includes("curtir") || txt.includes("compartilhar")) {{
                        const m = txt.match(/([\d.,]+\s*[km]?)\s*curtida/i);
                        if (m) {{ likes = limparNumero(m[1]); break; }}
                    }}
                }}
            }}
            if (likes === 0) {{
                const metaOg = document.querySelector("meta[property='og:description']")?.content || "";
                if (metaOg) {{
                    const m = metaOg.match(/([\d.,]+\s*(?:mil|k|m)?)\s*(?:curtida|like)/i);
                    if (m) likes = limparNumero(m[1]);
                }}
            }}
            if (likes === 0) {{
                document.querySelectorAll("[aria-label]").forEach(el => {{
                    const aria = (el.getAttribute("aria-label") || "").toLowerCase();
                    if (aria.includes("curtida") || aria.includes("like")) {{
                        const v = limparNumero(aria); if (v > likes) likes = v;
                    }}
                }});
            }}
            let comentarios = 0;
            const metaDesc = document.querySelector("meta[property='og:description']")?.content || "";
            if (metaDesc) {{
                const mEn = metaDesc.match(/([\d.,]+\s*(?:mil|k|m)?)\s*comments?/i);
                if (mEn) comentarios = limparNumero(mEn[1]);
                if (comentarios === 0) {{
                    const mPt = metaDesc.match(/([\d.,]+\s*(?:mil|k|m)?)\s*comentário/i);
                    if (mPt) comentarios = limparNumero(mPt[1]);
                }}
            }}
            if (comentarios === 0) {{
                document.querySelectorAll("span, a, [aria-label]").forEach(el => {{
                    const src = (el.getAttribute("aria-label") || el.innerText || "").toLowerCase().trim();
                    if (src.includes("comentário") || src.includes("comment")) {{
                        const v = limparNumero(src); if (v > comentarios) comentarios = v;
                    }}
                }});
            }}
            let views = 0;
            document.querySelectorAll("span, [aria-label]").forEach(el => {{
                const src = (el.getAttribute("aria-label") || el.innerText || "").toLowerCase().trim();
                if (src.includes("visualiza") || src.includes("reprodução") ||
                    src.includes("view")      || src.includes("plays")) {{
                    const v = limparNumero(src); if (v > views) views = v;
                }}
            }});
            const caption = document.querySelector("meta[property='og:description']")?.content || "";
            const thumb   = document.querySelector("meta[property='og:image']")?.content || "";
            return {{ likes, comentarios, views, caption, thumb }};
        }}
        """)

        return post

    finally:
        _fechar_browser(pw, context)


# =========================================================
# SCRAPE INSTAGRAM COMPLETO
# =========================================================

def _scrape_instagram_com_conta(url: str, conta: dict) -> dict:
    username      = conta["username"]
    username_alvo = url.rstrip("/").split("/")[-1].lower()

    # FASE 1: coleta perfil e lista de links (fecha browser ao terminar)
    perfil, links_posts = _coletar_perfil_e_links(url, conta)

    # FASE 2: visita cada post abrindo e fechando o browser individualmente
    posts = []
    for i, full in enumerate(links_posts[:15]):
        log(f"IG:{username}", f"post {i+1}/{min(len(links_posts), 15)}: {full}")
        try:
            post = _coletar_post(full, username_alvo, conta)
            if post is None:
                continue

            caption = post.get("caption", "")
            likes_caption = corrigir_likes_pela_caption(caption)
            if likes_caption > post["likes"]:
                post["likes"] = likes_caption

            comentarios_caption = corrigir_comentarios_pela_caption(caption)
            if comentarios_caption > post["comentarios"]:
                post["comentarios"] = comentarios_caption

            post["url"]  = full
            post["tipo"] = "reel" if "/reel/" in full else "post"
            posts.append(post)
            log(f"IG:{username}", f"OK — likes={post['likes']} com={post['comentarios']} views={post['views']}")

        except _SessaoExpirada:
            raise

        except Exception as e:
            if _is_crash(e):
                log(f"IG:{username}", f"crash no post {i+1} — pulando e continuando")
                gc.collect()
                time.sleep(2)
                continue
            log(f"IG:{username}", f"erro no post {full}: {e}")
            continue

    # Calcula estatísticas
    total_likes    = sum(p["likes"]       for p in posts)
    total_comments = sum(p["comentarios"] for p in posts)
    total_views    = sum(p["views"]        for p in posts)
    media_likes    = (total_likes / len(posts)) if posts else 0
    engajamento    = 0
    if perfil["seguidores"] > 0:
        engajamento = ((total_likes + total_comments) / perfil["seguidores"]) * 100

    melhor_post = max(
        posts, key=lambda p: p["likes"] + p["comentarios"] + p["views"]
    ) if posts else None

    log(f"IG:{username}", f"RESULTADO: {len(posts)} posts | eng={engajamento:.2f}%")

    return {
        "rede":         "instagram",
        "conta_usada":  username,
        "perfil":       perfil,
        "estatisticas": {
            "total_likes":    total_likes,
            "total_comments": total_comments,
            "total_views":    total_views,
            "media_likes":    round(media_likes, 2),
            "engajamento":    round(engajamento, 2),
        },
        "melhor_post": melhor_post,
        "posts":        posts,
    }


# =========================================================
# SCRAPE YOUTUBE
# =========================================================

def _scrape_youtube_com_conta(url: str, conta: dict) -> dict:
    username     = conta["username"]
    session_path = str(caminho_sessao(conta["profile_dir"]))

    if "/videos" not in url:
        url = url.rstrip("/") + "/videos"

    pw, context, page = _abrir_browser(session_path)
    try:
        page.goto(url, wait_until="networkidle")
        time.sleep(3)
        for _ in range(random.randint(3, 6)):
            page.mouse.wheel(0, random.randint(1000, 3000))
            time.sleep(random.uniform(1, 2))

        result = page.evaluate("""
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
        return result
    finally:
        _fechar_browser(pw, context)


# =========================================================
# SCRAPE GITHUB
# =========================================================

def _scrape_github_com_conta(url: str, conta: dict) -> dict:
    username     = conta["username"]
    session_path = str(caminho_sessao(conta["profile_dir"]))

    pw, context, page = _abrir_browser(session_path)
    try:
        page.goto(url, wait_until="networkidle")
        time.sleep(2)
        result = page.evaluate("""
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
        return result
    finally:
        _fechar_browser(pw, context)


# =========================================================
# SCRAPE GENÉRICO
# =========================================================

def _scrape_generico_com_conta(url: str, conta: dict) -> dict:
    session_path = str(caminho_sessao(conta["profile_dir"]))
    pw, context, page = _abrir_browser(session_path)
    try:
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(2)
        return page.evaluate("""
        () => ({
            rede:   'web',
            titulo: document.title || '',
            texto:  document.body.innerText.slice(0, 3000),
            h1:     [...document.querySelectorAll('h1')].map(e => e.innerText)
        })
        """)
    finally:
        _fechar_browser(pw, context)


# =========================================================
# POOL
# =========================================================

def _obter_conta_com_espera() -> dict:
    deadline = time.monotonic() + FILA_TIMEOUT
    while True:
        conta = obter_conta_livre()
        if conta is not None:
            return conta
        restante = deadline - time.monotonic()
        if restante <= 0:
            raise _erro_publico("FILA_CHEIA")
        log("POOL", f"sem conta livre — aguardando 5s (restam {restante:.0f}s)…")
        time.sleep(5)


def _scrape_instagram_com_pool(url: str) -> dict:
    """
    Tenta até MAX_TENTATIVAS contas diferentes.
    Sessão expirada → dispara relogin em background → aguarda 20s → tenta de novo.
    """
    contas_com_sessao_expirada: set[str] = set()

    for tentativa in range(MAX_TENTATIVAS):
        conta    = _obter_conta_com_espera()
        username = conta["username"]

        if username in contas_com_sessao_expirada:
            liberar_conta(username)
            log("POOL", f"conta {username} com sessão expirada — pulando")
            time.sleep(3)
            continue

        log("POOL", f"tentativa {tentativa+1}/{MAX_TENTATIVAS} com {username}")
        log("POOL", "aguardando slot de browser...")

        with _sem_browsers:
            log("POOL", f"slot obtido — iniciando scrape com {username}")
            try:
                result = _scrape_instagram_com_conta(url, conta)
                liberar_conta(username)
                log("POOL", f"sucesso com {username}")
                return result

            except _SessaoExpirada:
                log("POOL", f"sessão expirada em {username} — disparando relogin")
                contas_com_sessao_expirada.add(username)
                liberar_conta(username)

                agendou = relogar_conta_em_background(username)
                if agendou:
                    log("POOL", f"aguardando relogin de @{username} ({RELOGIN_WAIT}s)...")
                    time.sleep(RELOGIN_WAIT)
                    contas_com_sessao_expirada.discard(username)
                    log("POOL", f"relogin concluído — @{username} disponível novamente")
                else:
                    log("POOL", f"@{username} sem senha salva — faça login manual no painel")

                continue

            except _ErroNegocio as e:
                liberar_conta(username)
                raise _erro_publico(e.codigo)

            except ErroScrapePublico:
                liberar_conta(username)
                raise

            except Exception as e:
                liberar_conta(username)
                if _is_crash(e):
                    log("POOL", f"crash de browser em {username} (RAM) — desistindo")
                else:
                    log("POOL", f"erro inesperado: {type(e).__name__}: {e}")
                raise _erro_publico("GENERICO")

    log("POOL", "todas as tentativas esgotadas")
    raise _erro_publico("GENERICO")


def _scrape_generico_com_pool(url: str, rede: str) -> dict:
    log("POOL", f"scrape genérico ({rede})")
    conta    = _obter_conta_com_espera()
    username = conta["username"]
    try:
        if rede == "youtube":
            result = _scrape_youtube_com_conta(url, conta)
        elif rede == "github":
            result = _scrape_github_com_conta(url, conta)
        else:
            result = _scrape_generico_com_conta(url, conta)
        liberar_conta(username)
        return result
    except Exception as e:
        liberar_conta(username)
        log("POOL", f"erro no scrape genérico: {e}")
        raise _erro_publico("GENERICO")


# =========================================================
# ENTRADA PÚBLICA
# =========================================================

def scrape_url(url: str) -> dict:
    rede = detectar_rede(url)
    log("SCRAPE", f"url={url} rede={rede}")

    if rede == "instagram":
        return _scrape_instagram_com_pool(url)
    else:
        return _scrape_generico_com_pool(url, rede)
