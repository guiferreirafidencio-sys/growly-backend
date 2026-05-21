# account_manager.py
# =========================================================
# GERENCIADOR DE CONTAS INSTAGRAM
# =========================================================
#
# RESPONSABILIDADES:
#   - Carregar e salvar contas do contas.json
#   - Marcar conta como ocupada antes de usar
#   - Liberar conta após scraping
#   - Marcar conta como banida quando necessário
#   - Fornecer a próxima conta disponível
#
# COMO FUNCIONA A DISTRIBUIÇÃO:
#   Quando scrape_url() precisa de uma conta, chama
#   obter_conta_livre(). Essa função:
#     1. Lê contas.json
#     2. Filtra contas com status == "livre"
#     3. Escolhe a conta com MENOS scrapes feitos
#        (balanceamento por uso acumulado)
#     4. Marca como "ocupado" e salva
#     5. Retorna os dados da conta
#
#   Após o scrape, liberar_conta() é chamada e
#   o status volta para "livre" + scrapes += 1
#
# COMO ADICIONAR NOVAS CONTAS:
#   Use o admin_config.py (rota /admin/config/login-instagram)
#   que já cuida de:
#     - Abrir Playwright headful
#     - Aguardar login manual
#     - Salvar storage.json na pasta da conta
#     - Inserir a conta no contas.json via salvar_contas()
#
# =========================================================

import json
import threading
from pathlib import Path
from datetime import datetime

# =========================================================
# CAMINHOS
# =========================================================

BASE_DIR     = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
CONFIG_FILE  = SESSIONS_DIR / "contas.json"

# Lock global para evitar race condition ao ler/salvar JSON
# quando múltiplas threads tentam pegar conta ao mesmo tempo
_json_lock = threading.Lock()

# =========================================================
# HELPERS JSON
# =========================================================

def carregar_contas() -> list[dict]:
    """
    Lê contas.json e retorna a lista de contas.
    Se o arquivo não existir, cria um vazio.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    with _json_lock:

        if not CONFIG_FILE.exists():
            CONFIG_FILE.write_text(
                json.dumps({"contas": []}, indent=4, ensure_ascii=False),
                encoding="utf-8"
            )

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    return data.get("contas", [])


def salvar_contas(contas: list[dict]) -> None:
    """
    Persiste a lista de contas no contas.json.
    Usa lock para evitar escrita simultânea.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    with _json_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"contas": contas}, f, indent=4, ensure_ascii=False)

# =========================================================
# OBTER CONTA LIVRE
# =========================================================

def obter_conta_livre() -> dict | None:
    """
    Retorna a conta mais ociosa disponível (status == "livre")
    e a marca como "ocupado" atomicamente.

    Critério de escolha: menor número de scrapes acumulados.
    Isso distribui a carga uniformemente entre as contas ao
    longo do tempo.

    Retorna None se não houver nenhuma conta disponível.
    """
    # Lock aqui garante que duas threads não peguem
    # a mesma conta ao mesmo tempo
    with _json_lock:

        if not CONFIG_FILE.exists():
            return None

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        contas = data.get("contas", [])

        # Filtra apenas as livres
        livres = [c for c in contas if c.get("status") == "livre"]

        if not livres:
            return None

        # Pega a com menos scrapes (balanceamento por uso)
        escolhida = min(livres, key=lambda c: c.get("scrapes", 0))

        # Marca como ocupado na lista principal
        for conta in contas:
            if conta["username"] == escolhida["username"]:
                conta["status"] = "ocupado"
                break

        # Salva sem usar o lock externo (já estamos dentro dele)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"contas": contas}, f, indent=4, ensure_ascii=False)

    return escolhida


# =========================================================
# LIBERAR CONTA
# =========================================================

def liberar_conta(username: str) -> None:
    """
    Após o scrape terminar (com sucesso ou erro),
    devolve a conta para o pool de disponíveis e
    incrementa o contador de scrapes.
    """
    with _json_lock:

        if not CONFIG_FILE.exists():
            return

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        contas = data.get("contas", [])

        for conta in contas:
            if conta["username"] == username:
                conta["status"] = "livre"
                conta["scrapes"] = conta.get("scrapes", 0) + 1
                break

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"contas": contas}, f, indent=4, ensure_ascii=False)


# =========================================================
# MARCAR COMO BANIDA
# =========================================================

def marcar_banida(username: str) -> None:
    """
    Quando Instagram bloqueia ou exige verificação,
    marca a conta como "banida" para que não seja
    mais usada automaticamente.

    O admin deve re-fazer o login para reativar.
    """
    with _json_lock:

        if not CONFIG_FILE.exists():
            return

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        contas = data.get("contas", [])

        for conta in contas:
            if conta["username"] == username:
                conta["status"] = "banida"
                break

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"contas": contas}, f, indent=4, ensure_ascii=False)


# =========================================================
# REATIVAR CONTA
# =========================================================

def reativar_conta(username: str) -> None:
    """
    Reativa uma conta banida ou presa em "ocupado"
    (útil após reinício do servidor quando um crash
    deixou a conta marcada como ocupada).
    """
    with _json_lock:

        if not CONFIG_FILE.exists():
            return

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        contas = data.get("contas", [])

        for conta in contas:
            if conta["username"] == username:
                conta["status"] = "livre"
                break

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"contas": contas}, f, indent=4, ensure_ascii=False)


# =========================================================
# STATUS GERAL
# =========================================================

def montar_status() -> dict:
    """
    Retorna um resumo do pool de contas para o painel admin.
    Compatível com o admin_config.py existente.
    """
    contas = carregar_contas()

    return {
        "total":         len(contas),
        "livres":        len([c for c in contas if c.get("status") == "livre"]),
        "ocupadas":      len([c for c in contas if c.get("status") == "ocupado"]),
        "banidas":       len([c for c in contas if c.get("status") == "banida"]),
        "total_scrapes": sum(c.get("scrapes", 0) for c in contas),
        "contas":        contas
    }


# =========================================================
# CAMINHO DA SESSÃO
# =========================================================

def caminho_sessao(profile_dir: str) -> Path:
    """
    Retorna o Path completo da pasta de sessão de uma conta.
    Ex: sessions/ig_profile_conta1
    """
    return SESSIONS_DIR / profile_dir
