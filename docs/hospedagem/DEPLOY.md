# Deploy em produção (Vercel + Neon)

Decisão registrada no [ADR-0010](../ADR/ADR-0010.md), que substitui o Cloud Run do [ADR-0005](../ADR/ADR-0005.md). Na primeira vez, o processo leva uns 20 minutos. Depois disso, cada merge na `main` publica sozinho.

## 1. Pré-requisitos

- Conta na [Vercel](https://vercel.com) (plano Hobby, gratuito, sem cartão), com acesso ao repositório no GitHub.
- Conta no [Neon](https://neon.tech) (plano gratuito, sem cartão).
- Node.js (para o `npx vercel`), Docker e `uv` na máquina local.

## 2. Banco no Neon

1. Crie o projeto na região **AWS São Paulo (`aws-sa-east-1`)**. A região não muda depois, e a API roda em São Paulo (`gru1`).
2. Em **Connect**, desligue **Connection pooling** e copie a connection string. O host não pode ter `-pooler`.
3. Troque o prefixo `postgresql://` por `postgresql+psycopg://` e mantenha `?sslmode=require`.

A extensão `vector` e as tabelas são criadas pelas migrations, tanto no build da Vercel quanto no `make copy-db-neon`.

## 3. Configuração local

```bash
cp .env.production.example .env.production   # ignorado pelo git
openssl rand -hex 32                           # rode duas vezes: API_ACCESS_TOKEN e API_ADMIN_TOKEN novos
```

Preencha `DATABASE_URL` (Neon), as credenciais do provedor e os tokens. **Não reaproveite os tokens de desenvolvimento.**

## 4. Carga da base no Neon

Escolha **uma** das opções:

```bash
make copy-db-neon   # copia a base local chatbot_prod (gerada por make ingest-prod-local), sem gastar créditos
make ingest-prod    # ou: gera os embeddings de novo, direto no Neon (gasta créditos)
```

O `copy-db-neon` aplica as migrations no Neon, confere se o banco está vazio e copia `documents`, `chunks` e `chunk_embeddings` numa única transação. Ao final, mostra a contagem de registros na origem e no destino.

## 5. Projeto na Vercel

```bash
npx vercel@64.0.2 login
npx vercel@64.0.2 link --yes --project chatbot-api   # cria o projeto e o arquivo .vercel/ (ignorado pelo git)
npx vercel@64.0.2 git connect                        # vincula o repositório do GitHub
make deploy-env                                      # grava as variáveis de produção (valores não são exibidos)
```

O `make deploy-env` grava as credenciais como **sensitive**, ou seja, não podem ser lidas depois nem pelo painel. Ele também fixa `API_ENV=production`, `TRUSTED_PROXY_HOPS=1` e `DIRECT_UPLOAD_MAX_BYTES=4194304`.

## 6. Deploy

O primeiro deploy pode ser feito pela CLI:

```bash
npx vercel@64.0.2 deploy --prod
```

A partir daí, **todo merge na `main` publica automaticamente**. Branches e PRs não geram deploy (`git.deploymentEnabled` no `vercel.json`).

Configuração aplicada (`vercel.json` e `pyproject.toml`):

| Item | Valor | Motivo |
|---|---|---|
| Entrada | `src/chatbot_api/asgi.py` (`app`) | A Vercel importa `módulo:app`, sem factory |
| Região | `gru1` (São Paulo) | Mesma região do Neon |
| `maxDuration` | 300 s | Máximo do plano Hobby; cobre o streaming e o embedding após o upload |
| Build | `python -m chatbot_api.db.migrate` | Migrations antes de publicar; se falharem, a versão anterior continua no ar |
| Pacote | sem `tests/`, `docs/`, `evaluation/`, `scripts/` | Pacote menor e cold start mais rápido |
| Deploy automático | só a `main` | Previews usariam o banco e os créditos de produção |

## 7. Teste pela URL pública

```bash
make deploy-smoke URL=https://<projeto>.vercel.app   # /health, /ready e /v1/models

curl -N https://<projeto>.vercel.app/v1/chat/completions \
  -H "Authorization: Bearer $API_ACCESS_TOKEN" -H "Content-Type: application/json" \
  -d '{"stream": true, "messages": [{"role": "user", "content": "O que é matriciamento?"}]}'
```

Também dá para testar pelo Postman (`baseUrl`) e pela página `docs/postman/test-stream.html`, conforme o [guia do Postman](../manuais/TESTE_COM_POSTMAN.md).

## Custos e limites

- **Custo zero** dentro dos limites do plano Hobby (uso não comercial) e do Neon free (com cotas mensais de armazenamento e de horas de computação; a base atual ocupa poucos MB).
- **Requisições de até 4,5 MB:** o upload direto fica limitado a 4 MiB em produção. Para PDFs maiores, use o upload em partes (4 MiB por parte).
- **Cold start:** sem tráfego, a função escala até zero e o Neon suspende após 5 minutos. A primeira requisição depois disso leva alguns segundos a mais.
- **Rate limit por instância:** o limite fica em memória, então com várias instâncias o limite efetivo se multiplica.
