.DEFAULT_GOAL := help
.PHONY: help sync install run test lint format typecheck check up up-prod down logs deploy ingest-prod evaluate redteam ingest ingest-prod-local

MERGED_PR_LIMIT := 200

help: ## Lista os comandos disponíveis
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

sync: ## Atualiza a main e remove branches locais de PRs já mergeados
	git fetch --prune
	git checkout main
	git pull --ff-only
	gh pr list --state merged --limit $(MERGED_PR_LIMIT) --json headRefName -q '.[].headRefName' \
		| while read -r branch; do git branch -D "$$branch" 2>/dev/null || true; done

install: ## Instala as dependências (inclusive de desenvolvimento)
	uv sync --frozen

run: ## Sobe a API localmente com reload
	uv run uvicorn --factory chatbot_api.main:create_app --reload --port 8000

test: ## Executa os testes com cobertura (mínimo 95%)
	uv run pytest

lint: ## Verifica lint e formatação
	uv run ruff check .
	uv run ruff format --check .

format: ## Formata o código e aplica correções automáticas
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## Verifica tipos com mypy (strict)
	uv run mypy src tests

check: lint typecheck test ## Lint + tipos + testes (o mesmo que a CI)

PROD_LOCAL_DATABASE := chatbot_prod
PROD_LOCAL_ENV := DOCKER_API_ENV=production DOCKER_API_DATABASE=$(PROD_LOCAL_DATABASE)
INGEST_IN_CONTAINER := docker compose run --rm -v "$(CURDIR)/docs/apostilas:/apostilas:ro" api python -m chatbot_api.ingest /apostilas

up: ## Sobe API (desenvolvimento: Ollama), Postgres e Ollama via Docker
	docker compose up -d --build

up-prod: ## Sobe a API local com o provedor real e o banco chatbot_prod (embeddings de produção)
	docker compose up -d --wait postgres
	docker compose exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '"'"'$(PROD_LOCAL_DATABASE)'"'"'" | grep -q 1 || createdb -U "$$POSTGRES_USER" $(PROD_LOCAL_DATABASE)'
	$(PROD_LOCAL_ENV) docker compose up -d --build api

down: ## Derruba os containers
	docker compose down

logs: ## Acompanha os logs da API
	docker compose logs -f api

ingest: ## Ingere docs/apostilas pelo container (sem uv no host)
	$(INGEST_IN_CONTAINER)

ingest-prod-local: ## Ingere docs/apostilas no banco chatbot_prod com o embedding de produção (gasta créditos)
	$(PROD_LOCAL_ENV) $(INGEST_IN_CONTAINER)

ENV_PRODUCTION := .env.production

deploy: ## Deploy no Cloud Run (requer gcloud autenticado e .env.production)
	scripts/deploy/cloud_run.sh $(ENV_PRODUCTION)

ingest-prod: ## Ingere docs/apostilas no banco de produção com o embedding de produção
	set -a && . ./$(ENV_PRODUCTION) && set +a && API_ENV=production uv run python -m chatbot_api.ingest docs/apostilas

evaluate: ## Avalia o retrieval (Hit@k, MRR, abstenção) e sugere o limiar de similaridade
	uv run python -m chatbot_api.evaluation

redteam: ## Ataca o RAG com prompt injection no ambiente do container (make up ou make up-prod)
	docker compose exec api python -m chatbot_api.redteam
