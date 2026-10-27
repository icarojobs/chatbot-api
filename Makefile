.DEFAULT_GOAL := help
.PHONY: help sync install run test lint format typecheck check up down logs

MERGED_PR_LIMIT := 200

help: ## Lista os comandos disponíveis
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

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

up: ## Sobe API, Postgres e Ollama via Docker
	docker compose up -d --build

down: ## Derruba os containers
	docker compose down

logs: ## Acompanha os logs da API
	docker compose logs -f api
