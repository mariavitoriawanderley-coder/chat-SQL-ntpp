# Alvos do dia a dia. Testado no Git Bash (Windows) e em shell POSIX.
#
# O `make` não vem com o Windows. Se não tiver, cada alvo abaixo é um comando
# só — copie a linha. Para instalar: winget install GnuWin32.Make

PROJETO   ?= consultas-consuleg
REGIAO    ?= southamerica-east1
SERVICO   ?= consulta-dados-publicos
CONTA     ?= sa-consulta-dados

PY        := .venv/Scripts/python
PIP       := .venv/Scripts/pip

.PHONY: ajuda instalar dev-api dev-web build-web build testar lint formatar \
        validar-catalogo importar-temas limpar preparar-gcp implantar logs

ajuda:
	@echo "instalar          cria a .venv, instala Python e Node"
	@echo "dev-api           uvicorn com reload na 8000"
	@echo "dev-web           vite na 5173, com proxy /api para a 8000"
	@echo "build-web         compila o front para static/ (front servido pelo FastAPI)"
	@echo "validar-catalogo  valida os YAML do catálogo e lista o que foi lido"
	@echo "importar-temas    regera o mapa de temas a partir da planilha das comissões"
	@echo "testar            pytest"
	@echo "lint              ruff + biome"
	@echo "preparar-gcp      habilita APIs e cria a service account (roda uma vez)"
	@echo "implantar         gcloud run deploy --source ."

# ─── Desenvolvimento ──────────────────────────────────────────────────────
instalar:
	python -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	cd web && npm install

dev-api:
	$(PY) -m uvicorn app.main:app --reload --app-dir src --port 8000

dev-web:
	cd web && npm run dev

# ─── Build ────────────────────────────────────────────────────────────────
build-web:
	cd web && npm run build
	rm -rf static
	cp -r web/dist static

# Front compilado + servidor único, exatamente como roda em produção.
build: build-web
	$(PY) -m uvicorn app.main:app --app-dir src --port 8000

# Roda a mesma validação do startup, sem subir servidor. Use a cada arquivo
# salvo enquanto cadastra tabela — ele aponta arquivo e campo de cada erro.
validar-catalogo:
	PYTHONPATH=src $(PY) -m app.cli validar-catalogo

# Regera src/app/temas/comissoes.yaml a partir de dados/temas_comissoes_alepe.xlsx.
# Rode a cada alteração na planilha e versione os dois arquivos juntos.
importar-temas:
	PYTHONPATH=src $(PY) -m app.cli importar-temas

testar:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests
	cd web && npm run lint

formatar:
	$(PY) -m ruff format src tests
	cd web && npm run format

limpar:
	rm -rf static web/dist .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# ─── Publicação ───────────────────────────────────────────────────────────
# Roda uma vez por projeto. Cria a identidade com exatamente os dois papéis
# que a aplicação precisa — sem chave JSON, o Cloud Run injeta a identidade.
preparar-gcp:
	gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
	    artifactregistry.googleapis.com bigquery.googleapis.com \
	    secretmanager.googleapis.com --project=$(PROJETO)
	gcloud iam service-accounts create $(CONTA) \
	    --display-name="Consulta a dados públicos" --project=$(PROJETO) || true
	gcloud projects add-iam-policy-binding $(PROJETO) \
	    --member="serviceAccount:$(CONTA)@$(PROJETO).iam.gserviceaccount.com" \
	    --role="roles/bigquery.jobUser" --condition=None
	gcloud projects add-iam-policy-binding $(PROJETO) \
	    --member="serviceAccount:$(CONTA)@$(PROJETO).iam.gserviceaccount.com" \
	    --role="roles/bigquery.dataViewer" --condition=None

implantar:
	gcloud run deploy $(SERVICO) \
	    --source . \
	    --project=$(PROJETO) \
	    --region=$(REGIAO) \
	    --service-account=$(CONTA)@$(PROJETO).iam.gserviceaccount.com \
	    --allow-unauthenticated \
	    --memory=1Gi --cpu=1 --timeout=300 --concurrency=40 \
	    --min-instances=0 --max-instances=5 \
	    --set-env-vars=AMBIENTE=producao,GOOGLE_CLOUD_PROJECT=$(PROJETO),BQ_LOCATION=US

logs:
	gcloud run services logs read $(SERVICO) \
	    --project=$(PROJETO) --region=$(REGIAO) --limit=50
