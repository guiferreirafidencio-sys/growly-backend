# referencias.py
# =========================================================
# BUSCA DE REFERÊNCIAS NO INSTAGRAM POR HASHTAG
# Usado para enriquecer as ideias de conteúdo com exemplos reais
# =========================================================

from flask import Blueprint, jsonify, request
from account_manager import obter_conta_livre, liberar_conta
from bot import get_or_create_bot
import time
import random
import re

referencias_bp = Blueprint("referencias", __name__)

# =========================================================
# SCRAPING DE HASHTAG
# =========================================================

def scrape_hashtag(tag: str, limite: int = 4):
    """
    Busca posts recentes de uma hashtag no Instagram.
    Retorna lista de { url, thumb, caption, likes, views }
    """
    tag = tag.lstrip("#").strip().lower()
    url = f"https://www.instagram.com/explore/tags/{tag}/"

    print(f"[REF] buscando hashtag: #{tag}")

    conta = obter_conta_livre()

    if not conta:
        raise Exception("Nenhuma conta disponível")

    bot = get_or_create_bot(conta)
    page = bot._page

    page.goto(url, wait_until="networkidle")
    time.sleep(random.uniform(3, 5))

    if "/accounts/login" in page.url:
        raise Exception("Instagram pediu login.")

    # scroll leve para carregar mais posts
    for _ in range(2):
        page.mouse.wheel(0, random.randint(1000, 2000))
        time.sleep(random.uniform(1, 2))

    # coleta links dos posts
    hrefs = page.eval_on_selector_all(
        "a[href*='/p/'], a[href*='/reel/']",
        """els => [...new Set(
            els.map(e => e.getAttribute('href'))
               .filter(h => h && (h.includes('/p/') || h.includes('/reel/')))
        )]"""
    )

    links = [
        "https://www.instagram.com" + h
        for h in hrefs[:limite]
    ]

    print(f"[REF] #{tag} → {len(links)} posts encontrados")
   
    posts = []
    for full_url in links:
        try:
            post = _scrape_post_rapido(page, full_url)
            if post:
                posts.append(post)
        except Exception as e:
            print(f"[REF] erro no post {full_url}: {e}")
            continue
        finally:
            liberar_conta(conta["username"])
    return posts


def _scrape_post_rapido(page, url: str):
    """
    Scraping rápido de um post: thumb, caption resumida, likes, views.
    Não precisa de dados completos — só o suficiente para referência.
    """
    print(f"[REF] post: {url}")
    page.goto(url, wait_until="networkidle")
    time.sleep(random.uniform(1.5, 3))

    dados = page.evaluate("""
    () => {
        function limpar(txt) {
            if (!txt) return 0;
            txt = txt.toLowerCase().trim();
            let mult = 1;
            if (txt.includes('k')) mult = 1000;
            if (txt.includes('m')) mult = 1000000;
            const n = txt.match(/[\\d.,]+/);
            if (!n) return 0;
            return parseFloat(n[0].replace(/\\./g,'').replace(',','.')) * mult;
        }

        const meta    = document.querySelector("meta[property='og:description']")?.content || "";
        const thumb   = document.querySelector("meta[property='og:image']")?.content       || "";
        const caption = meta;

        // likes
        let likes = 0;
        r"const mLikes = meta.match(/([\d.,]+\s*[km]?)\s*(curtida|like)/i);"
        if (mLikes) likes = limpar(mLikes[1]);

        // views
        let views = 0;
        document.querySelectorAll("span, [aria-label]").forEach(el => {
            const src = (el.getAttribute("aria-label") || el.innerText || "").toLowerCase();
            if (src.includes("visualiza") || src.includes("view") || src.includes("plays")) {
                const v = limpar(src);
                if (v > views) views = v;
            }
        });

        return { thumb, caption, likes, views };
    }
    """)

    if not dados or not dados.get("thumb"):
        return None

    # resume a caption para exibição
    caption_raw = dados.get("caption", "")
    caption_curta = _resumir_caption(caption_raw)

    tipo = "reel" if "/reel/" in url else "post"

    return {
        "url":     url,
        "tipo":    tipo,
        "thumb":   dados.get("thumb", ""),
        "caption": caption_curta,
        "likes":   int(dados.get("likes", 0)),
        "views":   int(dados.get("views", 0)),
    }


def _resumir_caption(texto: str, max_palavras: int = 12) -> str:
    """
    Extrai as primeiras palavras reais da caption,
    ignorando contagens de likes/comentários que o Instagram
    coloca no início do og:description.
    """
    if not texto:
        return ""

    # Remove o prefixo "154 likes, 76 comments - " que o Instagram injeta
    texto = re.sub(
        r"^\d[\d.,]*\s*[km]?\s*(curtida|like|comment|comentário)[^-]*-\s*",
        "",
        texto,
        flags=re.IGNORECASE
    ).strip()

    # Remove emojis do início
    texto = re.sub(r"^[\U00010000-\U0010ffff\U0001F300-\U0001F9FF\s]+", "", texto).strip()

    palavras = texto.split()[:max_palavras]
    resumo   = " ".join(palavras)
    return resumo + ("…" if len(texto.split()) > max_palavras else "")


# =========================================================
# ROTA
# =========================================================

@referencias_bp.route("/api/referencias", methods=["POST"])
def api_referencias():
    """
    Recebe uma lista de hashtags e retorna posts de referência
    para cada uma.

    Body esperado:
    {
        "hashtags": [
            { "ideia": "Série de looks GRWM", "tags": ["grwm", "lookdodia"] },
            { "ideia": "Reviews de produtos",  "tags": ["reviewdemoda", "unboxing"] }
        ]
    }

    Retorna:
    {
        "ok": true,
        "referencias": [
            {
                "ideia": "Série de looks GRWM",
                "posts": [
                    { "url": "...", "thumb": "...", "caption": "...", "likes": 0, "views": 0 }
                ]
            }
        ]
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"ok": False, "erro": "JSON obrigatório"}), 400

        hashtags = data.get("hashtags", [])
        if not hashtags:
            return jsonify({"ok": False, "erro": "lista de hashtags vazia"}), 400

        resultado = []

        for item in hashtags:
            ideia = item.get("ideia", "")
            tags  = item.get("tags", [])

            posts_encontrados = []

            for tag in tags[:2]:   # máx 2 hashtags por ideia para não demorar demais
                try:
                    posts = scrape_hashtag(tag, limite=2)
                    posts_encontrados.extend(posts)
                    if len(posts_encontrados) >= 3:
                        break
                except Exception as e:
                    print(f"[REF] erro na tag #{tag}: {e}")
                    continue

            resultado.append({
                "ideia": ideia,
                "posts": posts_encontrados[:3]   # máx 3 referências por ideia
            })

        return jsonify({"ok": True, "referencias": resultado})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"ok": False, "erro": str(e)}), 500