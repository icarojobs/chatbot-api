# Manual da API

Base URL local: `http://localhost:8000` · Documentação interativa: `/docs` (Swagger) e `/redoc`.

> Prefere testar pelo Postman? Importe a coleção [`docs/postman/chatbot-api.postman_collection.json`](../postman/chatbot-api.postman_collection.json) e siga o [passo a passo](TESTE_COM_POSTMAN.md).

## Autenticação

Endpoints que consomem créditos exigem o header `Authorization: Bearer <token>`:

| Token (`.env`) | Uso |
|---|---|
| `API_ACCESS_TOKEN` | Chat e listagem de modelos |
| `API_ADMIN_TOKEN` | Upload e gestão de documentos |

É o mesmo header que os SDKs da OpenAI enviam como `api_key`.

## Rate limiting

Todas as rotas são limitadas por IP (padrão `60/minute`, configurável em `RATE_LIMIT_DEFAULT`). Ao exceder, a API responde `429` com o header `Retry-After` (segundos até liberar).

## Formato de erro

Todos os erros seguem o formato da API da OpenAI:

```json
{
  "error": {
    "message": "Token de acesso ausente ou inválido.",
    "type": "authentication_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

| Status | `type` |
|---|---|
| 400 | `invalid_request_error` |
| 401 | `authentication_error` |
| 404 | `not_found_error` |
| 429 | `rate_limit_error` |
| 500 | `server_error` (sem detalhes internos) |

Toda resposta traz o header `x-request-id`. Envie o seu próprio (8–64 caracteres alfanuméricos ou `-`) para correlacionar com os logs.

## Endpoints

### `GET /health`

Verifica se o processo está vivo.

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### `GET /ready`

Verifica se a aplicação e suas dependências estão prontas. Retorna `200 {"status":"ready"}` ou `503 {"status":"not_ready"}`.

```bash
curl http://localhost:8000/ready
```

### `GET /v1/models`

Lista os modelos de chat disponíveis no ambiente (formato da OpenAI). Requer `API_ACCESS_TOKEN`.

```bash
curl http://localhost:8000/v1/models -H "Authorization: Bearer $API_ACCESS_TOKEN"
```

```json
{"object": "list", "data": [{"id": "azure/gpt-5-mini", "object": "model", "created": 0, "owned_by": "chatbot-api"}]}
```

Em `development` a lista traz o modelo do Ollama; em `production`, os modelos de `OPENAI_RESPONSE_MODELS`. Com o SDK da OpenAI:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="<API_ACCESS_TOKEN>")
print([model.id for model in client.models.list()])
```

### `GET /v1/models/{model_id}`

Detalha um modelo. IDs com `/` são aceitos (ex.: `/v1/models/azure/gpt-5-mini`). Modelo fora da lista retorna `404` com `code: "model_not_found"`.

## Documentos (base de conhecimento)

Todas as rotas abaixo exigem o **`API_ADMIN_TOKEN`**. O envio é feito **em partes de até 4 MiB** (abaixo do limite de 4,5 MB por requisição de algumas hospedagens), o que permite arquivos grandes e retomada após falha de rede. Tamanho máximo padrão: 50 MB (`UPLOAD_MAX_BYTES`); a sessão expira em 60 minutos (`UPLOAD_TTL_MINUTES`).

### Fluxo

1. `POST /v1/documents/uploads` com `filename`, `size` (bytes) e `sha256` (hex minúsculo) → retorna `id`, `part_size` e `total_parts`.
2. `PUT /v1/documents/uploads/{id}/parts/{n}` para cada parte `n` (1..`total_parts`), com o corpo binário (`application/octet-stream`). Todas as partes têm exatamente `part_size` bytes, exceto a última. Reenviar uma parte a substitui.
3. `GET /v1/documents/uploads/{id}` mostra `received_parts` (use para retomar).
4. `POST /v1/documents/uploads/{id}/complete` valida partes, tamanho, SHA-256 e se o conteúdo é PDF, extrai o texto e responde **`202`** com o documento em `processing`. Os embeddings são gerados em background.
5. `GET /v1/documents/{document_id}` até `status` virar `ready` (ou `failed`, com `error`).

Enviar um arquivo idêntico a um já existente retorna o documento existente (deduplicação por SHA-256).

### Exemplo em Python

```python
import hashlib
from pathlib import Path

import httpx

path = Path("apostila.pdf")
data = path.read_bytes()
headers = {"Authorization": "Bearer <API_ADMIN_TOKEN>"}

with httpx.Client(base_url="http://localhost:8000", headers=headers, timeout=120) as client:
    upload = (
        client.post(
            "/v1/documents/uploads",
            json={
                "filename": path.name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
        .raise_for_status()
        .json()
    )

    for number in range(1, upload["total_parts"] + 1):
        start = (number - 1) * upload["part_size"]
        client.put(
            f"/v1/documents/uploads/{upload['id']}/parts/{number}",
            content=data[start : start + upload["part_size"]],
            headers={"Content-Type": "application/octet-stream"},
        ).raise_for_status()

    document = (
        client.post(f"/v1/documents/uploads/{upload['id']}/complete").raise_for_status().json()
    )
    print(document["id"], document["status"])
```

### Erros específicos

| Status | `code` | Causa |
|---|---|---|
| 400 | `invalid_part_number` / `invalid_part_size` / `invalid_filename` | Parte fora do intervalo, tamanho incorreto ou nome inválido |
| 404 | `upload_not_found` | Upload inexistente (ou expirado e já removido) |
| 409 | `upload_incomplete` / `upload_not_open` | Faltam partes / upload já concluído |
| 410 | `upload_expired` | Sessão expirada: inicie outra |
| 413 | `file_too_large` / `part_too_large` | Arquivo ou parte acima do limite |
| 415 | `unsupported_file_type` | O conteúdo não é PDF |
| 422 | `checksum_mismatch` / `invalid_document` | SHA-256 não confere / PDF sem texto extraível |

### `GET /v1/documents` e `GET /v1/documents/{id}`

Listam/detalham documentos com `status` (`processing`, `ready`, `failed`), `page_count` e `chunk_count`.

## Chat (RAG)

### `POST /v1/chat/completions`

Responde perguntas **com base nas apostilas**, no mesmo formato da API de Chat Completions da OpenAI. Requer `API_ACCESS_TOKEN`. Qualquer SDK/cliente da OpenAI funciona trocando apenas `base_url` e `api_key`.

| Campo | Tipo | Descrição |
|---|---|---|
| `messages` | lista | Conversa no formato da OpenAI. A **última** mensagem deve ser do usuário; ela é a pergunta (máx. 4000 caracteres). `content` aceita texto ou partes `{"type": "text"}`. |
| `model` | string | Opcional. Um dos IDs de `GET /v1/models`; padrão: o primeiro da lista. |
| `stream` | bool | `true` para SSE (padrão `false`). |
| `top_k` | int | Extensão opcional: quantos trechos recuperar (padrão 4, máx. 8). |

Campos desconhecidos são ignorados; `tools`, `functions`, `tool_choice`, `function_call`, `logprobs` e `n > 1` retornam `400`.

A resposta inclui dois campos extras (ignorados por clientes da OpenAI):

- `sources`: trechos usados como contexto (`filename`, `page_start`, `page_end`, `score`, `chunk_id`, `document_id`). As citações `[1]`, `[2]`… no texto seguem essa ordem.
- `abstained`: `true` quando a base não tem evidência suficiente — a API responde que não encontrou a informação **sem chamar o LLM**.

#### Exemplo com streaming (`curl`)

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"stream": true, "messages": [{"role": "user", "content": "O que é matriciamento em saúde mental?"}]}'
```

```text
data: {"id": "chatcmpl-…", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": null}], …}

data: {"id": "chatcmpl-…", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "Matriciamento"}, "finish_reason": null}], …}

data: {"id": "chatcmpl-…", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "sources": [{"filename": "…pdf", "page_start": 50, "page_end": 50, "score": 0.6564, …}], "abstained": false}

data: [DONE]
```

#### Exemplo com o SDK da OpenAI (Python)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="<API_ACCESS_TOKEN>")

stream = client.chat.completions.create(
    model="azure/gpt-5-mini",
    messages=[{"role": "user", "content": "Como acolher um usuário em sofrimento psíquico?"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

Sem streaming, `response.model_extra["sources"]` traz as fontes.

#### Erros

- Antes do primeiro token (modelo inválido, provedor indisponível): status HTTP de erro com o corpo no formato da OpenAI (`404 model_not_found`, `502 provider_error`, `504 provider_timeout`…).
- Depois que o stream começou: um evento `data: {"error": {...}}` encerra o stream (sem `[DONE]`); os SDKs da OpenAI transformam esse evento em exceção.
- Se o cliente desconectar, a geração no provedor é cancelada.
