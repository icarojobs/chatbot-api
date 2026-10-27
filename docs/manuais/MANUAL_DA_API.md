# Manual da API

Base URL local: `http://localhost:8000` · Documentação interativa: `/docs` (Swagger) e `/redoc`.

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
