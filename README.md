# Growly Backend

## Estrutura

- `main.py`: ponto de entrada Flask, mantido na raiz para o comando de deploy.
- `app/`: pasta-mãe de todo o código da aplicação.
  - `config/`: variáveis de ambiente e configuração Flask.
  - `database/`: SQLAlchemy e modelos (`User` e `Analise`).
  - `routes/`: páginas e APIs por funcionalidade.
  - `services/`: chat e integrações externas.
  - `scraper/`: motor do antigo `bot.py` e sua API pública.
  - `storage/`: caminhos de sessões, banco local e logs.
  - `account_manager.py`: controle atômico das contas do Instagram.
- `assets/`, `templates/` e `static/`: arquivos visuais no mesmo nível; Flask usa `templates/` e `static/`.

## Execução

Instale as dependências com `pip install -r requirements.txt`. Para o scraper,
execute também `playwright install chromium`. Em seguida, rode `flask --app main run`
ou `gunicorn main:app` em produção.

## Variáveis de ambiente

Configure `SECRET_KEY`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_SECRET` e
`REDIRECT_URI`. As chaves de IA aceitam `GEMINI_API_1` a `GEMINI_API_10` e
`OPENROUTER_API_1` a `OPENROUTER_API_5`.
