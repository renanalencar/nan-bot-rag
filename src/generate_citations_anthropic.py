"""
Bônus opcional — geração com Citations API (Anthropic).

Alternativa a generate.py: em vez de pedir citação por instrução dentro do
prompt, usa o recurso de citações estruturais da Citations API do Anthropic
(o modelo devolve o texto exato citado e o documento de origem, em vez de
escrever "(Fonte, p. X)" por conta própria).

Fica fora da abstração LLMProvider (ver llm_provider.py) de propósito: é um
recurso específico da API do Anthropic, sem equivalente direto em outros
providers, então só funciona com ANTHROPIC_API_KEY configurada — não dá pra
trocar de provider aqui.

Uso:
    python src/generate_citations_anthropic.py "your question here"

Requer ANTHROPIC_API_KEY em .env (ver .env.example).
"""

import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from retrieve import retrieve

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

CLAUDE_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 2048
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def _call_with_retry(request_fn):
    """Roda request_fn() com retry em erros retentáveis (429 e 5xx)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return request_fn()
        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            retryable = isinstance(e, anthropic.RateLimitError) or e.status_code >= 500
            if retryable and attempt < MAX_RETRIES:
                print(f"  Erro {getattr(e, 'status_code', 429)}, retrying in {RETRY_DELAY_SECONDS}s... ({attempt}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise
    raise RuntimeError("Failed to call Claude after multiple retries")


def build_documents(chunks: list[dict]) -> list[dict]:
    """Converte chunks recuperados em content blocks `document`, com citações
    estruturais habilitadas (Citations API).
    """
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": c["text"]},
            "title": f"{c['source']}, p. {c['page']}",
            "citations": {"enabled": True},
        }
        for c in chunks
    ]


def call_claude_with_citations(client: anthropic.Anthropic, documents: list[dict], question: str) -> list[dict]:
    """Chama o Claude com os documents montados por build_documents.

    Retorna os segmentos de texto da resposta, cada um com a lista de
    citações estruturais (texto exato citado + documento de origem) que a
    API devolve.
    """
    response = _call_with_retry(lambda: client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": documents + [{"type": "text", "text": question}]}],
    ))

    segments = []
    for block in response.content:
        if block.type != "text":
            continue
        citations = [
            {"cited_text": cit.cited_text, "document_title": cit.document_title}
            for cit in (block.citations or [])
        ]
        segments.append({"text": block.text, "citations": citations})
    return segments


def answer_question_with_citations(question: str, top_k: int = 4) -> dict:
    """Roda o loop RAG completo usando a Citations API em vez de citação por
    instrução no prompt. Retorna pergunta, chunks recuperados, documents
    montados e os segmentos de resposta com citação estrutural.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não encontrada. Copie .env.example para .env e preencha a chave.")

    chunks = retrieve(question, top_k=top_k)
    documents = build_documents(chunks)
    client = anthropic.Anthropic(api_key=api_key)
    segments = call_claude_with_citations(client, documents, question)

    return {"question": question, "chunks": chunks, "documents": documents, "segments": segments}


def print_result_with_citations(result: dict):
    print(f"Question: {result['question']}\n")
    print("Retrieved chunks:")
    for c in result["chunks"]:
        print(f"  [{c['source']} p.{c['page']}] (dist={c['distance']:.3f})")
    print("\nAnswer (with structural citations):")
    for seg in result["segments"]:
        print(seg["text"])
        for cit in seg["citations"]:
            print(f"    ↳ [{cit['document_title']}] \"{cit['cited_text']}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python src/generate_citations_anthropic.py "sua pergunta"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = answer_question_with_citations(question)
    print_result_with_citations(result)
