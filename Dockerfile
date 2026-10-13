# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────────────
# Estágio 1 — o Node compila o front e some. Nada de Node na imagem final.
# ─────────────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS front

WORKDIR /front

# package.json e lock antes do código: o npm ci só reexecuta quando as
# dependências mudam, não a cada edição de componente.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


# ─────────────────────────────────────────────────────────────────────────────
# Estágio 2 — runtime Python.
# 3.14 e não o 3.12 do plano: é a versão do venv de desenvolvimento, e manter
# as duas iguais evita a classe de bug que só aparece dentro do container.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    AMBIENTE=producao

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY --from=front /front/dist/ ./static/

# Sem root. O Cloud Run não exige, mas um container que roda como root só
# aumenta o estrago de qualquer falha na aplicação.
RUN useradd --system --uid 10001 --no-create-home app \
    && chown -R app:app /app
USER app

EXPOSE 8080

# O Cloud Run injeta PORT. O shell precisa expandi-la, daí a forma exec com sh.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-server-header"]
