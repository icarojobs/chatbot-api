#!/usr/bin/env bash
# Copia a base já ingerida localmente (banco chatbot_prod, embeddings de produção) para o Neon,
# sem gerar embeddings de novo. Uso: scripts/deploy/copy_db_to_neon.sh [.env.production]
# Pré-requisitos: `make up-prod` (ou `make up`) com o Postgres local no ar e `make ingest-prod-local` feito.
set -euo pipefail

readonly ENV_FILE="${1:-.env.production}"
readonly SOURCE_DATABASE="chatbot_prod"
readonly DATA_TABLES=(documents chunks chunk_embeddings)
readonly COUNT_QUERY="SELECT (SELECT count(*) FROM documents) || ' documentos, ' || (SELECT count(*) FROM chunks) || ' trechos, ' || (SELECT count(*) FROM chunk_embeddings) || ' embeddings'"

log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'Erro: %s\n' "$*" >&2; exit 1; }

load_environment() {
  [[ -f "$ENV_FILE" ]] || fail "arquivo $ENV_FILE não encontrado (copie .env.production.example)."
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  [[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL vazia em $ENV_FILE."
  NEON_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
  export NEON_URL
}

in_postgres() {
  docker compose exec -T -e NEON_URL postgres sh -c "$1"
}

neon_query() {
  in_postgres "psql \"\$NEON_URL\" -X -A -t -v ON_ERROR_STOP=1 -c \"$1\""
}

local_query() {
  in_postgres "psql -U \"\$POSTGRES_USER\" -d ${SOURCE_DATABASE} -X -A -t -c \"$1\""
}

migrate_neon() {
  log "Aplicando as migrations no Neon"
  API_ENV=production uv run python -m chatbot_api.db.migrate
}

ensure_empty_target() {
  local documents
  documents="$(neon_query "SELECT count(*) FROM documents")"
  [[ "$documents" == "0" ]] || fail "o Neon já tem ${documents} documento(s); a cópia só roda num banco vazio."
}

copy_data() {
  local tables=""
  for table in "${DATA_TABLES[@]}"; do
    tables+=" -t ${table}"
  done
  log "Copiando ${SOURCE_DATABASE} → Neon (${DATA_TABLES[*]})"
  in_postgres "pg_dump -U \"\$POSTGRES_USER\" -d ${SOURCE_DATABASE} --data-only --no-owner${tables} | psql \"\$NEON_URL\" -X -q -v ON_ERROR_STOP=1 --single-transaction -o /dev/null"
}

main() {
  command -v docker >/dev/null || fail "docker não instalado."
  command -v uv >/dev/null || fail "uv não instalado."
  load_environment
  log "Origem (local): $(local_query "$COUNT_QUERY")"
  migrate_neon
  ensure_empty_target
  copy_data
  log "Destino (Neon): $(neon_query "$COUNT_QUERY")"
}

main "$@"
