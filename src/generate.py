"""
Fase 4 do pipeline RAG — geração.

chunks recuperados (retrieve.py) + pergunta -> prompt -> LLM -> resposta citada.

O provider de LLM é plugável — ver llm_provider.py. Por padrão usa o
AnthropicProvider (requer ANTHROPIC_API_KEY em .env, ver .env.example);
troque via variável de ambiente LLM_PROVIDER.

Uso:
    python src/generate.py "your question here"
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

from llm_provider import get_provider
from retrieve import retrieve

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

PROMPT_TEMPLATE = """You are a documentation assistant. Answer the question using ONLY the information in the excerpts below, taken from the reference documents in docs/.

Rules:
- Answer directly and objectively.
- Cite the source of each claim in the format (Source, p. X), using the source name and page shown for each excerpt.
- If the excerpts don't have enough information to answer, say so explicitly instead of making something up.

Retrieved excerpts:
{context}

Question: {question}

Answer:"""


def build_prompt(question: str, chunks: list[dict]) -> str:
    context = "\n\n".join(f"[Source: {c['source']}, p. {c['page']}]\n{c['text']}" for c in chunks)
    return PROMPT_TEMPLATE.format(context=context, question=question)


def answer_question(question: str, top_k: int = 4) -> dict:
    """Roda o loop RAG completo: retrieval -> prompt -> geração.

    Retorna pergunta, chunks recuperados, prompt montado e resposta.
    """
    chunks = retrieve(question, top_k=top_k)
    prompt = build_prompt(question, chunks)
    provider = get_provider()
    answer = provider.generate(prompt)

    return {"question": question, "chunks": chunks, "prompt": prompt, "answer": answer}


def print_result(result: dict):
    print(f"Question: {result['question']}\n")
    print("Retrieved chunks:")
    for c in result["chunks"]:
        print(f"  [{c['source']} p.{c['page']}] (dist={c['distance']:.3f})")
    print(f"\nAnswer:\n{result['answer']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python src/generate.py "sua pergunta"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = answer_question(question)
    print_result(result)
