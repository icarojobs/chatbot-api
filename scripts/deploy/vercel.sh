#!/usr/bin/env bash
# Configuração da API na Vercel. Uso:
#   scripts/deploy/vercel.sh env [.env.production]           grava as variáveis de produção no projeto vinculado
#   scripts/deploy/vercel.sh smoke <url> [.env.production]   testa /health, /ready e /v1/models
# Pré-requisitos: Node.js (npx), `vercel login` e `vercel link` feitos uma vez.
set -euo pipefail

readonly VERCEL=(npx --yes vercel@64.0.2)
readonly TARGET="production"
readonly SECRET_VARIABLES=(DATABASE_URL OPENAI_BASE_URL OPENAI_ACCESS_KEY API_ACCESS_TOKEN API_ADMIN_TOKEN)
readonly CONFIG_VARIABLES=(OPENAI_RESPONSE_MODELS OPENAI_EMBEDDINGS_MODELS)
# Fixed by the platform: Vercel overwrites X-Forwarded-For with the client IP (1 hop) and caps
# request bodies at 4.5 MB, so direct uploads stay at 4 MiB (larger files use the chunked upload).
readonly PLATFORM_VARIABLES=(API_ENV=production LOG_LEVEL=INFO TRUSTED_PROXY_HOPS=1 DIRECT_UPLOAD_MAX_BYTES=4194304)

log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'Erro: %s\n' "$*" >&2; exit 1; }

load_environment() {
  local env_file="$1" name
  [[ -f "$env_file" ]] || fail "arquivo $env_file não encontrado (copie .env.production.example)."
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  for name in "${SECRET_VARIABLES[@]}" "${CONFIG_VARIABLES[@]}"; do
    [[ -n "${!name:-}" ]] || fail "variável $name vazia em $env_file."
  done
}

put_variable() {
  local name="$1" value="$2" kind="$3"
  printf '%s' "$value" | "${VERCEL[@]}" env add "$name" "$TARGET" --force "--$kind" >/dev/null
  printf '  %s (%s)\n' "$name" "$kind"
}

sync_environment() {
  load_environment "$1"
  log "Gravando variáveis de ${TARGET} na Vercel (valores não são exibidos)"
  local name pair
  for name in "${SECRET_VARIABLES[@]}"; do
    put_variable "$name" "${!name}" sensitive
  done
  for name in "${CONFIG_VARIABLES[@]}"; do
    put_variable "$name" "${!name}" no-sensitive
  done
  for pair in "${PLATFORM_VARIABLES[@]}"; do
    put_variable "${pair%%=*}" "${pair#*=}" no-sensitive
  done
  log "Pronto. As variáveis valem a partir do próximo deploy."
}

smoke_test() {
  local url="${1%/}"
  [[ -n "$url" ]] || fail "informe a URL da API."
  load_environment "$2"
  log "Smoke test em ${url}"
  curl -fsS "${url}/health" && echo
  curl -fsS "${url}/ready" && echo
  curl -fsS "${url}/v1/models" -H "Authorization: Bearer ${API_ACCESS_TOKEN}" && echo
}

main() {
  command -v npx >/dev/null || fail "Node.js (npx) não instalado."
  case "${1:-}" in
    env) sync_environment "${2:-.env.production}" ;;
    smoke) smoke_test "${2:-}" "${3:-.env.production}" ;;
    *) fail "uso: $0 env [.env.production] | smoke <url> [.env.production]" ;;
  esac
}

main "$@"
