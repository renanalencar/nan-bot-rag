"""
Fase 3 do pipeline RAG — retrieval.

Pergunta -> embed (mesmo modelo da Fase 2) -> top-k chunks do Chroma.

Módulo pensado pra ser importado (pelo notebook da demo ou por
generate.py), não pra rodar sozinho — mas dá pra testar isoladamente via
`python src/retrieve.py "sua pergunta"`.
"""

import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).parent.parent
VECTORSTORE_DIR = ROOT / "data" / "vectorstore"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # precisa bater com embed.py
COLLECTION_NAME = "corpus"  # precisa bater com embed.py
DEFAULT_TOP_K = 4

_model = None
_collection = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
        # get_or_create_collection ensures it won't crash even if the vectorstore is empty
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def retrieve(question: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Retorna os top_k chunks mais próximos da pergunta.

    Cada item: {"text", "source", "file", "page", "distance"}.
    """
    query_embedding = _get_model().encode([question], normalize_embeddings=True).tolist()
    result = _get_collection().query(query_embeddings=query_embedding, n_results=top_k)

    chunks = []
    for text, meta, dist in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        chunks.append(
            {
                "text": text,
                "source": meta["source"],
                "file": meta["file"],
                "page": meta["page"],
                "distance": dist,
            }
        )
    return chunks


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python src/retrieve.py "sua pergunta"')
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    print(f"Pergunta: {question}\n")
    for chunk in retrieve(question):
        print(f"[{chunk['source']} p.{chunk['page']}] (dist={chunk['distance']:.3f})")
        print(chunk["text"])
        print()
