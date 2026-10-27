#!/usr/bin/env bash
# Deploy idempotente no Google Cloud Run. Uso: scripts/deploy/cloud_run.sh [.env.production]
# Pré-requisitos: gcloud autenticado (gcloud auth login) e Docker local.
set -euo pipefail

readonly ENV_FILE="${1:-.env.production}"
readonly REPOSITORY="chatbot"
readonly IMAGE_NAME="api"
readonly MIN_INSTANCES=1
readonly MAX_INSTANCES=2
readonly CONCURRENCY=40
readonly REQUEST_TIMEOUT_SECONDS=900
readonly CPU=1
readonly MEMORY="1Gi"
readonly TRUSTED_PROXY_HOPS=1
readonly SECRET_VARIABLES=(DATABASE_URL OPENAI_BASE_URL OPENAI_ACCESS_KEY API_ACCESS_TOKEN API_ADMIN_TOKEN)
readonly REQUIRED_VARIABLES=(GCP_PROJECT_ID GCP_REGION SERVICE_NAME OPENAI_RESPONSE_MODELS OPENAI_EMBEDDINGS_MODELS RAG_MIN_SCORE "${SECRET_VARIABLES[@]}")
readonly REQUIRED_SERVICES=(run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com)

log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'Erro: %s\n' "$*" >&2; exit 1; }

load_environment() {
  [[ -f "$ENV_FILE" ]] || fail "arquivo $ENV_FILE não encontrado (copie .env.production.example)."
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  local name
  for name in "${REQUIRED_VARIABLES[@]}"; do
    [[ -n "${!name:-}" ]] || fail "variável $name vazia em $ENV_FILE."
  done
}

secret_name() {
  local variable="$1"
  echo "${SERVICE_NAME}-${variable,,}" | tr '_' '-'
}

enable_services() {
  log "Habilitando APIs do projeto ${GCP_PROJECT_ID}"
  gcloud services enable "${REQUIRED_SERVICES[@]}" --project "$GCP_PROJECT_ID"
}

ensure_repository() {
  if ! gcloud artifacts repositories describe "$REPOSITORY" --location "$GCP_REGION" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    log "Criando repositório Artifact Registry ${REPOSITORY}"
    gcloud artifacts repositories create "$REPOSITORY" --repository-format docker \
      --location "$GCP_REGION" --project "$GCP_PROJECT_ID"
  fi
}

build_and_push_image() {
  local tag
  tag="$(git rev-parse --short HEAD)"
  IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${tag}"
  log "Build e push da imagem ${IMAGE}"
  gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev" --quiet
  docker build --platform linux/amd64 -t "$IMAGE" .
  docker push "$IMAGE"
}

upsert_secret() {
  local variable="$1" name
  name="$(secret_name "$variable")"
  if ! gcloud secrets describe "$name" --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets create "$name" --replication-policy automatic --project "$GCP_PROJECT_ID"
  fi
  printf '%s' "${!variable}" | gcloud secrets versions add "$name" --data-file - --project "$GCP_PROJECT_ID" >/dev/null
  gcloud secrets add-iam-policy-binding "$name" --project "$GCP_PROJECT_ID" \
    --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" --role roles/secretmanager.secretAccessor >/dev/null
}

sync_secrets() {
  log "Sincronizando segredos no Secret Manager"
  local project_number variable
  project_number="$(gcloud projects describe "$GCP_PROJECT_ID" --format 'value(projectNumber)')"
  RUNTIME_SERVICE_ACCOUNT="${project_number}-compute@developer.gserviceaccount.com"
  for variable in "${SECRET_VARIABLES[@]}"; do
    upsert_secret "$variable"
  done
}

secret_bindings() {
  local variable bindings=()
  for variable in "${SECRET_VARIABLES[@]}"; do
    bindings+=("${variable}=$(secret_name "$variable"):latest")
  done
  (IFS=,; echo "${bindings[*]}")
}

deploy_service() {
  log "Deploy do serviço ${SERVICE_NAME} (${GCP_REGION})"
  gcloud run deploy "$SERVICE_NAME" \
    --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --image "$IMAGE" \
    --allow-unauthenticated \
    --min-instances "$MIN_INSTANCES" --max-instances "$MAX_INSTANCES" \
    --no-cpu-throttling --cpu "$CPU" --memory "$MEMORY" \
    --concurrency "$CONCURRENCY" --timeout "$REQUEST_TIMEOUT_SECONDS" \
    --set-env-vars "^@^API_ENV=production@LOG_LEVEL=INFO@TRUSTED_PROXY_HOPS=${TRUSTED_PROXY_HOPS}@OPENAI_RESPONSE_MODELS=${OPENAI_RESPONSE_MODELS}@OPENAI_EMBEDDINGS_MODELS=${OPENAI_EMBEDDINGS_MODELS}@RAG_MIN_SCORE=${RAG_MIN_SCORE}" \
    --set-secrets "$(secret_bindings)"
}

smoke_test() {
  local url
  url="$(gcloud run services describe "$SERVICE_NAME" --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format 'value(status.url)')"
  log "Smoke test em ${url}"
  curl -fsS "${url}/health" && echo
  curl -fsS "${url}/ready" && echo
  curl -fsS "${url}/v1/models" -H "Authorization: Bearer ${API_ACCESS_TOKEN}" && echo
  log "Deploy concluído: ${url}"
}

main() {
  command -v gcloud >/dev/null || fail "gcloud não instalado."
  command -v docker >/dev/null || fail "docker não instalado."
  load_environment
  enable_services
  ensure_repository
  build_and_push_image
  sync_secrets
  deploy_service
  smoke_test
}

main "$@"
