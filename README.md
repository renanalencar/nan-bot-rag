# POC RAG — Sistemas com IA

POC de um pipeline de **Retrieval-Augmented Generation (RAG)** local: você coloca PDFs em `docs/`, o pipeline extrai o texto, indexa por similaridade semântica e responde perguntas citando a fonte (arquivo + página).

Projeto pensado para a turma estudar e estender — a extração de PDF e o provider de LLM são pontos de plugue deliberados, documentados abaixo.

## Índice

- [Pipeline](#pipeline)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Setup](#setup)
- [Como rodar](#como-rodar)
- [Decisões arquiteturais](#decisões-arquiteturais)
- [Como estender](#como-estender)

## Pipeline

O pipeline possui quatro fases base e uma interface de API, onde cada fase consome o resultado da anterior:

```
docs/*.pdf
   │  src/ingest.py
   ▼
data/chunks/chunks.json      (texto em pedaços, com metadata de fonte/página)
   │  src/embed.py
   ▼
data/vectorstore/            (Chroma, embeddings persistidos em disco)
   │  src/retrieve.py  ──►  top-k chunks mais parecidos com a pergunta
   ▼
src/generate.py ou src/main.py ──► prompt (pergunta + chunks) ──► LLM ──► resposta citada
```

| Fase | Arquivo | Entrada | Saída |
|---|---|---|---|
| 1. Ingestão | `src/ingest.py` | PDFs em `docs/` | `data/chunks/chunks.json` |
| 2. Embedding | `src/embed.py` | `chunks.json` | `data/vectorstore/` (Chroma) |
| 3. Retrieval | `src/retrieve.py` | pergunta (texto) | top-k chunks relevantes |
| 4. Geração (Terminal)| `src/generate.py` | pergunta + chunks | resposta no terminal |
| 5. Atendimento (API) | `src/main.py` | webhooks de chat | resposta enviada ao usuário |

## Estrutura do projeto

```
poc_rag_sistemas_com_ia/
├── docs/                             # PDFs do corpus (você adiciona os seus aqui)
├── data/
│   ├── chunks/                       # cache de texto extraído + chunks.json
│   └── vectorstore/                  # Chroma persistido (gerado por embed.py)
├── src/
│   ├── ingest.py                     # Fase 1 — PDF -> chunks
│   ├── embed.py                      # Fase 2 — chunks -> vector store
│   ├── retrieve.py                   # Fase 3 — pergunta -> top-k chunks
│   ├── generate.py                   # Fase 4 — pergunta + chunks -> resposta (Terminal)
│   ├── main.py                       # Fase 5 — Webhooks FastAPI (WhatsApp, Telegram, Slack)
│   ├── llm_provider.py               # abstração de provider de LLM (Anthropic, Gemini, OpenAI)
│   └── generate_citations_anthropic.py  # bônus opcional, só Anthropic
├── requirements.txt
├── .env.example                      # copie para .env e preencha
└── README.md
```

## Setup

Pré-requisito: Python 3.11+.

```bat
:: criar e ativar o ambiente virtual (Windows, cmd.exe)
python -m venv .venv
.venv\Scripts\activate.bat

:: instalar dependências
pip install -r requirements.txt

:: configurar variáveis de ambiente
copy .env.example .env
:: edite .env e preencha as variáveis da sua LLM e dos bots (Telegram, WhatsApp, Slack)
```

Coloque um ou mais PDFs em `docs/` (pode criar subpastas à vontade — o `ingest.py` procura recursivamente).

## Como rodar

Com a venv ativada e pelo menos um PDF em `docs/`:

### Processamento do Corpus (Indexação)
```bat
python src/ingest.py
python src/embed.py
```

### Teste Rápido via Terminal
```bat
python src/generate.py "sua pergunta sobre o conteúdo dos PDFs"
```

### Atendimento Automático via Webhooks (FastAPI)
O projeto contém uma API em FastAPI pronta para plugar em serviços de mensageria.
```bat
uvicorn src.main:app --reload
```
Isso levantará o servidor em `http://127.0.0.1:8000` expondo as rotas:
- `/webhook` para o WhatsApp Cloud API
- `/telegram-webhook` para o Telegram (botfather)
- `/slack-webhook` para a Event API do Slack

- `ingest.py` e `embed.py` só precisam ser reexecutados quando `docs/` mudar.
- `retrieve.py` pode ser testado isoladamente (sem chamar LLM nenhum):
  ```bat
  python src/retrieve.py "sua pergunta"
  ```
- `generate.py` chama `retrieve()` internamente, então basta rodar ele direto pra ter o fluxo completo.

## Decisões arquiteturais

### Chunking contido por página

`ingest.py` nunca deixa um chunk cruzar a fronteira de uma página — cada chunk tem exatamente uma página de origem. Isso torna a citação `(fonte, p. X)` sempre inequívoca; o custo é que um parágrafo que atravessa duas páginas fica cortado no meio, aceitável para esta POC.

### Cache de extração por PDF (`data/chunks/_raw_pages/`)

Extrair texto de um PDF grande não é instantâneo. `extract_pages()` persiste o texto bruto por página assim que extrai, então rodar `ingest.py` de novo sobre o mesmo PDF não reprocessa nada — só lê do cache. Se você adicionar um PDF novo, só o PDF novo é processado.

### Descarte de páginas sem texto útil (`MIN_USEFUL_CHARS`)

Páginas que são só imagem/ilustração (capa de capítulo, arte) extraem string vazia ou quase vazia. Em vez de gerar um chunk vazio ou de ruído, essas páginas são descartadas silenciosamente (contabilizadas no log como "páginas descartadas").

### `ingest.py` genérico, sem lista de arquivos fixa

Versões anteriores deste pipeline (POC original) tinham uma lista hardcoded de arquivos, cada um com seu próprio método de extração (havia um PDF com mapeamento de fonte quebrado que exigia OCR). Aqui não — `ingest.py` varre `docs/` recursivamente (`DOCS.rglob("*.pdf")`) e extrai todos com o mesmo método (texto embutido via PyMuPDF). **Trade-off**: PDFs escaneados como imagem, sem camada de texto, não vão gerar chunks (a página inteira cai no `MIN_USEFUL_CHARS` e é descartada). Se seu PDF for assim, você vai notar pelo log ("X páginas descartadas") e precisa adicionar um passo de OCR por conta própria.

### Embeddings calculados explicitamente, não delegados ao Chroma

`embed.py` chama `model.encode(...)` você mesmo, em vez de deixar o Chroma calcular embeddings escondido atrás de uma default embedding function. O objetivo é pedagógico: essa é a etapa mais fácil de virar caixa-preta, então ela fica visível no código.

### `all-MiniLM-L6-v2` como modelo de embedding

Modelo pequeno, roda em CPU sem custo de API, e é monolíngue (inglês). Se o seu corpus for majoritariamente em português (ou outro idioma), vale trocar por um modelo multilíngue — mas espere retrieval menos preciso para termos técnicos que não têm tradução direta óbvia; teste com as suas próprias perguntas antes de confiar no resultado.

### Collection do Chroma recriada do zero a cada `embed.py`

Mais simples que sincronizar incrementalmente (detectar o que mudou, o que foi removido, etc.), e reindexar o corpus inteiro leva segundos nessa escala. Se seu corpus crescer para algo que demore minutos/horas para reindexar, essa decisão precisa ser revisitada.

### Distância cosseno (`hnsw:space: "cosine"`)

Padrão comum para embeddings de sentence-transformers normalizados (`normalize_embeddings=True` tanto em `embed.py` quanto em `retrieve.py`) — com vetores normalizados, cosseno e produto interno dão o mesmo ranking, mas cosseno é mais intuitivo de debugar (distância 0 = idêntico, 2 = oposto).

### `LLMProvider`: abstração sobre o provider de LLM

`generate.py` e `main.py` não importam bibliotecas de IA diretamente na lógica de negócio — eles chamam `get_provider().generate(prompt)`, definido em `llm_provider.py`. Motivo: o resto do pipeline (ingest/embed/retrieve) é 100% local; só a geração da resposta precisa de um LLM. O projeto já suporta **Anthropic**, **OpenAI** e **Gemini** nativamente. Ver [Como estender](#implementar-um-novo-provider-de-llm) para adicionar o seu.

### Citations API isolada em `generate_citations_anthropic.py`

O Anthropic oferece um recurso de citação estrutural (a API aponta o trecho exato citado e o documento de origem, em vez do modelo escrever a citação por conta própria no texto). É um recurso proprietário, sem equivalente direto em outros providers — por isso fica fora da abstração `LLMProvider`, em um arquivo separado, claramente marcado como bônus opcional que só funciona com Anthropic.

## Como estender

### Adicionar material ao corpus

Só colocar o PDF em `docs/` (em qualquer subpasta) e rodar `ingest.py` de novo. O nome da fonte citada nas respostas é o caminho relativo a `docs/` sem extensão (ex.: `docs/regras/manual.pdf` vira fonte `"regras/manual"`).

### Implementar um novo provider de LLM

Em `src/llm_provider.py`:

1. Crie uma classe que herda de `LLMProvider` e implementa `generate(self, prompt: str) -> str`. Essa é a única regra de contrato — recebe o prompt já montado e devolve o texto da resposta.
2. Sua classe é responsável pela própria autenticação (variável de ambiente, etc.) e pelo próprio retry em erros transitórios — use `AnthropicProvider` como referência.
3. Registre a classe no dicionário `PROVIDERS`, associada a um nome.
4. No `.env`, defina `LLM_PROVIDER=<seu-nome>`.

```python
class MeuProvider(LLMProvider):
    def __init__(self):
        ...  # ler API key do ambiente, inicializar client

    def generate(self, prompt: str) -> str:
        ...  # chamar o modelo, devolver só o texto da resposta

PROVIDERS = {
    "anthropic": AnthropicProvider,
    "meu-provider": MeuProvider,
}
```

`generate.py` não precisa de nenhuma mudança — ele só conhece a interface `LLMProvider`.

### Ajustar as perguntas de sanidade

`embed.py` tem uma lista `SANITY_QUERIES` (vazia por padrão) rodada ao final da indexação, só para checar visualmente se o retrieval está trazendo passagens plausíveis antes de conectar o LLM. Preencha com 2-3 perguntas relevantes ao seu corpus.
