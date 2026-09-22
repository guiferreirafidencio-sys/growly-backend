from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime

import threading
import json
import time
import os
import gc
import base64
import shutil

from app.account_manager import salvar_senha_conta


SESSIONS_DIR = Path(
    os.getenv("SESSIONS_DIR", "/app/sessions")
)

SESSIONS_DIR.mkdir(
    parents=True,
    exist_ok=True
)

CONFIG_FILE = SESSIONS_DIR / "contas.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


login_status = {
    "running": False,
    "username": None,
    "profile_dir": None,
    "error": None,
    "stage": None,
    "message": None,
    "screenshot": None,
}

_login_context = {
    "page": None,
    "browser": None,
    "context": None,
    "pw": None
}


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
        return json.load(f).get("contas", [])


def salvar_contas(contas):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"contas": contas},
            f,
            indent=4,
            ensure_ascii=False
        )


def montar_status():
    contas = carregar_contas()

    return {
        "total": len(contas),
        "livres": len([
            c for c in contas
            if c.get("status") == "livre"
        ]),
        "total_scrapes": sum(
            c.get("scrapes", 0)
            for c in contas
        ),
        "contas": contas,
    }


def _fechar_login_browser():
    for key in [
        "page",
        "context",
        "browser",
        "pw"
    ]:
        try:
            if _login_context[key]:
                (
                    _login_context[key].close()
                    if key != "pw"
                    else _login_context[key].stop()
                )
        except:
            pass

        _login_context[key] = None

    gc.collect()


def _screenshot_base64(page):
    try:
        png = page.screenshot(
            full_page=False
        )

        return (
            "data:image/png;base64,"
            + base64.b64encode(png).decode()
        )

    except:
        return None


def _salvar_sessao_e_conta(
    username,
    profile_dir,
    password=""
):
    profile_path = (
        SESSIONS_DIR / profile_dir
    )

    profile_path.mkdir(
        parents=True,
        exist_ok=True
    )

    storage = (
        _login_context["context"]
        .storage_state()
    )

    def _importar_cookies():

        from playwright.sync_api import (
            sync_playwright as _sync_playwright
        )

        pw2 = _sync_playwright().start()

        try:
            ctx2 = (
                pw2.chromium
                .launch_persistent_context(
                    user_data_dir=str(profile_path),
                    headless=True,
                    storage_state=storage,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-setuid-sandbox",
                    ],
                )
            )

            ctx2.close()

            print(
                f"[ADMIN] cookies importados "
                f"para pasta do perfil @{username}",
                flush=True
            )

        except Exception as e:

            print(
                f"[ADMIN] AVISO: erro ao importar "
                f"cookies: {e}",
                flush=True
            )

        finally:
            pw2.stop()
            gc.collect()

    t = threading.Thread(
        target=_importar_cookies,
        daemon=True
    )

    t.start()
    t.join()

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
            "data_cadastro": (
                datetime.now()
                .strftime("%d/%m/%Y")
            ),
            "ultimo_login": (
                datetime.now().isoformat()
            ),
        })

    salvar_contas(contas)

    if password:
        salvar_senha_conta(
            username,
            password
        )

    login_status["screenshot"] = None

    print(
        f"[ADMIN] sessão salva para @{username}",
        flush=True
    )


def _limpar_status_apos_done():
    time.sleep(6)

    login_status.update(
        stage=None,
        message=None,
        screenshot=None,
        username=None,
        running=False
    )


def _aceitar_cookies(page):

    for texto in [
        "Permitir todos os cookies",
        "Allow all cookies",
        "Aceitar todos os cookies",
        "Accept all cookies"
    ]:

        try:

            btn = page.locator(
                f"text={texto}"
            ).first

            if btn.is_visible(
                timeout=3000
            ):

                btn.click()

                time.sleep(2)

                return

        except:
            continue


def _ja_logado(url):

    if "instagram.com" not in url:
        return False

    if (
        "/accounts/login" in url
        or "challenge" in url
        or "two_factor" in url
    ):
        return False

    return True


def _worker_login(
    username,
    password,
    profile_dir
):

    try:

        login_status["stage"] = (
            "logging_in"
        )

        login_status["message"] = (
            "Iniciando browser..."
        )

        login_status["screenshot"] = None

        print(
            "[ADMIN] worker iniciado",
            flush=True
        )

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

        storage_arg = (
            str(storage_file)
            if storage_file.exists()
            else None
        )

        pw = sync_playwright().start()

        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1400,900",
            ],
        )

        context_opts = dict(
            user_agent=UA,
            viewport={
                "width": 1400,
                "height": 900
            },
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            extra_http_headers={
                "Accept-Language":
                    "pt-BR,pt;q=0.9,en;q=0.8",

                "Accept":
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "image/avif,image/webp,"
                    "*/*;q=0.8",

                "Accept-Encoding":
                    "gzip, deflate, br",

                "Sec-Fetch-Dest":
                    "document",

                "Sec-Fetch-Mode":
                    "navigate",

                "Sec-Fetch-Site":
                    "none",

                "Sec-Fetch-User":
                    "?1",

                "Upgrade-Insecure-Requests":
                    "1",
            },
        )

        if storage_arg:
            context_opts[
                "storage_state"
            ] = storage_arg

        context = browser.new_context(
            **context_opts
        )

        page = context.new_page()

        page.set_default_timeout(
            60_000
        )

        page.add_init_script("""
            Object.defineProperty(
                navigator,
                'webdriver',
                { get: () => undefined }
            );

            Object.defineProperty(
                navigator,
                'plugins',
                { get: () => [1,2,3,4,5] }
            );

            Object.defineProperty(
                navigator,
                'languages',
                {
                    get: () => [
                        'pt-BR',
                        'pt',
                        'en-US'
                    ]
                }
            );

            window.chrome = {
                runtime: {}
            };
        """)

        _login_context["pw"] = pw
        _login_context["browser"] = browser
        _login_context["context"] = context
        _login_context["page"] = page

        login_status["message"] = (
            "Abrindo Instagram..."
        )

        for tentativa in range(2):

            try:

                page.goto(
                    "https://www.instagram.com/",
                    wait_until="domcontentloaded",
                    timeout=60_000
                )

                break

            except Exception as e:

                print(
                    f"[ADMIN] goto home tentativa "
                    f"{tentativa + 1} falhou: {e}",
                    flush=True
                )

                if tentativa == 1:
                    raise

                time.sleep(3)

        time.sleep(4)

        login_status["screenshot"] = (
            _screenshot_base64(page)
        )

        print(
            f"[ADMIN] URL após home: {page.url}",
            flush=True
        )

        if _ja_logado(page.url):

            print(
                "[ADMIN] sessão já ativa",
                flush=True
            )

            _salvar_sessao_e_conta(
                username,
                profile_dir,
                password
            )

            login_status["stage"] = "done"

            login_status["message"] = (
                "Login realizado com sucesso!"
            )

            _fechar_login_browser()

            login_status["running"] = False

            threading.Thread(
                target=_limpar_status_apos_done,
                daemon=True
            ).start()

            return

        _aceitar_cookies(page)

        if "/accounts/login" not in page.url:

            login_status["message"] = (
                "Navegando para login..."
            )

            page.goto(
                "https://www.instagram.com/accounts/login/",
                wait_until="domcontentloaded",
                timeout=60_000
            )

            time.sleep(4)

        login_status["screenshot"] = (
            _screenshot_base64(page)
        )

        url_atual = page.url

        print(
            f"[ADMIN] URL login: {url_atual}",
            flush=True
        )

        login_status["message"] = (
            "Aguardando formulário..."
        )

        campo_encontrado = False

        try:

            page.wait_for_selector(
                'input[name="username"]',
                timeout=30000
            )

            campo_encontrado = True

        except:
            pass

        if not campo_encontrado:

            login_status["screenshot"] = (
                _screenshot_base64(page)
            )

            print(
                f"[ADMIN] campo não encontrado. "
                f"URL: {page.url}",
                flush=True
            )

            page.evaluate(
                "window.scrollTo(0, 0)"
            )

            time.sleep(2)

            try:

                page.wait_for_selector(
                    'input[name="username"]',
                    timeout=30000
                )

                campo_encontrado = True

            except:
                pass

        if not campo_encontrado:

            login_status["stage"] = "error"

            login_status["message"] = (
                f"Página de login não carregou. "
                f"URL: {page.url} "
                "— veja o screenshot abaixo."
            )

            login_status["error"] = (
                "formulário não encontrado"
            )

            login_status["screenshot"] = (
                _screenshot_base64(page)
            )

            _fechar_login_browser()

            login_status["running"] = False

            return

        login_status["message"] = (
            "Preenchendo credenciais..."
        )

        page.fill(
            'input[name="username"]',
            username
        )

        time.sleep(0.5)

        page.fill(
            'input[name="password"]',
            password
        )

        time.sleep(0.5)

        page.click(
            'button[type="submit"]'
        )

        time.sleep(5)

        url_atual = page.url

        print(
            f"[ADMIN] URL após submit: {url_atual}",
            flush=True
        )

        if (
            "two_factor" in url_atual
            or "challenge" in url_atual
        ):

            login_status["stage"] = (
                "waiting_2fa"
            )

            login_status["message"] = (
                "Código de verificação necessário!"
            )

            return

        if _ja_logado(url_atual):

            _salvar_sessao_e_conta(
                username,
                profile_dir,
                password
            )

            login_status["stage"] = "done"

            login_status["message"] = (
                "Login realizado com sucesso!"
            )

            _fechar_login_browser()

            login_status["running"] = False

            threading.Thread(
                target=_limpar_status_apos_done,
                daemon=True
            ).start()

            return

        login_status["stage"] = "error"

        login_status["message"] = (
            "Usuário ou senha incorretos."
        )

        login_status["error"] = (
            "credenciais inválidas"
        )

        login_status["screenshot"] = (
            _screenshot_base64(page)
        )

        _fechar_login_browser()

        login_status["running"] = False

    except Exception as e:

        import traceback

        traceback.print_exc()

        print(
            f"[ADMIN] ERRO: {e}",
            flush=True
        )

        try:

            login_status["screenshot"] = (
                _screenshot_base64(
                    _login_context["page"]
                )
            )

        except:
            pass

        login_status["stage"] = "error"

        login_status["message"] = str(e)

        login_status["error"] = str(e)

        _fechar_login_browser()

        login_status["running"] = False


def remover_conta(username):

    salvar_contas([
        c
        for c in carregar_contas()
        if c["username"] != username
    ])


def obter_conta_livre():

    contas = carregar_contas()

    for conta in contas:

        if conta.get("status") == "livre":

            conta["status"] = "ocupado"

            salvar_contas(contas)

            return conta

    return None


def liberar_conta(username):

    contas = carregar_contas()

    for conta in contas:

        if conta["username"] == username:

            conta["status"] = "livre"

            conta["scrapes"] = (
                conta.get("scrapes", 0) + 1
            )

    salvar_contas(contas)


def limpar_cache_sessoes():

    """Remove apenas cache do Chromium, mantém cookies/sessão intactos."""

    pastas_cache = [
        "Cache",
        "Code Cache",
        "GPUCache",
        "DawnCache",
        "Service Worker",
        "CacheStorage",
        "blob_storage",
        "Network Persistent State",
    ]

    total_removido = 0

    for profile in SESSIONS_DIR.iterdir():

        if not profile.is_dir():
            continue

        for sub in profile.rglob("*"):

            if (
                sub.name in pastas_cache
                and sub.is_dir()
            ):

                try:

                    tamanho = sum(
                        f.stat().st_size
                        for f in sub.rglob("*")
                        if f.is_file()
                    )

                    shutil.rmtree(
                        sub,
                        ignore_errors=True
                    )

                    total_removido += tamanho

                except Exception:
                    pass

    return total_removido


def iniciar_login(
    username,
    password,
    profile_dir
):

    if login_status["running"]:

        return (
            False,
            "já existe login rodando"
        )

    if not username or not password:

        return (
            False,
            "usuário e senha obrigatórios"
        )

    login_status.update(
        running=True,
        username=username,
        profile_dir=profile_dir,
        error=None,
        stage=None,
        message=None,
        screenshot=None
    )

    threading.Thread(
        target=_worker_login,
        args=(
            username,
            password,
            profile_dir
        ),
        daemon=True
    ).start()

    return True, None


def enviar_codigo_2fa(code):

    if login_status["stage"] != "waiting_2fa":

        return (
            False,
            "nenhum login aguardando 2FA"
        )

    if not code:

        return (
            False,
            "código obrigatório"
        )

    def _submit_2fa():

        try:

            page = _login_context["page"]

            username = login_status["username"]

            profile_dir = (
                login_status["profile_dir"]
            )

            login_status["stage"] = (
                "logging_in"
            )

            login_status["message"] = (
                "Enviando código..."
            )

            page.wait_for_selector(
                'input[name="verificationCode"]',
                timeout=10000
            )

            page.fill(
                'input[name="verificationCode"]',
                code
            )

            time.sleep(0.5)

            page.click(
                'button[type="submit"]'
            )

            time.sleep(5)

            if _ja_logado(page.url):

                _salvar_sessao_e_conta(
                    username,
                    profile_dir
                )

                login_status["stage"] = (
                    "done"
                )

                login_status["message"] = (
                    "Login realizado com sucesso!"
                )

                threading.Thread(
                    target=_limpar_status_apos_done,
                    daemon=True
                ).start()

            else:

                login_status["stage"] = (
                    "error"
                )

                login_status["message"] = (
                    "Código incorreto ou expirado."
                )

                login_status["error"] = (
                    "código 2FA inválido"
                )

        except Exception as e:

            login_status["stage"] = "error"

            login_status["message"] = str(e)

            login_status["error"] = str(e)

        finally:

            _fechar_login_browser()

            login_status["running"] = False

    threading.Thread(
        target=_submit_2fa,
        daemon=True
    ).start()

    return True, None


def obter_status():

    return {
        **montar_status(),

        "login_status": {
            "running":
                login_status["running"],

            "stage":
                login_status["stage"],

            "message":
                login_status["message"],

            "error":
                login_status["error"],

            "screenshot":
                login_status["screenshot"],
        }
    }
