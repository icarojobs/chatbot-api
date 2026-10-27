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

## TECH STACK
- Python 3.15.x
- uv 0.13.x
- FastAPI 0.162.x + auto-api-docs
- openai (python library/sdk)
- langgraph 1.2.x
