# Deploy em produção (Cloud Run + Neon)

Decisão registrada no [ADR-0005](../ADR/ADR-0005.md). Tempo estimado: ~20 minutos na primeira vez.

## 1. Pré-requisitos

- Conta Google Cloud com **faturamento ativo** (o uso fica dentro da franquia gratuita, exceto a instância mínima — ver custos abaixo).
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) instalada e Docker rodando.
- Conta no [Neon](https://neon.tech) (plano gratuito).

## 2. Banco no Neon

1. Crie um projeto (região próxima de `southamerica-east1`, ex.: AWS São Paulo).
2. Copie a connection string **direta** (sem `-pooler` no host) e troque o prefixo `postgresql://` por `postgresql+psycopg://`, mantendo `?sslmode=require`.

A extensão `vector` e as tabelas são criadas automaticamente pelas migrations no start do container.

## 3. Projeto no Google Cloud

```bash
gcloud auth login
gcloud projects create <id-do-projeto>        # ou use um existente
gcloud billing projects link <id-do-projeto> --billing-account <conta-de-faturamento>
```

## 4. Configuração

```bash
cp .env.production.example .env.production   # ignorado pelo git
openssl rand -hex 32                           # gere API_ACCESS_TOKEN e API_ADMIN_TOKEN novos
```

Preencha `GCP_PROJECT_ID`, `DATABASE_URL` (Neon), as credenciais do provedor e `RAG_MIN_SCORE` (valor calibrado para o embedding de produção no ADR-0006).

## 5. Ingestão das apostilas no banco de produção

```bash
make ingest-prod
```

Gera os embeddings com `cohere/embed-v4.0` (idempotente: pode rodar de novo sem custo extra). Alternativa: enviar os PDFs pela API depois do deploy (manual, seção Documentos).

## 6. Deploy

```bash
make deploy
```

O script (`scripts/deploy/cloud_run.sh`) é idempotente: habilita as APIs, cria o repositório no Artifact Registry, faz build/push da imagem (tag = commit atual), grava os segredos no Secret Manager, faz o deploy e roda um smoke test em `/health`, `/ready` e `/v1/models`.

Configuração aplicada no Cloud Run:

| Parâmetro | Valor | Motivo |
|---|---|---|
| `--min-instances` | 1 | Sem cold start durante a avaliação |
| `--no-cpu-throttling` | — | Embeddings de uploads rodam em background após a resposta |
| `--timeout` | 900 s | Respostas em streaming longas |
| `--concurrency` | 40 | Streams simultâneos por instância |
| `--max-instances` | 2 | Limita custo e conexões no Neon |
| `TRUSTED_PROXY_HOPS` | 1 | IP real do cliente para o rate limit (entrada do Google Front End) |
| Segredos | Secret Manager | `DATABASE_URL`, chave do provedor e tokens nunca ficam na imagem |

## 7. Teste pela URL pública

```bash
curl -N https://<url-do-servico>/v1/chat/completions \
  -H "Authorization: Bearer $API_ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"stream": true, "messages": [{"role": "user", "content": "O que é matriciamento?"}]}'
```

## Custos e limites

- `min-instances=1` com CPU sempre alocada **sai da franquia gratuita** (custo baixo, proporcional ao tempo ligado). Para custo zero, use `MIN_INSTANCES=0` no script, aceitando cold start de alguns segundos.
- O Neon free suspende o banco após inatividade: a primeira consulta depois disso leva ~1 s a mais (o pool reconecta sozinho).
- Rate limit em memória vale por instância (com `max-instances=2`, o limite efetivo pode dobrar).
