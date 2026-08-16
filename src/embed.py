"""
Fase 2 do pipeline RAG — embeddings + vector store.

data/chunks/chunks.json -> vetores (sentence-transformers, local, CPU)
                         -> Chroma persistido em data/vectorstore/

Os embeddings são calculados aqui explicitamente, chunk por chunk, em vez
de delegados a uma função default escondida dentro do Chroma.

Uso:
    python src/embed.py
"""

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).parent.parent
CHUNKS_PATH = ROOT / "data" / "chunks" / "chunks.json"
VECTORSTORE_DIR = ROOT / "data" / "vectorstore"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "corpus"
BATCH_SIZE = 256

# Preencha com perguntas relevantes ao conteúdo que você colocou em docs/
# — servem só para checar visualmente se o retrieval está trazendo
# passagens plausíveis antes de conectar o LLM.
SANITY_QUERIES = []


def load_chunks() -> list[dict]:
    return json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))


def main():
    chunks = load_chunks()
    print(f"{len(chunks)} chunks carregados de {CHUNKS_PATH.name}")

    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Modelo de embedding: {EMBEDDING_MODEL} ({model.get_sentence_embedding_dimension()} dimensões)")

    client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
    # Recria a collection do zero a cada execução — mais simples que
    # sincronizar incrementalmente, e o corpus inteiro reindexa em segundos.
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(
        COLLECTION_NAME,
        metadata={"embedding_model": EMBEDDING_MODEL, "hnsw:space": "cosine"},
    )

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        collection.add(
            ids=[c["id"] for c in batch],
            documents=texts,
            embeddings=embeddings.tolist(),
            metadatas=[{"source": c["source"], "file": c["file"], "page": c["page"]} for c in batch],
        )
        print(f"  {min(start + BATCH_SIZE, len(chunks))}/{len(chunks)} chunks indexados")

    print(f"\nVector store populado em {VECTORSTORE_DIR} ({collection.count()} itens)")

    print("\n--- Teste de sanidade (retrieval antes de conectar o LLM) ---")
    for query in SANITY_QUERIES:
        query_embedding = model.encode([query], normalize_embeddings=True).tolist()
        result = collection.query(query_embeddings=query_embedding, n_results=3)
        print(f"\nQuery: {query!r}")
        for doc, meta, dist in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            print(f"\n  [{meta['source']} p.{meta['page']}] (dist={dist:.3f})")
            print(f"  {doc}")


if __name__ == "__main__":
    main()
