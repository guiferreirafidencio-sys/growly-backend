FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Chromium já vem na imagem base — não precisa instalar de novo
COPY . .

CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "1", "--worker-class", "gthread", "--threads", "4"]