import re
import threading
import time

import requests as http_requests
from google import genai

from app.config import settings


CHAT_API_KEYS = settings.GEMINI_API_KEYS
CHAT_OPENROUTER_KEYS = settings.OPENROUTER_API_KEYS

CHAT_OPENROUTER_MODELS = [
    "openrouter/auto",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "qwen/qwen3-235b-a22b:free",
    "google/gemma-3-27b-it:free",
]


def _extrair_retry_delay_chat(erro_str: str, padrao: float = 20.0) -> float:
    try:
        match = re.search(r"'retryDelay':\s*'(\d+)s'", str(erro_str))
        if match:
            return float(match.group(1)) + 1.0
    except:
        pass
    return padrao



def _chat_gemini(contents: list, max_tokens: int = 2000) -> str:
    resultado = {"texto": None, "erro": None}
    evento    = threading.Event()
    lock      = threading.Lock()

    def tentar(chave, indice):
        max_retries = 2
        for tentativa in range(max_retries + 1):
            try:
                print(f"[CHAT:GEMINI] chave {indice+1} tentativa {tentativa+1}")
                ai = genai.Client(api_key=chave)
                resposta = ai.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config={"temperature": 0.7, "max_output_tokens": max_tokens}
                )
                texto = resposta.text
                with lock:
                    if resultado["texto"] is None:
                        resultado["texto"] = texto
                        print(f"[CHAT:GEMINI] chave {indice+1} respondeu ({len(texto)} chars)")
                        evento.set()
                return
            except Exception as e:
                erro_str = str(e)
                is_429 = "429" in erro_str or "RESOURCE_EXHAUSTED" in erro_str
                if is_429 and tentativa < max_retries:
                    espera = _extrair_retry_delay_chat(erro_str)
                    print(f"[CHAT:GEMINI] chave {indice+1} rate-limited, aguardando {espera:.0f}s...")
                    time.sleep(espera)
                    continue
                with lock:
                    resultado["erro"] = e
                break

        vivas = sum(1 for t in threads if t.is_alive())
        if vivas == 0 and resultado["texto"] is None:
            evento.set()

    threads = [
        threading.Thread(target=tentar, args=(chave, i), daemon=True)
        for i, chave in enumerate(CHAT_API_KEYS)
    ]
    for t in threads:
        t.start()

    evento.wait(timeout=60)

    if resultado["texto"]:
        return resultado["texto"]
    raise Exception(f"Gemini chat falhou: {resultado['erro']}")


def _chat_openrouter(prompt: str, max_tokens: int = 2000) -> str:
    if not CHAT_OPENROUTER_KEYS:
        raise Exception("Sem chaves OpenRouter.")

    resultado = {"texto": None, "erro": None}
    evento    = threading.Event()
    lock      = threading.Lock()
    tarefas   = [(key, model) for key in CHAT_OPENROUTER_KEYS for model in CHAT_OPENROUTER_MODELS]

    def tentar(key, model, idx):
        try:
            print(f"[CHAT:OR] tentando {model}")
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://localhost",
                    "X-Title":       "ChatAssistente"
                },
                json={
                    "model":       model,
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  max_tokens,
                    "temperature": 0.7
                },
                timeout=60
            )
            if resp.status_code == 200:
                texto = resp.json()["choices"][0]["message"]["content"]
                with lock:
                    if resultado["texto"] is None:
                        resultado["texto"] = texto
                        print(f"[CHAT:OR] {model} respondeu ({len(texto)} chars)")
                        evento.set()
            else:
                with lock:
                    resultado["erro"] = f"{resp.status_code} em {model}"
        except Exception as e:
            with lock:
                resultado["erro"] = e
        finally:
            vivas = sum(1 for t in threads if t.is_alive())
            if vivas == 0 and resultado["texto"] is None:
                evento.set()

    threads = [
        threading.Thread(target=tentar, args=(key, model, i), daemon=True)
        for i, (key, model) in enumerate(tarefas)
    ]
    for t in threads:
        t.start()

    evento.wait(timeout=90)

    if resultado["texto"]:
        return resultado["texto"]
    raise Exception(f"OpenRouter chat falhou: {resultado['erro']}")


def gerar_resposta_chat(contents_gemini: list, prompt_texto: str, max_tokens: int = 2000) -> str:
    resultado = {"texto": None, "erro_gemini": None, "erro_or": None}
    evento    = threading.Event()
    lock      = threading.Lock()

    def _verificar_fim():
        gemini_done = (not CHAT_API_KEYS)        or (resultado["erro_gemini"] is not None)
        or_done     = (not CHAT_OPENROUTER_KEYS) or (resultado["erro_or"]     is not None)
        if gemini_done and or_done and resultado["texto"] is None:
            evento.set()

    def tentar_gemini():
        if not CHAT_API_KEYS:
            return
        try:
            texto = _chat_gemini(contents_gemini, max_tokens)
            with lock:
                if resultado["texto"] is None:
                    resultado["texto"] = texto
                    print("[CHAT] Gemini venceu")
                    evento.set()
        except Exception as e:
            with lock:
                resultado["erro_gemini"] = e
            _verificar_fim()

    def tentar_or():
        if not CHAT_OPENROUTER_KEYS:
            return
        try:
            texto = _chat_openrouter(prompt_texto, max_tokens)
            with lock:
                if resultado["texto"] is None:
                    resultado["texto"] = texto
                    print("[CHAT] OpenRouter venceu")
                    evento.set()
        except Exception as e:
            with lock:
                resultado["erro_or"] = e
            _verificar_fim()

    t1 = threading.Thread(target=tentar_gemini, daemon=True)
    t2 = threading.Thread(target=tentar_or,     daemon=True)
    t1.start()
    t2.start()

    evento.wait(timeout=120)

    if resultado["texto"]:
        return resultado["texto"]

    raise Exception(
        f"Chat IA falhou. Gemini: {resultado['erro_gemini']} | OpenRouter: {resultado['erro_or']}"
    )
