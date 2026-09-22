"""Public pages, authentication and the assistant API."""

from dataclasses import dataclass

import requests as http_requests
from flask import Blueprint, jsonify, redirect, render_template, request, session
from oauthlib.oauth2 import WebApplicationClient

from app.config import settings
from app.database.database import db
from app.database.models import User
from app.services.chat_ai import gerar_resposta_chat

core_bp = Blueprint("core", __name__)
oauth_client = WebApplicationClient(settings.GOOGLE_CLIENT_ID)


@dataclass
class GoogleHosts:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str


def get_google_oauth_urls() -> GoogleHosts:
    data = http_requests.get(
        "https://accounts.google.com/.well-known/openid-configuration", timeout=15
    ).json()
    return GoogleHosts(data["authorization_endpoint"], data["token_endpoint"],
                       data["userinfo_endpoint"])


@core_bp.route("/")
def home():
    return redirect("/perfil") if "user_id" in session else render_template("landing.html")


@core_bp.route("/login")
def login_page():
    return redirect("/perfil") if "user_id" in session else render_template("index.html")


@core_bp.route("/auth/login")
def login():
    if "user_id" in session:
        return redirect("/perfil")
    hosts = get_google_oauth_urls()
    return redirect(oauth_client.prepare_request_uri(
        hosts.authorization_endpoint, redirect_uri=settings.REDIRECT_URI,
        scope=["openid", "email", "profile"],
    ))


@core_bp.route("/auth/callback")
def callback():
    hosts = get_google_oauth_urls()
    token_url, headers, body = oauth_client.prepare_token_request(
        hosts.token_endpoint, authorization_response=request.url,
        redirect_url=settings.REDIRECT_URI, code=request.args.get("code"),
    )
    response = http_requests.post(token_url, headers=headers, data=body,
                                  auth=(settings.GOOGLE_CLIENT_ID, settings.GOOGLE_SECRET), timeout=20)
    oauth_client.parse_request_body_response(response.text)
    uri, headers, body = oauth_client.add_token(hosts.userinfo_endpoint)
    userinfo = http_requests.get(uri, headers=headers, data=body, timeout=20).json()
    user = User.query.filter_by(google_id=userinfo["sub"]).first()
    if not user:
        user = User(google_id=userinfo["sub"], nome=userinfo["name"],
                    email=userinfo["email"], foto=userinfo["picture"])
        db.session.add(user)
        db.session.commit()
    session.permanent = True
    session.update(user_id=user.id, nome=user.nome, email=user.email, foto=user.foto)
    return redirect("/perfil")


@core_bp.route("/perfil")
def perfil():
    if "user_id" not in session:
        return redirect("/")
    return render_template("perfil.html", nome=session["nome"], email=session["email"], foto=session["foto"])


@core_bp.route("/api/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "não autenticado"}), 401
    data = request.get_json(silent=True) or {}
    mensagem, historico = data.get("mensagem", "").strip(), data.get("historico", [])
    if not mensagem:
        return jsonify({"error": "mensagem vazia"}), 400
    context = f"Você é um assistente pessoal. Usuário: {session['nome']} ({session['email']}). Responda sempre em português."
    contents = [item.get("parts", "") for item in historico]
    contents = contents + [mensagem] if contents else [context + "\n\n" + mensagem]
    prompt = "\n".join([context, *[str(item.get("parts", "")) for item in historico], mensagem])
    try:
        return jsonify({"resposta": gerar_resposta_chat(contents, prompt)})
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@core_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")
