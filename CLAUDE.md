# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos

```bash
make sync        # rotina de abertura: atualiza a main e remove branches de PRs mergeados
make install     # uv sync --frozen (Python 3.14 + deps de dev)
make run         # API local com reload em :8000 (uvicorn --factory chatbot_api.main:create_app)
make check       # ruff + mypy strict + pytest com --cov-fail-under=95 (o mesmo que a CI)
make ingest      # ingere docs/apostilas pelo container (sem uv no host)
make evaluate    # avaliação do retrieval (Hit@k, MRR, abstenção) e limiar sugerido
make redteam     # 16 ataques de prompt injection no ambiente do container (ADR-0008); falha se algum passar
make deploy-env  # grava as variáveis do .env.production na Vercel (deploy é automático a cada merge na main; ver docs/hospedagem/DEPLOY.md)
make copy-db-neon  # copia a base local chatbot_prod para o Neon vazio (sem reingerir)
make ingest-prod # ingere docs/apostilas no Neon com o embedding de produção
make up / down   # docker compose: api, postgres (pgvector) e ollama (+ ollama-models baixa os modelos de dev)
make up-prod     # API local em API_ENV=production (provedor real, banco chatbot_prod); make up volta ao dev
make ingest-prod-local  # embeddings de produção no banco chatbot_prod (gasta créditos)
uv run pytest tests/integration/test_health.py::test_health_is_ok   # um teste específico
uv run python -m chatbot_api.ingest docs/apostilas                  # ingere PDFs (idempotente)
uv run python -m chatbot_api.db.migrate                             # aplica migrations (o container já roda no start)
```

Os testes de integração usam um Postgres real: `TEST_DATABASE_URL` no `.env` (banco `chatbot_test`, criado com `docker compose exec postgres createdb -U chatbot chatbot_test`). A fixture de sessão recria o schema e roda as migrations; cada teste com `session_factory` trunca as tabelas ao final.

Portas do host são configuráveis no `.env` (`API_HOST_PORT`, `POSTGRES_HOST_PORT`, `OLLAMA_HOST_PORT`); nesta máquina a 5432 é usada por outro projeto, então o Postgres sobe na 5433. GPU para o Ollama: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up` (requer NVIDIA Container Toolkit, não instalado aqui).

## Arquitetura da fundação

- `create_app(settings)` em `src/chatbot_api/main.py` monta tudo; testes injetam `Settings` (ver `tests/conftest.py`) e nunca leem o `.env`.
- Middlewares são **ASGI puros** (`core/logging.py`, `core/rate_limit.py`) para não bufferizar o streaming SSE — não use `BaseHTTPMiddleware` nem slowapi (ver ADR-0001).
- Todo erro sai no formato da OpenAI via `core/errors.py`; levante `ApiError` em vez de `HTTPException`.
- Auth: dependências `require_access_token` / `require_admin_token` (`core/security.py`).
- Rate limit global por IP; atrás de proxy, `TRUSTED_PROXY_HOPS` define qual entrada do `X-Forwarded-For` é confiável.
- `/ready` executa as funções em `app.state.readiness_checks` — novas dependências (banco, provedor) registram seu check ali.
- Provedores (`providers/`): contratos `ChatModelProvider`/`EmbeddingProvider` e um único `OpenAICompatibleProvider` (SDK `openai`, que usa `httpx2` — nos testes use `httpx2.MockTransport`). `build_provider_profile` escolhe Ollama (dev) ou o provedor real (prod) pelo `API_ENV`; o cliente vive no lifespan (`app.state.provider`). `ProviderProfile.models` tipa cada modelo como `chat` ou `embedding` (campo `type` em `/v1/models`); só `chat` é aceito em `model` no chat (`400 invalid_model_type`). Erros do SDK viram `ApiError` seguros em `providers/errors.py`.
- Dados (`db/`, ADR-0003): `documents` → `chunks` (com `page_start`/`page_end`) → `chunk_embeddings` (chave `chunk_id` + `embedding_model`, coluna `vector` sem dimensão fixa; sem HNSW de propósito). Ingestão (`ingestion/`): `extract_pages` (pypdf + `normalize_text`, que restaura ligaduras fi/fl perdidas) → `chunk_pages` (frases, ~1500 chars) → `IngestionService` idempotente por SHA-256 e retomável. Mudou normalização/chunking? Os PDFs já ingeridos não são reprocessados — trunque `documents` e reingira.
- Upload (`uploads/service.py` + `api/routes/documents.py`, token admin): sessão → partes de 4 MiB guardadas em `upload_parts` (bytea, sobrevivem a restart/multi-instância) → `complete` valida SHA-256 e magic bytes, chama `IngestionService.store` e agenda `embed_pending` via `BackgroundTasks`. Nos testes, reduza `PART_SIZE_BYTES` com monkeypatch nos dois módulos. Upload direto (`POST /v1/documents?filename=`, corpo binário até `DIRECT_UPLOAD_MAX_BYTES`) usa o mesmo `UploadService.store_file`. Exclusão: `DELETE /v1/documents/{id}` (cascata em chunks/embeddings) e reset `DELETE /v1/documents?confirm=true`, desabilitado em produção salvo `DOCUMENTS_RESET_ENABLED=true`; embedding em background de documento já excluído é ignorado (`background_embedding_skipped`).
- Pytest roda com `filterwarnings = error`: conexões não fechadas quebram a suíte — apps de teste devem vir de `app_factory` (descarta a engine).
- RAG (`rag/`, ADR-0004): `RAGNodes` (dependências injetadas; `Retriever` é Protocol) → `build_rag_graph` → `RAGService.stream` emite `TextDelta`/`AnswerCompleted(sources, abstained)`. Sem trecho com cosseno ≥ `RAG_MIN_SCORE` ⇒ abstenção sem chamar o LLM. O limiar é calibrado por modelo de embedding em `providers/profile.py::CALIBRATED_MIN_SCORES` (bge-m3 0,47; cohere/embed-v4.0 0,27 — ADR-0006); trocar o modelo de embedding exige reingestão + `make evaluate` + registrar o novo valor. Mensagens `system`/`developer` do cliente viram "INSTRUÇÕES DO CLIENTE" anexadas ao `SYSTEM_PROMPT` (tom/formato/idioma; as regras da API prevalecem), e um lembrete após a PERGUNTA reforça idioma e instruções (modelos pequenos seguem melhor o fim do prompt). A resposta sai no idioma da pergunta; as regras de pt-br do `COMPORTAMENTO_DA_IA.md` valem para o desenvolvimento, não para as respostas da API. Prompt injection (ADR-0008): `rag/guard.py::detect_injection` roda em `validate_input` (pergunta + instruções → nó `refuse`, sem LLM) e em `evaluate_context` (descarta trechos envenenados); o prompt usa blocos `<documentos>`/`<pergunta>`/`<instrucoes_do_cliente>` e `neutralize` remove essas tags do texto não confiável. Mudou prompt, filtro ou modelo? Rode `make redteam` em dev e prod; novos ataques vão em `redteam_cases.py`. Script manual de ponta a ponta: `playground/rag_e2e.py`.
- Chat (`api/routes/chat.py`): `POST /v1/chat/completions` no formato OpenAI (stream e não-stream) com extras `sources`/`abstained`. O primeiro evento do RAG é aguardado antes de abrir o stream, para erros iniciais virarem status HTTP; erros depois disso viram `data: {"error": …}` (sem `[DONE]`). `tests/integration/test_chat.py` usa o SDK oficial da OpenAI via `httpx2.ASGITransport`.
- Provedor real validado (ver ADR-0002): embeddings `cohere/embed-v4.0` com 1536 dimensões; `azure/gpt-5-mini` é modelo de raciocínio — use `max_completion_tokens` com folga (`LLM_MAX_OUTPUT_TOKENS`), senão a resposta sai vazia.

Stack (versões sempre pinadas, nunca `latest`): Python 3.14.x, uv 0.13.x, FastAPI 0.162.x (com docs automáticas), SDK `openai`, LangGraph 1.2.x, PostgreSQL + pgvector.

**O desenvolvimento segue `docs/planejamento/PLANO_DE_DESENVOLVIMENTO.md` (1 PR por fase, usando `.github/pull_request_template.md`). Decisões de base na `docs/RFC/RFC-0002.md` — consulte antes de propor algo que as contradiga.** Todas as fases do plano foram implementadas; os workflows `CI` (lint, tipos, testes) e `Security` (CodeQL, Semgrep, pip-audit, Gitleaks, Trivy) rodam em todo PR. A `main` é protegida: push direto e force push bloqueados (inclusive para admins), merge só via PR com os 6 checks verdes e branch atualizada; nunca desative esses workflows.

## Objetivo e arquitetura

API de chatbot com RAG sobre uma base de conhecimento prévia (apostilas de saúde mental em `docs/apostilas/*.pdf`, ignoradas pelo git). Requisitos centrais:

- Ingestão de documentos via API autenticada (upload em partes, para funcionar em qualquer hospedagem; ver `docs/hospedagem/DECISAO_TECNICA.md`) e via CLI, ambas usando o mesmo pipeline.
- Recuperação dos trechos relevantes (pgvector) → contexto para o LLM → resposta via streaming (SSE).
- Escolha do modelo entre os configurados, sem reescrever a integração; contrato idêntico ao da OpenAI (`POST /v1/chat/completions`, `GET /v1/models`), com as fontes num campo extra `sources`.
- Abster-se quando não houver evidência suficiente na base e expor as referências usadas.

Fluxo planejado (LangGraph `StateGraph`): validar entrada → embedding da pergunta → recuperar top-k chunks (pgvector) → avaliar suficiência → gerar resposta em streaming **ou** abster-se → finalizar metadados. O plano detalhado está em `playground/rag-chatbot-architecture.md` (não rastreado, rascunho local). Fora do escopo inicial: microserviços, filas/Redis, multiagentes, memória/checkpoint persistente, reranking/busca híbrida antes de medir a qualidade. Onde o rascunho diverge da RFC-0002 (SSE próprio, índice local, só CLI), vale a RFC.

Hospedagem (ADR-0010): Vercel (plano Hobby, runtime Python, região `gru1`) + Neon (`aws-sa-east-1`, conexão direta). Entrada em `src/chatbot_api/asgi.py`; migrations no build (`[tool.vercel.scripts]`); só a `main` publica. Limites: 4,5 MB por requisição (upload direto em produção = 4 MiB), 300 s por invocação. O Cloud Run (ADR-0005) foi abandonado após o bloqueio do faturamento do Google Cloud; o `Dockerfile` segue para o ambiente local.

### Configuração e ambientes

Variáveis em `.env` (não rastreado; exemplo em `.env.example`): `API_ENV`, `OPENAI_BASE_URL`, `OPENAI_ACCESS_KEY`, `OPENAI_RESPONSE_MODELS`, `OPENAI_EMBEDDINGS_MODELS`.

- `API_ENV=development` (padrão): Ollama (via docker compose, GPU GTX 1650 SUPER 4 GB) com `qwen3:4b-instruct-2507-q4_K_M` (chat, sem modo de raciocínio) e `bge-m3:567m` (embeddings), pelo mesmo adaptador compatível com OpenAI usado em produção.
- Embeddings de dev e prod têm modelos/dimensões diferentes e não são comparáveis: os vetores ficam separados por `embedding_model`.
- `API_ENV=production`: única situação em que o provedor real é chamado.
- Testes unitários sempre com mocks, usando apenas uma amostra dos modelos configurados.
- O endpoint é "compatível com OpenAI", mas não presuma que todos os parâmetros do SDK funcionam — valide com uma chamada pequena de embeddings e uma geração curta com streaming antes de processar a base inteira.

## Regras obrigatórias do projeto

Fonte: `docs/COMPORTAMENTO_DA_IA.md` (manter os dois arquivos em sincronia).

**Rotina de abertura de toda sessão (não precisa ser pedida):**
- `git checkout main && git pull`.
- Remover branches locais cujo PR já foi mergeado. Os PRs usam squash merge, então `git branch --merged` não detecta nada — confirme com `gh pr list --state merged`.
- Garantir que exista um `.mcp.json` na raiz com os MCP servers adequados ao projeto; **não escrever código sem ele**.

**Antes de executar qualquer pedido:** discutir em formato de RFC, com perguntas de múltipla escolha já trazendo a recomendação. Ao fim do debate, gerar `docs/RFC/RFC-XXXX` (numeração incremental a partir de 0001). Mudanças de impacto significativo também geram um ADR detalhado em pt-br em `docs/ADR/ADR-XXXX`.

**Código:**
- Idioma: toda UI em pt-br com acentuação correta; código, banco, migrations e infraestrutura em en-us.
- DRY, SOLID, Object Calisthenics; constantes no lugar de magic numbers/strings.
- Complexidade ciclomática: aninhamento acima de 2 níveis no escopo trabalhado deve ser refatorado (extrair funções) sem quebrar comportamento ou testes.
- Evitar comentários; só para regras de negócio de alta complexidade.
- Todo endpoint precisa de rate limiting.
- Vulnerabilidades encontradas: corrigir na hora e explicar o que foi feito.
- Nenhum secret em arquivos rastreados (usar `.env` + `.env.example`).
- Testes automatizados com cobertura mínima de 95% do codebase; tudo que for criado, corrigido ou refatorado precisa de testes.

**Documentação a manter atualizada:**
- `README.md`: profissional, com diagramas mermaid, descrição da base de conhecimento, decisões técnicas, como a IA foi usada (icarojobs como Arquiteto de Software; código gerado com Claude Code CLI + Opus 5.5) e passo a passo de execução com Docker em Linux, macOS e Windows WSL2.
- `docs/manuais/*`: manual de uso da API detalhado, passo a passo.

**Git / PR:**
- Fluxo sempre via branch → PR → merge → pull na `main`, com commits semânticos e descrição dos PRs em pt-br.
- Micro-commits a cada pequena etapa; um PR por módulo concluído.
- Commits e PRs autorados pelo usuário do `git config --global` — **nunca citar a IA como coautora/colaboradora** (sem `Co-Authored-By`, sem rodapé "Generated with Claude Code").
- `gh` já está configurado; usuário `icarojobs` (`gh auth switch --user icarojobs` se necessário).
- `playground/` é sempre não rastreado (scripts e dados temporários).
