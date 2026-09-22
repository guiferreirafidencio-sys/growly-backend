# analisar.py

from flask import Blueprint, render_template, request, session, jsonify, redirect

import os
import json
import time
import re
import hashlib
import threading
import urllib.parse
import requests as http_requests

from datetime import datetime
from dotenv import load_dotenv
from google import genai

from app.scraper import scrape_url

load_dotenv()

analisar_bp = Blueprint("analisar", __name__)

# ← agora lê até GEMINI_API_15
API_KEYS = [
    k for k in [os.getenv(f"GEMINI_API_{i}") for i in range(1, 16)]
    if k
]

OPENROUTER_KEYS = [
    k for k in [os.getenv(f"OPENROUTER_API_{i}") for i in range(1, 6)]
    if k
]

print(f"[CONFIG] {len(API_KEYS)} chaves Gemini | {len(OPENROUTER_KEYS)} chaves OpenRouter")

_cache_analise = {}
_cache_url     = {}
_cache_lock    = threading.Lock()

# Fila de chaves Gemini
_fila_gemini = None
_fila_lock   = threading.Lock()

def _get_fila_gemini():
    global _fila_gemini
    with _fila_lock:
        if _fila_gemini is None:
            from queue import Queue
            _fila_gemini = Queue()
            for k in API_KEYS:
                _fila_gemini.put(k)
    return _fila_gemini

# ════════════════════════════════════════════════
# OPENROUTER — só modelos :free
# ════════════════════════════════════════════════

OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "qwen/qwen2.5-vl-72b-instruct:free",
]

def gerar_resposta_openrouter(prompt: str):
    if not OPENROUTER_KEYS:
        raise Exception("Nenhuma chave OpenRouter configurada.")

    resultado = {"texto": None, "erro": None}
    evento    = threading.Event()
    lock      = threading.Lock()
    tarefas   = [(key, model) for key in OPENROUTER_KEYS for model in OPENROUTER_MODELS]

    def tentar(key, model):
        if evento.is_set():
            return
        try:
            print(f"[OPENROUTER] tentando {model} (paralelo)")
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://localhost",
                    "X-Title":       "AnalisadorPerfil"
                },
                json={
                    "model":       model,
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  4000,
                    "temperature": 0.7
                },
                timeout=60
            )

            if resp.status_code == 200:
                data  = resp.json()
                texto = data["choices"][0]["message"]["content"]
                with lock:
                    if resultado["texto"] is None:
                        resultado["texto"] = texto
                        print(f"[OPENROUTER] {model} respondeu primeiro ({len(texto)} chars)")
                        evento.set()
            else:
                print(f"[OPENROUTER] erro {resp.status_code} em {model}: {resp.text[:200]}")
                with lock:
                    resultado["erro"] = f"{resp.status_code} em {model}"

        except Exception as e:
            print(f"[OPENROUTER] exceção em {model}: {e}")
            with lock:
                resultado["erro"] = e

        finally:
            vivas = sum(1 for t in threads if t.is_alive())
            if vivas == 0 and resultado["texto"] is None:
                evento.set()

    threads = [
        threading.Thread(target=tentar, args=(key, model), daemon=True)
        for key, model in tarefas
    ]
    for t in threads:
        t.start()

    evento.wait(timeout=90)

    if resultado["texto"]:
        return resultado["texto"]

    raise Exception(f"Todas as tentativas OpenRouter falharam. Último erro: {resultado['erro']}")

# ════════════════════════════════════════════════
# GEMINI
# ════════════════════════════════════════════════

def _extrair_retry_delay(erro_str: str, padrao: float = 20.0) -> float:
    try:
        match = re.search(r"'retryDelay':\s*'(\d+)s'", str(erro_str))
        if match:
            return float(match.group(1)) + 1.0
    except:
        pass
    return padrao

def gerar_resposta_gemini(prompt: str, max_tokens: int = 8000):
    fila = _get_fila_gemini()

    resultado = {"texto": None, "erro": None}
    evento    = threading.Event()
    lock      = threading.Lock()

    def tentar_com_chave():
        chave  = fila.get()
        indice = API_KEYS.index(chave) + 1
        max_retries = 2
        try:
            for tentativa in range(max_retries + 1):
                try:
                    if tentativa > 0:
                        print(f"[GEMINI] chave {indice} retry {tentativa}")
                    else:
                        print(f"[GEMINI] tentando chave {indice} (fila)")

                    ai = genai.Client(api_key=chave)
                    resposta = ai.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                        config={"temperature": 0.7, "max_output_tokens": max_tokens}
                    )
                    texto = resposta.text
                    with lock:
                        if resultado["texto"] is None:
                            resultado["texto"] = texto
                            print(f"[GEMINI] chave {indice} respondeu ({len(texto)} chars)")
                            evento.set()
                    return

                except Exception as e:
                    erro_str = str(e)
                    is_429   = "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str

                    if is_429 and tentativa < max_retries:
                        espera = _extrair_retry_delay(erro_str)
                        print(f"[GEMINI] chave {indice} rate-limited, aguardando {espera:.0f}s...")
                        time.sleep(espera)
                        continue

                    print(f"[GEMINI] erro chave {indice}: {erro_str[:200]}")
                    with lock:
                        resultado["erro"] = e
                    break
        finally:
            fila.put(chave)

    threads = [
        threading.Thread(target=tentar_com_chave, daemon=True)
        for _ in API_KEYS
    ]
    for t in threads:
        t.start()

    evento.wait(timeout=120)

    if resultado["texto"]:
        return resultado["texto"]

    raise Exception(f"Todas as chaves Gemini falharam. Último erro: {resultado['erro']}")

# ════════════════════════════════════════════════
# GERAR RESPOSTA — Gemini e OpenRouter em paralelo, SEM semáforo
# ════════════════════════════════════════════════

def gerar_resposta(prompt: str, max_tokens: int = 8000):
    resultado = {"texto": None, "erro_gemini": None, "erro_or": None}
    evento    = threading.Event()
    lock      = threading.Lock()

    def _verificar_fim():
        gemini_done = (not API_KEYS)        or (resultado["erro_gemini"] is not None)
        or_done     = (not OPENROUTER_KEYS) or (resultado["erro_or"]     is not None)
        if gemini_done and or_done and resultado["texto"] is None:
            evento.set()

    def tentar_gemini():
        if not API_KEYS:
            return
        try:
            texto = gerar_resposta_gemini(prompt, max_tokens)
            with lock:
                if resultado["texto"] is None:
                    resultado["texto"] = texto
                    print("[IA] Gemini venceu a corrida")
                    evento.set()
        except Exception as e:
            print(f"[IA] Gemini falhou: {e}")
            with lock:
                resultado["erro_gemini"] = e
            _verificar_fim()

    def tentar_openrouter():
        if not OPENROUTER_KEYS:
            return
        try:
            texto = gerar_resposta_openrouter(prompt)
            with lock:
                if resultado["texto"] is None:
                    resultado["texto"] = texto
                    print("[IA] OpenRouter venceu a corrida")
                    evento.set()
        except Exception as e:
            print(f"[IA] OpenRouter falhou: {e}")
            with lock:
                resultado["erro_or"] = e
            _verificar_fim()

    t1 = threading.Thread(target=tentar_gemini,     daemon=True)
    t2 = threading.Thread(target=tentar_openrouter, daemon=True)
    t1.start()
    t2.start()

    evento.wait(timeout=150)

    if resultado["texto"]:
        return resultado["texto"]

    raise Exception(
        f"Todas as IAs falharam. "
        f"Gemini: {resultado['erro_gemini']} | OpenRouter: {resultado['erro_or']}"
    )

# ════════════════════════════════════════════════
# JSON SAFE
# ════════════════════════════════════════════════

def safe_json(raw: str):
    if not raw:
        return {"erro": "Resposta vazia"}

    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except:
        pass

    try:
        inicio = cleaned.index("{")
        fim    = cleaned.rindex("}") + 1
        return json.loads(cleaned[inicio:fim])
    except:
        pass

    try:
        sem_quebra = re.sub(r'(?<!\\)\n', ' ', cleaned)
        inicio = sem_quebra.index("{")
        fim    = sem_quebra.rindex("}") + 1
        return json.loads(sem_quebra[inicio:fim])
    except:
        pass

    try:
        candidato = cleaned[:cleaned.rindex("}") + 1]
        abertas   = candidato.count("{")
        fechadas  = candidato.count("}")
        if abertas > fechadas:
            candidato += "}" * (abertas - fechadas)
        return json.loads(candidato)
    except:
        pass

    print(f"[SAFE_JSON] falhou em parsear: {raw[:500]}")
    return {"erro": "json_invalido", "raw": raw[:1000]}

# ════════════════════════════════════════════════
# DETECTAR REDE
# ════════════════════════════════════════════════

def detectar_rede(url):
    url = url.lower()
    if "instagram" in url: return "instagram"
    if "youtube" in url or "youtu.be" in url: return "youtube"
    if "github" in url: return "github"
    if "twitter" in url or "x.com" in url: return "twitter"
    return "web"

# ════════════════════════════════════════════════
# LIMPAR URL — remove ?igsh= e outros params mobile
# ════════════════════════════════════════════════

def limpar_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        limpa  = urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
        if "instagram.com" in limpa and not limpa.endswith("/"):
            limpa += "/"
        return limpa
    except:
        return url

# ════════════════════════════════════════════════
# LIMPAR NÚMERO — corrigido para 233M, 1.2k etc
# ════════════════════════════════════════════════

def limpar_numero(texto):
    if not texto: return 0
    texto = str(texto).lower().strip()
    for w in ["visualizações", "views", "curtidas", "likes"]:
        texto = texto.replace(w, "")
    texto = texto.replace(",", ".")
    mult = 1
    if re.search(r'\bmil\b', texto):         mult = 1000
    elif re.search(r'[\d]\s*k', texto):      mult = 1000
    elif re.search(r'[\d]\s*m\b', texto):    mult = 1_000_000
    match = re.search(r"([\d\.]+)", texto)
    if not match: return 0
    try:
        return int(float(match.group(1)) * mult)
    except:
        return 0

# ════════════════════════════════════════════════
# FORMATAR NÚMERO
# ════════════════════════════════════════════════

def formatar_numero(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"

    if n < 100_000:
        return f"{n:,}".replace(",", ".")
    elif n < 1_000_000:
        return f"{round(n / 1_000)}k"
    else:
        valor     = n / 1_000_000
        formatado = f"{valor:.1f}".rstrip("0").rstrip(".")
        return f"{formatado}M"

# ════════════════════════════════════════════════
# VALIDAR URL INSTAGRAM
# ════════════════════════════════════════════════

_SEGMENTOS_INVALIDOS_IG = {
    "stories", "p", "reel", "reels", "explore",
    "tv", "ar", "direct", "accounts", "share",
    "api", "oauth", "challenge", "legal", "about",
    "press", "help", "blog", "jobs", "privacy",
    "hashtag", "location", "audio"
}

def validar_url_instagram(url: str) -> tuple[bool, str]:
    try:
        parsed = urllib.parse.urlparse(url)
        partes = [p for p in parsed.path.split("/") if p]

        if len(partes) == 0:
            return False, (
                "URL inválida. Informe a URL do perfil público, "
                "por exemplo: https://www.instagram.com/nome_do_perfil/"
            )

        if len(partes) > 1:
            return False, (
                "URL inválida. Parece ser um link de post, reel ou story. "
                "Informe apenas a URL do perfil, "
                "por exemplo: https://www.instagram.com/nome_do_perfil/"
            )

        if partes[0].lower() in _SEGMENTOS_INVALIDOS_IG:
            return False, (
                f"URL inválida ('{partes[0]}' não é um perfil). "
                "Informe a URL do perfil público, "
                "por exemplo: https://www.instagram.com/nome_do_perfil/"
            )

        return True, ""

    except Exception:
        return False, "URL inválida ou mal formatada."

# ════════════════════════════════════════════════
# TEXTO UTIL
# ════════════════════════════════════════════════

CAPTION_MAX = 120
TEXTO_MAX   = 3500

def extrair_texto_util(scraped, rede):

    if rede == "instagram":
        textos = []

        perfil = scraped.get("perfil", {})
        bio    = perfil.get("bio", "")
        seg    = perfil.get("seguidores", 0)
        pub    = perfil.get("publicacoes", 0)

        if bio:
            textos.append(f"BIO DO PERFIL: {bio[:200]}")
        if seg:
            textos.append(f"Seguidores: {seg:,}")
        if pub:
            textos.append(f"Publicações: {pub}")

        stats = scraped.get("estatisticas", {})
        if stats:
            textos.append(
                f"Total likes (últimos posts): {stats.get('total_likes', 0):,} | "
                f"Total comentários: {stats.get('total_comments', 0):,} | "
                f"Taxa de engajamento: {stats.get('engajamento', 0):.2f}%"
            )

        posts = scraped.get("posts", [])
        print(f"[TEXTO_UTIL] {len(posts)} posts para análise")

        if not posts:
            textos.append("AVISO: Nenhum post encontrado.")
        else:
            textos.append(f"\n--- ÚLTIMOS {len(posts)} POSTS/REELS ---")
            for i, p in enumerate(posts):
                caption     = (p.get("caption", "") or "").strip()[:CAPTION_MAX]
                likes       = p.get("likes", 0)
                comentarios = p.get("comentarios", 0)
                views       = p.get("views", 0)
                tipo        = p.get("tipo", "post").upper()
                url         = p.get("url", "")

                linha = (
                    f"[{tipo} {i+1}] "
                    f"Likes: {likes:,} | Comentários: {comentarios:,}"
                )
                if views:
                    linha += f" | Views: {views:,}"
                if caption:
                    linha += f"\n  Legenda: {caption}"
                elif url:
                    linha += f"\n  URL: {url}"

                textos.append(linha)

        resultado = "\n".join(textos)

        if len(resultado) > TEXTO_MAX:
            resultado = resultado[:TEXTO_MAX] + "\n[... truncado ...]"

        print(f"[TEXTO_UTIL] {len(resultado)} chars gerados")
        print(f"[TEXTO_UTIL] preview:\n{resultado[:600]}\n---")
        return resultado

    elif rede == "youtube":
        videos = scraped.get("videos", [])
        linhas = [f"Canal: {scraped.get('titulo', '')}"]
        for v in videos:
            linhas.append(
                f"- {v.get('title','')} | {v.get('views','')} views | {v.get('data','')}"
            )
        return "\n".join(linhas)[:TEXTO_MAX]

    elif rede == "github":
        repos = scraped.get("repos", [])
        linhas = [f"Perfil GitHub: {scraped.get('titulo', '')}"]
        for r in repos:
            linhas.append(
                f"- {r.get('nome','')} | ⭐{r.get('stars','0')} | {r.get('desc','')}"
            )
        return "\n".join(linhas)[:TEXTO_MAX]

    return scraped.get("texto", "")[:TEXTO_MAX]

# ════════════════════════════════════════════════
# HISTORICO GRAFICO
# ════════════════════════════════════════════════

def extrair_historico_grafico(scraped, rede):
    historico = []

    if rede == "instagram":
        for p in scraped.get("posts", []):
            caption = p.get("caption", "") or ""
            url     = p.get("url", "")
            match   = re.search(r"/(p|reel)/([^/]+)", url)
            titulo  = caption[:40] if caption else (
                f"{match.group(1)} {match.group(2)[:8]}" if match else "Post"
            )
            historico.append({
                "titulo":        titulo,
                "data":          "Recente",
                "visualizacoes": p.get("views", 0),
                "curtidas":      p.get("likes", 0),
                "comentarios":   p.get("comentarios", 0),
                "link":          url,
                "thumb":         p.get("thumb", "")
            })

    elif rede == "youtube":
        for v in scraped.get("videos", []):
            historico.append({
                "titulo":        v.get("title", "Vídeo"),
                "data":          v.get("data", "Recente"),
                "visualizacoes": limpar_numero(v.get("views", "0")),
                "curtidas":      0,
                "comentarios":   0,
                "link":          v.get("link", ""),
                "thumb":         v.get("thumb", "")
            })

    elif rede == "github":
        for r in scraped.get("repos", []):
            historico.append({
                "titulo":        r.get("nome", "Repo"),
                "data":          "Recente",
                "visualizacoes": 0,
                "curtidas":      limpar_numero(r.get("stars", "0")),
                "comentarios":   0,
                "link":          r.get("link", "")
            })

    return historico

# ════════════════════════════════════════════════
# ANALISE IA
# ════════════════════════════════════════════════

def _cache_valido(resultado: dict) -> bool:
    listas = ["pontos_fortes", "oportunidades", "ideias_conteudo", "estrategia_crescimento"]
    return all(
        isinstance(resultado.get(k), list) and len(resultado.get(k, [])) > 0
        for k in listas
    )

def analisar_com_ia(texto: str, rede: str, url: str = ""):

    # ── Cache por URL ──
    if url:
        chave_url = hashlib.md5(url.lower().strip().encode()).hexdigest()
        with _cache_lock:
            if chave_url in _cache_url:
                cached = _cache_url[chave_url]
                if _cache_valido(cached):
                    print("[IA] usando cache por URL")
                    return cached
                else:
                    del _cache_url[chave_url]

    if not texto.strip() or len(texto.strip()) < 30:
        print("[IA] texto muito curto, pulando")
        return {
            "resumo": "Não foi possível extrair conteúdo suficiente do perfil.",
            "score": 50,
            "score_motivo": "Poucos dados disponíveis para análise.",
            "pontos_fortes": [],
            "oportunidades": [],
            "ideias_conteudo": [],
            "estrategia_crescimento": [],
            "publico_alvo": {}
        }

    # ── Cache por conteúdo ──
    chave = hashlib.md5((rede + texto[:500]).encode()).hexdigest()

    if chave in _cache_analise:
        cached = _cache_analise[chave]
        if _cache_valido(cached):
            print("[IA] usando cache válido")
            return cached
        else:
            print("[IA] cache inválido, regenerando...")
            del _cache_analise[chave]

    prompt = f"""Você é um especialista em crescimento digital e marketing de conteúdo.

Analise os dados abaixo de um perfil de {rede} e gere insights estratégicos detalhados e específicos.

DADOS DO PERFIL:
{texto}

INSTRUÇÕES CRÍTICAS:
- Responda SOMENTE com JSON válido e completo
- NÃO use markdown, NÃO use ```json, NÃO adicione explicações fora do JSON
- Todas as listas DEVEM ter exatamente 3 itens — nunca deixe lista vazia
- Cada item deve ser específico ao perfil analisado, não genérico
- Se os dados forem limitados, use o que está disponível e faça análise baseada nisso
- MUITO IMPORTANTE: o JSON deve estar 100% completo, com todas as chaves fechadas

ATENÇÃO PARA O CAMPO ideias_conteudo:
- Cada ideia DEVE ter um campo "texto" com a descrição da ideia
- Cada ideia DEVE ter um campo "tags" com 2 hashtags do Instagram relevantes para buscar referências
- As hashtags devem ser em português ou inglês, sem o #, minúsculas e sem espaços
- Exemplo de tag boa: "grwm", "lookdodia", "maquiagemfacil", "ootd"

ATENÇÃO PARA O CAMPO publico_alvo:
- Analise o conteúdo, bio, legendas e engajamento para inferir quem segue este perfil
- "faixa_etaria" deve ser uma faixa realista ex: "18–24 anos", "25–35 anos"
- "genero" deve indicar predominância ex: "maioria feminino", "equilibrado", "maioria masculino"
- "interesses" deve ter exatamente 3 interesses específicos ao nicho do perfil
- "tom" deve descrever como o criador se comunica ex: "descontraído e inspiracional"
- "resumo" deve ser 1 frase descrevendo quem são os seguidores

Formato obrigatório:

{{
  "resumo": "Análise geral do perfil em 2-3 frases concretas",
  "score": 75,
  "score_motivo": "Justificativa do score em 1 frase",
  "pontos_fortes": [
    "Ponto forte 1 específico deste perfil",
    "Ponto forte 2 específico deste perfil",
    "Ponto forte 3 específico deste perfil"
  ],
  "oportunidades": [
    "Oportunidade de melhoria 1 específica",
    "Oportunidade de melhoria 2 específica",
    "Oportunidade de melhoria 3 específica"
  ],
  "ideias_conteudo": [
    {{ "texto": "Ideia 1 específica e acionável para este nicho", "tags": ["hashtag1", "hashtag2"] }},
    {{ "texto": "Ideia 2 específica e acionável para este nicho", "tags": ["hashtag1", "hashtag2"] }},
    {{ "texto": "Ideia 3 específica e acionável para este nicho", "tags": ["hashtag1", "hashtag2"] }}
  ],
  "estrategia_crescimento": [
    "Passo estratégico 1 com ação concreta",
    "Passo estratégico 2 com ação concreta",
    "Passo estratégico 3 com ação concreta"
  ],
  "publico_alvo": {{
    "faixa_etaria": "ex: 18–24 anos",
    "genero": "ex: maioria feminino",
    "interesses": ["interesse 1", "interesse 2", "interesse 3"],
    "tom": "ex: descontraído e inspiracional",
    "resumo": "Quem segue este perfil em 1 frase"
  }}
}}"""

    print(f"[IA] enviando prompt ({len(prompt)} chars)")

    resposta_raw = gerar_resposta(prompt)
    resultado    = safe_json(resposta_raw)

    if "erro" in resultado:
        print(f"[IA] parse falhou, tentando com prompt reduzido...")
        prompt_curto = prompt.replace(texto, texto[:1500])
        try:
            resposta_raw2 = gerar_resposta(prompt_curto)
            resultado     = safe_json(resposta_raw2)
        except Exception as e:
            print(f"[IA] retry falhou: {e}")

    if "erro" in resultado:
        return {
            "resumo": "Erro ao processar resposta da IA.",
            "score": 50,
            "score_motivo": "Resposta da IA inválida.",
            "pontos_fortes": [],
            "oportunidades": [],
            "ideias_conteudo": [],
            "estrategia_crescimento": [],
            "publico_alvo": {}
        }

    defaults = {
        "resumo": "",
        "score": 60,
        "score_motivo": "",
        "pontos_fortes": [],
        "oportunidades": [],
        "ideias_conteudo": [],
        "estrategia_crescimento": [],
        "publico_alvo": {}
    }
    for k, v in defaults.items():
        if k not in resultado:
            resultado[k] = v

    # ── normalizar ideias_conteudo ──
    ideias_normalizadas = []
    for ideia in resultado.get("ideias_conteudo", []):
        if isinstance(ideia, str):
            ideias_normalizadas.append({"texto": ideia, "tags": []})
        elif isinstance(ideia, dict):
            ideias_normalizadas.append({
                "texto": ideia.get("texto", ""),
                "tags":  ideia.get("tags", [])
            })
    resultado["ideias_conteudo"] = ideias_normalizadas

    # ── normalizar publico_alvo ──
    pa = resultado.get("publico_alvo", {})
    if not isinstance(pa, dict):
        resultado["publico_alvo"] = {}
    else:
        if not isinstance(pa.get("interesses"), list):
            pa["interesses"] = []
        resultado["publico_alvo"] = pa

    print(f"[IA] análise gerada — pontos_fortes: {len(resultado['pontos_fortes'])} | "
          f"oportunidades: {len(resultado['oportunidades'])} | "
          f"ideias: {len(resultado['ideias_conteudo'])} | "
          f"publico_alvo: {bool(resultado['publico_alvo'])}")

    for i, ideia in enumerate(resultado["ideias_conteudo"]):
        print(f"[IA] ideia {i+1} tags: {ideia.get('tags', [])}")

    # ── salvar em cache ──
    if _cache_valido(resultado):
        _cache_analise[chave] = resultado
        if url:
            with _cache_lock:
                _cache_url[chave_url] = resultado
    else:
        print("[IA] resultado inválido (listas vazias), NÃO cacheando")

    return resultado

# ════════════════════════════════════════════════
# ROTAS
# ════════════════════════════════════════════════

@analisar_bp.route("/analisar")
def analisar_page():
    if "user_id" not in session:
        return redirect("/")
    return render_template("analisar.html")


@analisar_bp.route("/api/analisar", methods=["POST"])
def api_analisar():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"erro": "JSON obrigatório"}), 400

        url = data.get("url", "").strip()
        if not url:
            return jsonify({"erro": "URL obrigatória"}), 400
        if not url.startswith("http"):
            url = "https://" + url

        url = limpar_url(url)
        print(f"[API] URL limpa: {url}")

        if "instagram.com" in url.lower():
            valida, msg_erro = validar_url_instagram(url)
            if not valida:
                return jsonify({
                    "ok":       False,
                    "erro":     "url_invalida",
                    "mensagem": msg_erro
                }), 422

        inicio = time.time()
        rede   = detectar_rede(url)

        print(f"\n{'='*50}")
        print(f"[API] analisando: {url}")
        print(f"[API] rede detectada: {rede}")
        print(f"{'='*50}")

        try:
            scraped = scrape_url(url)
        except Exception as e:
            if "PERFIL_PRIVADO" in str(e):
                return jsonify({
                    "ok":       False,
                    "erro":     "perfil_privado",
                    "mensagem": "Este perfil é privado. Só é possível analisar perfis públicos."
                }), 422
            raise

        posts = scraped.get("posts", [])
        print(f"[API] posts raspados: {len(posts)}")

        for i, p in enumerate(posts[:3]):
            cap = p.get("caption", "")
            print(f"[API] post {i+1} caption ({len(cap)} chars): {cap[:100]}")

        texto_util    = extrair_texto_util(scraped, rede)
        analise       = analisar_com_ia(texto_util, rede, url=url)
        dados_grafico = extrair_historico_grafico(scraped, rede)

        from app.database.database import db
        from app.database.models import Analise
        if "user_id" in session:
            nova_analise = Analise(
                user_id=session["user_id"],
                rede=rede,
                url=url
            )
            db.session.add(nova_analise)
            db.session.commit()

        print(f"\n[API] análise final:")
        print(json.dumps(analise, indent=2, ensure_ascii=False))

        return jsonify({
            "ok":            True,
            "rede":          rede,
            "perfil":        scraped,
            "analise":       analise,
            "dados_grafico": dados_grafico,
            "timing":        {"total_s": round(time.time() - inicio, 2)},
            "timestamp":     datetime.utcnow().isoformat()
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"ok": False, "erro": str(e)}), 500
