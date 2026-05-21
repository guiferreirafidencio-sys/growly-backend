from flask import (
    Blueprint,
    render_template,
    jsonify,
    request,
    redirect,
    session
)

from playwright.sync_api import sync_playwright

from pathlib import Path
from functools import wraps
from datetime import datetime

import threading
import json
import time
import os

admin_config_bp = Blueprint(
    "admin_config",
    __name__
)

# =========================================================
# PASTAS
# =========================================================

BASE_DIR = Path(__file__).parent

SESSIONS_DIR = BASE_DIR / "sessions"

SESSIONS_DIR.mkdir(
    parents=True,
    exist_ok=True
)

CONFIG_FILE = SESSIONS_DIR / "contas.json"

# =========================================================
# LOGIN STATUS
# =========================================================

login_status = {
    "running": False,
    "username": None,
    "profile_dir": None,
    "error": None
}

# =========================================================
# ADMIN REQUIRED
# =========================================================

def admin_required(f):

    @wraps(f)
    def decorated(*args, **kwargs):

        admin_email = os.getenv(
            "ADMIN_EMAIL",
            ""
        ).strip().lower()

        user_email = session.get(
            "email",
            ""
        ).strip().lower()

        if not user_email:
            return redirect("/")

        if user_email != admin_email:
            return redirect("/")

        return f(*args, **kwargs)

    return decorated

# =========================================================
# JSON HELPERS
# =========================================================

def carregar_contas():

    if not CONFIG_FILE.exists():

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:

            json.dump(
                {"contas": []},
                f,
                indent=4,
                ensure_ascii=False
            )

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:

        data = json.load(f)

    return data.get("contas", [])

def salvar_contas(contas):

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:

        json.dump(
            {"contas": contas},
            f,
            indent=4,
            ensure_ascii=False
        )

# =========================================================
# STATUS
# =========================================================

def montar_status():

    contas = carregar_contas()

    total = len(contas)

    livres = len([
        c for c in contas
        if c["status"] == "livre"
    ])

    total_scrapes = sum([
        c.get("scrapes", 0)
        for c in contas
    ])

    return {
        "total": total,
        "livres": livres,
        "total_scrapes": total_scrapes,
        "contas": contas
    }

# =========================================================
# LOGIN INSTAGRAM
# =========================================================

def iniciar_login_instagram(
    username,
    profile_dir
):

    if login_status["running"]:
        return False

    login_status["running"] = True
    login_status["username"] = username
    login_status["profile_dir"] = profile_dir
    login_status["error"] = None

    def worker():

        try:

            profile_path = (
                SESSIONS_DIR / profile_dir
            )

            profile_path.mkdir(
                parents=True,
                exist_ok=True
            )

            storage_file = (
                profile_path / "storage.json"
            )

            with sync_playwright() as p:

                browser = p.chromium.launch(
                    headless=False,
                    channel="chrome"
                )

                context = browser.new_context(
                    viewport={
                        "width": 1400,
                        "height": 900
                    },
                    locale="pt-BR"
                )

                page = context.new_page()

                print(
                    "[ADMIN] abrindo login instagram"
                )

                page.goto(
                    "https://www.instagram.com/accounts/login/",
                    wait_until="domcontentloaded"
                )

                timeout = time.time() + 300

                login_detectado = False

                while time.time() < timeout:

                    try:

                        current_url = page.url.lower()

                        # procura elementos da home logada
                        avatar = page.locator("svg[aria-label='Página inicial']").count()

                        if avatar > 0:

                            login_detectado = True
                            break

                        # fallback por URL
                        if (
                            "instagram.com" in current_url
                            and "/accounts/login" not in current_url
                        ):

                            login_detectado = True
                            break

                    except:
                        pass

                    time.sleep(2)

                if not login_detectado:

                    raise Exception(
                        "tempo expirado no login"
                    )

                print("[ADMIN] login detectado")

                time.sleep(11)

                print(
                    "[ADMIN] login detectado"
                )

                context.storage_state(
                    path=str(storage_file)
                )

                contas = carregar_contas()

                existe = False

                for conta in contas:

                    if conta["username"] == username:

                        conta["status"] = "livre"

                        conta["ultimo_login"] = (
                            datetime.now().isoformat()
                        )

                        existe = True

                if not existe:

                    contas.append({
                        "username": username,
                        "profile_dir": profile_dir,
                        "status": "livre",
                        "scrapes": 0,
                        "data_cadastro": datetime.now().strftime("%d/%m/%Y"),
                        "ultimo_login": datetime.now().isoformat()
                    })

                salvar_contas(contas)

                browser.close()

        except Exception as e:

            print(
                "[ADMIN] erro:",
                e
            )

            login_status["error"] = str(e)

        finally:

            login_status["running"] = False

    threading.Thread(
        target=worker,
        daemon=True
    ).start()

    return True

# =========================================================
# REMOVER CONTA
# =========================================================

def remover_conta(username):

    contas = carregar_contas()

    nova_lista = []

    for conta in contas:

        if conta["username"] != username:
            nova_lista.append(conta)

    salvar_contas(nova_lista)

# =========================================================
# PEGAR CONTA LIVRE
# =========================================================

def obter_conta_livre():

    contas = carregar_contas()

    for conta in contas:

        if conta["status"] == "livre":

            conta["status"] = "ocupado"

            salvar_contas(contas)

            return conta

    return None

# =========================================================
# LIBERAR CONTA
# =========================================================

def liberar_conta(username):

    contas = carregar_contas()

    for conta in contas:

        if conta["username"] == username:

            conta["status"] = "livre"

            conta["scrapes"] += 1

    salvar_contas(contas)

# =========================================================
# ROTAS
# =========================================================

@admin_config_bp.route("/admin/config")
@admin_required
def admin_config_page():

    return render_template(
        "admin_config.html"
    )

@admin_config_bp.route(
    "/admin/config/status"
)
@admin_required
def admin_config_status():

    return jsonify(
        montar_status()
    )

@admin_config_bp.route(
    "/admin/config/login-instagram"
)
@admin_required
def login_instagram_route():

    username = request.args.get(
        "username",
        ""
    ).replace("@", "").strip()

    profile_dir = request.args.get(
        "profile_dir",
        ""
    ).strip()

    if not username:

        return jsonify({
            "ok": False,
            "error": "username obrigatório"
        }), 400

    if not profile_dir:

        profile_dir = (
            "ig_profile_" + username
        )

    ok = iniciar_login_instagram(
        username,
        profile_dir
    )

    if not ok:

        return jsonify({
            "ok": False,
            "error": "já existe login rodando"
        }), 400

    return jsonify({
        "ok": True
    })

@admin_config_bp.route(
    "/admin/config/remover/<username>",
    methods=["DELETE"]
)
@admin_required
def remover_conta_route(username):

    remover_conta(username)

    return jsonify({
        "ok": True
    })