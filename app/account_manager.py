# account_manager.py
# =========================================================
# GERENCIADOR DE CONTAS INSTAGRAM
# =========================================================

import json
import threading
import base64
import shutil
from pathlib import Path
from datetime import datetime
from app.storage.paths import SESSIONS_DIR

CONFIG_FILE  = SESSIONS_DIR / "contas.json"

_json_lock = threading.Lock()


# =========================================================
# HELPERS JSON
# =========================================================

def _ler_dados() -> dict:
    if not CONFIG_FILE.exists():
        return {"contas": []}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _gravar_dados(data: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# =========================================================
# HELPERS DE SENHA (base64)
# =========================================================

def _encode_senha(senha: str) -> str:
    return base64.b64encode(senha.encode()).decode()


def _decode_senha(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


# =========================================================
# RESET NA INICIALIZAÇÃO
# =========================================================

def reset_contas_travadas() -> None:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        count  = 0
        for c in contas:
            if c.get("status") == "ocupado":
                c["status"] = "livre"
                count += 1
        if count:
            _gravar_dados(data)
            print(f"[ACCOUNT] {count} conta(s) liberada(s) após restart", flush=True)


# =========================================================
# CARREGAR / SALVAR
# =========================================================

def carregar_contas() -> list[dict]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with _json_lock:
        if not CONFIG_FILE.exists():
            _gravar_dados({"contas": []})
        return _ler_dados().get("contas", [])


def salvar_contas(contas: list[dict]) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with _json_lock:
        _gravar_dados({"contas": contas})


# =========================================================
# SALVAR SENHA
# =========================================================

def salvar_senha_conta(username: str, senha: str) -> None:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        for c in contas:
            if c["username"] == username:
                c["senha_b64"] = _encode_senha(senha)
                break
        _gravar_dados(data)
        print(f"[ACCOUNT] senha salva para @{username}", flush=True)


# =========================================================
# OBTER CONTA LIVRE (atômico)
# =========================================================

def obter_conta_livre() -> dict | None:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        livres = [c for c in contas if c.get("status") == "livre"]

        if not livres:
            return None

        escolhida = min(livres, key=lambda c: c.get("scrapes", 0))

        for c in contas:
            if c["username"] == escolhida["username"]:
                c["status"] = "ocupado"
                break

        _gravar_dados(data)
        return dict(escolhida)


# =========================================================
# LIBERAR CONTA
# =========================================================

def liberar_conta(username: str) -> None:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        alterou = False

        for c in contas:
            if c["username"] == username:
                if c.get("status") == "ocupado":
                    c["status"]  = "livre"
                    c["scrapes"] = c.get("scrapes", 0) + 1
                    alterou = True
                break

        if alterou:
            _gravar_dados(data)


# =========================================================
# MARCAR BANIDA / REATIVAR
# =========================================================

def marcar_banida(username: str) -> None:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        for c in contas:
            if c["username"] == username:
                c["status"] = "banida"
                break
        _gravar_dados(data)


def reativar_conta(username: str) -> None:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        for c in contas:
            if c["username"] == username:
                c["status"] = "livre"
                break
        _gravar_dados(data)


# =========================================================
# AUTO-RELOGIN EM BACKGROUND
# =========================================================

def relogar_conta_em_background(username: str) -> bool:
    with _json_lock:
        data   = _ler_dados()
        contas = data.get("contas", [])
        conta  = next((c for c in contas if c["username"] == username), None)

    if not conta:
        print(f"[ACCOUNT] relogin: conta @{username} não encontrada", flush=True)
        return False

    senha_b64 = conta.get("senha_b64", "")
    if not senha_b64:
        print(f"[ACCOUNT] relogin: @{username} sem senha salva — faça login manual", flush=True)
        return False

    senha       = _decode_senha(senha_b64)
    profile_dir = conta.get("profile_dir", f"ig_profile_{username}")

    def _fazer_relogin():
        print(f"[ACCOUNT] relogin automático iniciando para @{username}...", flush=True)
        try:
            # ✅ Deleta a pasta INTEIRA do perfil para forçar sessão 100% limpa
            # O launch_persistent_context guarda cookies na pasta, não só no storage.json
            profile_path = SESSIONS_DIR / profile_dir
            if profile_path.exists():
                shutil.rmtree(profile_path)
                print(f"[ACCOUNT] perfil antigo deletado para @{username}", flush=True)

            from app.routes.admin_config import _worker_login
            _worker_login(username, senha, profile_dir)
            print(f"[ACCOUNT] relogin automático concluído para @{username}", flush=True)
        except Exception as e:
            print(f"[ACCOUNT] relogin automático FALHOU para @{username}: {e}", flush=True)

    t = threading.Thread(target=_fazer_relogin, daemon=True, name=f"relogin-{username}")
    t.start()
    return True


# =========================================================
# STATUS GERAL
# =========================================================

def montar_status() -> dict:
    contas = carregar_contas()
    return {
        "total":         len(contas),
        "livres":        len([c for c in contas if c.get("status") == "livre"]),
        "ocupadas":      len([c for c in contas if c.get("status") == "ocupado"]),
        "banidas":       len([c for c in contas if c.get("status") == "banida"]),
        "total_scrapes": sum(c.get("scrapes", 0) for c in contas),
        "contas":        contas,
    }


# =========================================================
# CAMINHO DE SESSÃO
# =========================================================

def caminho_sessao(profile_dir: str) -> Path:
    return SESSIONS_DIR / profile_dir
