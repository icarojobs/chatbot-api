# Testando a API com o Postman

Passo a passo para testar a Chatbot API pelo [Postman](https://www.postman.com/downloads/) usando a coleção pronta em [`docs/postman/chatbot-api.postman_collection.json`](../postman/chatbot-api.postman_collection.json). Para a referência completa de cada endpoint, veja o [Manual da API](MANUAL_DA_API.md).

## O que a coleção traz

| Pasta | Token | Conteúdo |
|---|---|---|
| 1. Saúde | nenhum | `GET /health` e `GET /ready` |
| 2. Modelos | `accessToken` | Lista os modelos com o `type` (`chat` ou `embedding`), preenche a variável `model` e detalha um modelo |
| 3. Chat (RAG) | `accessToken` | Pergunta com e sem streaming, abstenção fora do escopo, conversa com histórico e `top_k` |
| 4. Documentos (admin) | `adminToken` | Listagem, upload direto e o fluxo completo de upload em partes |
| 5. Erros esperados | variado | 401, 404 e 400 no formato de erro da OpenAI |
| 6. Exclusão (admin, destrutivo) | `adminToken` | Excluir um documento e reset da base. Execute só manualmente |

Cada requisição tem descrição (aba **Docs**) e testes automáticos (aba **Tests**/**Scripts**). Variáveis como `model`, `uploadId`, `partNumber` e `documentId` são preenchidas sozinhas pelas respostas.

## 1. Pré-requisitos

1. API rodando localmente: `make up` e depois `curl http://localhost:8000/ready`, que deve responder `{"status":"ready"}`. Se você mudou `API_HOST_PORT` no `.env`, ajuste a porta nos passos seguintes.
2. Base ingerida: `make ingest` (só na primeira vez).
3. Postman Desktop 10 ou mais recente. A versão web não alcança o `localhost` sem o Postman Agent.

## 2. Importar a coleção

1. No Postman: **File → Import** (ou botão **Import**).
2. Arraste o arquivo `docs/postman/chatbot-api.postman_collection.json`.
3. Confirme. A coleção **Chatbot API (RAG)** aparece na barra lateral.

## 3. Informar os tokens

Os tokens ficam no `.env` da raiz do projeto. Para vê-los só no seu terminal:

```bash
grep -E '^API_(ACCESS|ADMIN)_TOKEN=' .env
```

1. Clique na coleção **Chatbot API (RAG)** → aba **Variables**.
2. Preencha a coluna **Current value**:
   - `accessToken` ← valor de `API_ACCESS_TOKEN` (chat e modelos);
   - `adminToken` ← valor de `API_ADMIN_TOKEN` (documentos).
3. Confira `baseUrl` (padrão `http://localhost:8000`).
4. **Save** (Ctrl+S).

> Use sempre **Current value**: ele fica só na sua máquina e não vai junto se você exportar ou compartilhar a coleção. Nunca coloque tokens em **Initial value**.

A autenticação já está configurada: a coleção usa *Bearer Token* com `{{accessToken}}`, e a pasta de documentos sobrescreve com `{{adminToken}}`.

## 4. Primeiras requisições

1. **1. Saúde → Health** e **Ready**: devem responder `200`.
2. **2. Modelos → Listar modelos**: responde `200`. Cada modelo traz o campo `type`:
   - `chat`: gera as respostas e é o que vai em `model` no chat;
   - `embedding`: faz a busca do RAG, é escolhido pelo ambiente e não pode ser usado no chat.

   A requisição grava o primeiro modelo `chat` na variável `model` (em desenvolvimento, `qwen3:4b-instruct-2507-q4_K_M`; em produção, `azure/gpt-5-mini`). Para trocar de modelo, edite `model` na aba **Variables** com outro `id` do tipo `chat`. Se `model` estiver vazia, o campo é omitido e a API usa o modelo padrão.

## 5. Chat (RAG)

### Pergunta sem streaming

**3. Chat (RAG) → Pergunta no escopo (sem streaming)**. Na resposta, confira:

- `choices[0].message.content`: a resposta em pt-br, com citações `[1]`, `[2]`…;
- `sources`: os trechos usados (`filename`, `page_start`, `page_end`, `score`); o número da citação corresponde à posição na lista;
- `abstained`: `false`.

Para fazer outra pergunta, edite o texto em **Body → raw**.

### Pergunta com streaming

**Pergunta no escopo (streaming SSE)** envia `"stream": true`. O Postman mostra os eventos um a um conforme chegam:

- o primeiro chunk traz `delta.role = "assistant"`;
- os seguintes trazem pedaços do texto em `delta.content`;
- o último traz `finish_reason: "stop"`, `sources` e `abstained`;
- por fim chega `data: [DONE]`.

> **Tempo de resposta em desenvolvimento:** sem GPU, o modelo local (Ollama em CPU) leva cerca de **1 minuto para gerar uma resposta completa**. No modo streaming o texto começa a aparecer em poucos segundos, por isso ele é o melhor modo para acompanhar. Em produção o tempo até o primeiro token fica entre 5 e 10 s. Não reduza o timeout do Postman (**Settings → General → Request timeout** deve ficar em `0`, sem limite).

### Abstenção

**Pergunta fora do escopo (abstenção)**: perguntas sem relação com as apostilas devem voltar com `abstained: true`, `sources: []` e a mensagem padrão de abstenção, quase instantaneamente (o LLM não é chamado).

### Histórico e `top_k`

**Conversa com histórico e top_k**: mostra que só a **última** mensagem do usuário vira a pergunta, que mensagens `system` funcionam como instruções do cliente (formato, tom, idioma), sem burlar as regras da API, e que `top_k` (máximo 8) muda quantos trechos são recuperados. Em desenvolvimento, o modelo de 4B nem sempre segue instruções de formato; em produção, segue.

## 6. Enviar um PDF

### Upload direto (recomendado para testes)

Para PDFs de até 30 MB em localhost (4 MiB em produção, por causa do limite de 4,5 MB por requisição da Vercel), uma requisição basta:

1. Na aba **Variables** da coleção, preencha `fileName` (ex.: `apostila.pdf`) e salve.
2. **4. Documentos (admin) → Upload direto (PDF em uma requisição)** → **Body → binary** → selecione o PDF → **Send**.
3. A resposta é `202` com o documento em `processing`, e `documentId` é preenchida.
4. **4) Consultar documento** até `status` ser `ready`.

As apostilas de `docs/apostilas` (de 5,6 a 16 MB) cabem no upload direto.

### Upload em partes

Para arquivos acima desse limite, ou para testar a retomada de upload, o envio é feito em partes de até **4 MiB** (4.194.304 bytes). Como o Postman não calcula hash nem divide arquivos, prepare isso no terminal primeiro.

#### Calcular tamanho e SHA-256

**Linux:**

```bash
stat -c %s apostila.pdf
sha256sum apostila.pdf
```

**macOS:**

```bash
stat -f %z apostila.pdf
shasum -a 256 apostila.pdf
```

**Windows (PowerShell):**

```powershell
(Get-Item apostila.pdf).Length
(Get-FileHash apostila.pdf -Algorithm SHA256).Hash.ToLower()
```

#### Dividir o arquivo em partes

Arquivos de até 4 MiB não precisam ser divididos: a parte 1 é o próprio PDF.

**Linux e macOS:**

```bash
mkdir -p partes && split -b 4194304 apostila.pdf partes/parte-
ls partes   # parte-aa, parte-ab, parte-ac... (aa = parte 1, ab = parte 2...)
```

**Windows (PowerShell):**

```powershell
$bytes = [IO.File]::ReadAllBytes("$PWD\apostila.pdf"); $size = 4194304
New-Item -ItemType Directory -Force partes | Out-Null
for ($i = 0; $i * $size -lt $bytes.Length; $i++) {
  $end = [Math]::Min(($i + 1) * $size, $bytes.Length) - 1
  [IO.File]::WriteAllBytes("$PWD\partes\parte-$($i + 1)", $bytes[($i * $size)..$end])
}
```

#### Enviar pela coleção

1. Na aba **Variables** da coleção, preencha `fileName` (ex.: `apostila.pdf`), `fileSize` (bytes) e `fileSha256` (hex minúsculo). Salve.
2. **4. Documentos (admin) → 1) Iniciar upload**: responde `201` e grava `uploadId`. O console do Postman (**View → Show Postman Console**) informa quantas partes enviar.
3. **2) Enviar parte**: em **Body → binary**, selecione o arquivo da parte indicada por `partNumber` (começa em `1`) e envie. A cada `200`, `partNumber` avança para a próxima parte faltante. Troque o arquivo e repita até o console dizer que todas as partes foram recebidas.
4. **Consultar progresso do upload** (opcional): `received_parts` mostra o que já chegou. Se a rede cair, ele mostra de onde retomar.
5. **3) Concluir upload**: responde `202`, valida tamanho, SHA-256 e se o arquivo é PDF, extrai o texto e grava `documentId`. Os embeddings são gerados em background.
6. **4) Consultar documento**: repita até `status` ser `ready`. Se vier `failed`, o motivo está em `error`.
7. Volte ao chat e pergunte algo sobre o conteúdo do novo PDF.

Enviar um PDF idêntico a um já existente retorna o documento existente (deduplicação por SHA-256), sem reprocessar. A sessão de upload expira em 60 minutos.

**Erros comuns no upload:**

| Status | `code` | O que fazer |
|---|---|---|
| 400 | `invalid_part_size` | A parte não tem 4.194.304 bytes (só a última pode ser menor): confira a divisão |
| 409 | `upload_incomplete` | Faltam partes: veja `received_parts` e envie as que faltam |
| 410 | `upload_expired` | Sessão expirada: recomece em **1) Iniciar upload** |
| 415 | `unsupported_file_type` | O arquivo não é PDF |
| 422 | `checksum_mismatch` | `fileSha256` ou alguma parte está errada |

## 7. Excluir documentos

A pasta **6. Exclusão (admin, destrutivo)** apaga dados de verdade:

- **Excluir documento:** remove o documento da variável `documentId` (preenchida pelos uploads) com seus trechos e embeddings, e responde `204`. Para excluir outro, copie o `id` em **Listar documentos** e cole em `documentId`. Depois, uma pergunta sobre o conteúdo dele não deve mais citá-lo em `sources`.
- **Reset da base:** remove todos os documentos, trechos, embeddings e uploads, e mostra no console quantos foram removidos. Sem `confirm=true` a API responde `400` e nada é apagado (há um teste disso na pasta 5). Em produção o padrão é `403 reset_disabled`, mas o deploy da Vercel define `DOCUMENTS_RESET_ENABLED=true`, então o reset funciona lá. Para recarregar as apostilas depois, rode `make ingest` (dev), `make copy-db-neon` (produção) ou use o upload.

## 8. Erros esperados

A pasta **5. Erros esperados** valida os cenários negativos. Todos voltam no formato da OpenAI:

```json
{"error": {"message": "…", "type": "invalid_request_error", "param": null, "code": "model_not_found"}}
```

| Requisição | Esperado |
|---|---|
| Sem token | `401` |
| Token de acesso em rota admin | `401` |
| Modelo inexistente | `404` `model_not_found` |
| Modelo de embedding no chat | `400` `invalid_model_type` |
| Reset sem confirmação | `400` `confirmation_required` |
| Prompt injection (recusa) | `200` com mensagem de recusa, `abstained: true`, sem fontes |
| Pergunta longa demais (mais de 4000 caracteres) | `400` `question_too_long` |
| Parâmetro não suportado (`tools`) | `400` `unsupported_parameter` |
| Sem mensagem do usuário | `400` `invalid_messages` |

**Rate limit:** todas as rotas aceitam até `RATE_LIMIT_DEFAULT` requisições por IP (padrão `60/minute`). Para ver o `429`, rode **Health** no Collection Runner com 70 iterações e delay `0`.

## 9. Rodar tudo de uma vez (Collection Runner)

1. Clique com o botão direito na coleção → **Run collection**.
2. Desmarque:
   - as requisições de upload da pasta **4. Documentos (admin)** (exceto **Listar documentos**), que dependem de arquivos selecionados;
   - **toda** a pasta **6. Exclusão (admin, destrutivo)**.
3. **Run**. Todos os testes devem passar (verde).

Em desenvolvimento, sem GPU, a execução completa leva cerca de 2 a 3 minutos por causa das três gerações do LLM.

## 10. Testar outro ambiente

Para testar **localmente com os modelos de produção**, rode `make up-prod`; para voltar ao desenvolvimento, `make up`. Mudar `API_ENV` no `.env` não afeta o container. Veja a seção "Alternar entre desenvolvimento e produção (local)" do README. A `baseUrl` e os tokens continuam os mesmos. Rode **Listar modelos** de novo: se `model` guardar um modelo que não existe no ambiente atual, ela é trocada pelo primeiro modelo `chat`.

Para apontar para produção (Vercel), troque `baseUrl` pela URL do projeto (ex.: `https://<projeto>.vercel.app`) e use os tokens de **produção** em `accessToken`/`adminToken`. Em produção, `Listar modelos` retorna os modelos de `OPENAI_RESPONSE_MODELS`. Atualize `model` com o modelo desejado, ou deixe vazio para usar o padrão.

## 11. Testar o streaming pelo navegador (sem Postman)

A página [`docs/postman/test-stream.html`](../postman/test-stream.html) chama `POST /v1/chat/completions` direto do navegador. Ela mostra se a resposta chega aos poucos (`stream=true`) ou de uma vez (`stream=false`).

1. Abra o arquivo direto do disco, por exemplo `file:///caminho/do/projeto/docs/postman/test-stream.html`. Não é preciso servidor.
2. Preencha os campos:
   - **CHATBOT API URL:** o padrão é `http://localhost:8000/v1/chat/completions`. Para produção, use a URL da Vercel seguida de `/v1/chat/completions`.
   - **Chave API:** o `API_ACCESS_TOKEN` ou o `API_ADMIN_TOKEN` do ambiente.
   - **Mensagem:** a pergunta.
3. Marque ou desmarque **Stream** e clique em **Enviar**.

O painel mostra o status HTTP, o tempo até o primeiro byte, a quantidade de chunks, o tempo total, `abstained`, as fontes e, em **Resposta bruta**, o SSE recebido. No streaming, o número de chunks deve subir aos poucos. O botão **Parar** cancela a requisição.

A página depende do CORS da API (`CORS_ALLOWED_ORIGINS`, padrão `*`). Se aparecer "Failed to fetch", confira se a API no ar já tem CORS: o container local precisa ter sido reconstruído (`make up`), e a produção, publicada (merge na `main`). Só a URL fica salva no navegador; o token nunca é guardado.
