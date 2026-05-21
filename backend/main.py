# main.py — Flask + Google OAuth + Chat Gemini

from flask import Flask, render_template, redirect, request, session, jsonify
from dotenv import load_dotenv
from dataclasses import dataclass
from oauthlib.oauth2 import WebApplicationClient
import requests as http_requests
import os
import re
import threading
import time
from google import genai
from flask_sqlalchemy import SQLAlchemy
from datetime import timedelta

from admin import admin_bp, init_admin
from analisar import analisar_bp
from referencias import referencias_bp

# ─────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────

app = Flask(__name__)

# ─────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────

app.secret_key = os.getenv("SECRET_KEY")
app.permanent_session_lifetime = timedelta(days=7)

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

db_url = os.getenv("DATABASE_URL", "sqlite:///app.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
from admin_config import admin_config_bp

app.register_blueprint(admin_config_bp)

# ─────────────────────────────────────────────
# MODEL USER
# ─────────────────────────────────────────────

class User(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(200), unique=True, nullable=False)
    nome      = db.Column(db.String(200))
    email     = db.Column(db.String(200), unique=True)
    foto      = db.Column(db.String(500))

# ─────────────────────────────────────────────
# INIT ADMIN
# ─────────────────────────────────────────────

init_admin(db, User)

# ─────────────────────────────────────────────
# GEMINI — chaves múltiplas para o chat (mesmo
# esquema do analisar.py: tenta em paralelo e
# usa a primeira que responder)
# ─────────────────────────────────────────────

CHAT_API_KEYS = [
    k for k in [os.getenv(f"GEMINI_API_{i}") for i in range(1, 11)]
    if k
]

CHAT_OPENROUTER_KEYS = [
    k for k in [os.getenv(f"OPENROUTER_API_{i}") for i in range(1, 6)]
    if k
]

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
    """Tenta todas as chaves Gemini em paralelo e retorna a primeira resposta."""
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
    """Tenta todos os modelos OpenRouter em paralelo e retorna o primeiro."""
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
    """
    Dispara Gemini e OpenRouter em paralelo para o chat.
    Retorna a primeira resposta que chegar.
    """
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

# ─────────────────────────────────────────────
# GOOGLE OAUTH
# ─────────────────────────────────────────────

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_SECRET    = os.getenv("GOOGLE_SECRET")
REDIRECT_URI     = os.getenv("REDIRECT_URI")   # ex: http://127.0.0.1:8080/auth/callback

oauth_client = WebApplicationClient(GOOGLE_CLIENT_ID)

@dataclass
class GoogleHosts:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str

def get_google_oauth_urls():
    data = http_requests.get(
        "https://accounts.google.com/.well-known/openid-configuration"
    ).json()
    return GoogleHosts(
        authorization_endpoint=data["authorization_endpoint"],
        token_endpoint=data["token_endpoint"],
        userinfo_endpoint=data["userinfo_endpoint"],
    )

# ─────────────────────────────────────────────
# BLUEPRINTS
# ─────────────────────────────────────────────

app.register_blueprint(admin_bp)
app.register_blueprint(analisar_bp)
app.register_blueprint(referencias_bp)

# ─────────────────────────────────────────────
# ROTAS AUTH
# ─────────────────────────────────────────────

@app.route('/')
def home():
    if "user_id" in session:
        return redirect("/perfil")
    return render_template("index.html")

@app.route('/auth/login')
def login():
    if "user_id" in session:
        return redirect("/perfil")
    hosts = get_google_oauth_urls()
    uri = oauth_client.prepare_request_uri(
        hosts.authorization_endpoint,
        redirect_uri=REDIRECT_URI,
        scope=['openid', 'email', 'profile']
    )
    return redirect(uri)

@app.route('/auth/callback')
def callback():
    code = request.args.get("code")
    hosts = get_google_oauth_urls()

    token_url, headers, body = oauth_client.prepare_token_request(
        hosts.token_endpoint,
        authorization_response=request.url,
        redirect_url=REDIRECT_URI,
        code=code
    )
    token_response = http_requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_SECRET)
    )
    oauth_client.parse_request_body_response(token_response.text)

    uri, headers, body = oauth_client.add_token(hosts.userinfo_endpoint)
    userinfo = http_requests.get(uri, headers=headers, data=body).json()

    google_id = userinfo["sub"]
    user = User.query.filter_by(google_id=google_id).first()

    if not user:
        user = User(
            google_id=google_id,
            nome=userinfo["name"],
            email=userinfo["email"],
            foto=userinfo["picture"]
        )
        db.session.add(user)
        db.session.commit()

    session.permanent = True
    session["user_id"] = user.id
    session["nome"]    = user.nome
    session["email"]   = user.email
    session["foto"]    = user.foto

    return redirect("/perfil")

# ─────────────────────────────────────────────
# PERFIL
# ─────────────────────────────────────────────

@app.route('/perfil')
def perfil():
    if "user_id" not in session:
        return redirect("/")
    return render_template(
        "perfil.html",
        nome=session["nome"],
        email=session["email"],
        foto=session["foto"]
    )

# ─────────────────────────────────────────────
# API CHAT — Gemini + OpenRouter em paralelo
# ─────────────────────────────────────────────

@app.route('/api/chat', methods=['POST'])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "não autenticado"}), 401

    data      = request.get_json()
    mensagem  = data.get("mensagem", "").strip()
    historico = data.get("historico", [])

    if not mensagem:
        return jsonify({"error": "mensagem vazia"}), 400

    ctx = (
        f"Você é um assistente pessoal. "
        f"Usuário: {session['nome']} ({session['email']}). "
        f"Responda sempre em português."
    )

    # Monta contents para Gemini
    contents_gemini = []
    if not historico:
        contents_gemini.append(ctx + "\n\n" + mensagem)
    else:
        for h in historico:
            contents_gemini.append(h["parts"])
        contents_gemini.append(mensagem)

    # Monta prompt texto para OpenRouter (histórico simples)
    if not historico:
        prompt_texto = ctx + "\n\n" + mensagem
    else:
        linhas = [ctx]
        for h in historico:
            linhas.append(str(h.get("parts", "")))
        linhas.append(mensagem)
        prompt_texto = "\n".join(linhas)

    try:
        resposta = gerar_resposta_chat(contents_gemini, prompt_texto)
        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────

@app.route('/logout')
def logout():
    session.clear()
    return redirect("/")

# ─────────────────────────────────────────────
# CREATE TABLES
# ─────────────────────────────────────────────

with app.app_context():
    db.create_all()

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8080,
        debug=False
    )