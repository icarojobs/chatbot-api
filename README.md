# CHATBOT API

O "ChatBot API" é uma API de Chatbot construída essencialmente com Python, FastAPI, RAG e LangGraph. A API do ChatBot deve responder perguntas com base em uma base de conhecimentos prévia, utilizando RAG.

---

## CORE BUSINESS
- Carregar e preparar documentos via API para consultas;
- Recuperar os trechos relevantes da base a partir da pergunta do usuário;
- Enviar esses trechos como contexto para um modelo de linguagem gerar a resposta;
- Entregar a resposta em tempo real via streaming;
- Permitir escolher entre os modelos de linguagem disponíveis, sem precisar reescrever a integração;
- Formato de chamada idêntico ao da API da OpenAI.

---

## INFORMAÇÕES TÉCNICAS
As chaves de acesso devem ficar no arquivo .env na raiz do projeto e sem serem rastreadas pelo git.

Acesso aos modelos:
- Base URL e chave de acesso em local seguro e não rastreável (.env)

Materiais/apostilas exemplos RAG:
- Estão localizadas em "docs/apostilas/*.pdf".

---

## SEGURANÇA (CI)
O workflow `.github/workflows/security.yml` bloqueia o merge em achados HIGH/CRITICAL (em PR, push na `main` e varredura semanal). **Está desativado durante o desenvolvimento** para acelerar as entregas e será reativado na fase final (`gh workflow enable Security`).

| Ferramenta | Cobertura |
|---|---|
| CodeQL | SAST Python |
| Semgrep | SAST, SQL injection, OWASP Top 10 |
| pip-audit | CVEs nas dependências (com correção disponível) |
| Gitleaks | Segredos no histórico git |
| Trivy | CVEs e misconfigurações (Dockerfile/IaC) |

Os relatórios completos ficam em **Security → Code scanning**. Decisões detalhadas em [RFC-0001](docs/RFC/RFC-0001.md).

---

## TECH STACK
- Python 3.14.x
- uv 0.13.x
- FastAPI 0.162.x + auto-api-docs
- openai (python library/sdk)
- langgraph 1.2.x
- PostgreSQL + pgvector
- Ollama (ambiente de desenvolvimento: `qwen3:4b-instruct-2507-q4_K_M` + `bge-m3:567m`)

---

## COMO EXECUTAR

Pré-requisitos: Docker com Compose v2 e, para desenvolvimento local, [uv](https://docs.astral.sh/uv/) 0.13.6.

```bash
cp .env.example .env              # preencha os tokens (openssl rand -hex 32) e POSTGRES_PASSWORD
make up                           # API em http://localhost:8000 (docs em /docs), Postgres e Ollama
make install && make check        # dependências, lint, tipos e testes (cobertura mínima de 95%)
uv run python -m chatbot_api.ingest docs/apostilas   # carrega as apostilas na base (idempotente)
```

Uso da API: [manual](docs/manuais/MANUAL_DA_API.md).

---

## PLANEJAMENTO
O desenvolvimento segue o [plano por fases](docs/planejamento/PLANO_DE_DESENVOLVIMENTO.md), com um PR por fase. As decisões de base estão na [RFC-0002](docs/RFC/RFC-0002.md).
