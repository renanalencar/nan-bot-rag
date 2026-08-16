"""
Fase 1 do pipeline RAG — ingestão.

Fluxo: PDF -> texto por página -> limpeza -> chunking -> data/chunks/chunks.json

Versão genérica: qualquer PDF colocado em docs/ (em qualquer subpasta) é
processado automaticamente. Não há lista de arquivos fixa — para adicionar
material ao corpus, basta colocar o PDF dentro de docs/.

A extração é sempre por texto embutido no PDF (sem OCR). Páginas com pouco
texto útil (ex.: PDF escaneado como imagem) são descartadas — ver
MIN_USEFUL_CHARS.

O resultado da extração de cada PDF é cacheado em disco
(data/chunks/_raw_pages/), então rodar o script de novo não reprocessa
arquivos que não mudaram.

Uso:
    python src/ingest.py
"""

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
CHUNKS_DIR = ROOT / "data" / "chunks"
RAW_PAGES_DIR = CHUNKS_DIR / "_raw_pages"

# Páginas com menos que isso de texto útil são tratadas como "só imagem"
# e descartadas (não viram chunk).
MIN_USEFUL_CHARS = 40

CHUNK_SIZE_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150


def clean_text(text: str) -> str:
    """Normaliza espaçamento sem tentar reescrever o conteúdo."""
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(page: fitz.Page) -> str:
    return str(page.get_text("text"))


def cache_key(pdf_path: Path) -> str:
    """Nome de cache único por arquivo, baseado no caminho relativo a docs/.

    Evita colisão entre PDFs de mesmo nome em subpastas diferentes.
    """
    rel = pdf_path.relative_to(DOCS).with_suffix("")
    return str(rel).replace("\\", "__").replace("/", "__")


def extract_pages(pdf_path: Path) -> dict[int, str]:
    """
    Retorna {página (1-indexed): texto bruto} para todo o PDF.

    Usa um cache em disco por arquivo (data/chunks/_raw_pages/<chave>.json)
    para não reextrair PDFs grandes a cada execução do script.
    """
    RAW_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_PAGES_DIR / f"{cache_key(pdf_path)}.json"

    cached: dict[str, str] = {}
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    pages: dict[int, str] = {int(k): v for k, v in cached.items()}

    new_pages = 0
    for i in range(total_pages):
        page_num = i + 1
        if page_num in pages:
            continue
        pages[page_num] = extract_page_text(doc[i])
        new_pages += 1
    doc.close()

    if new_pages:
        cache_path.write_text(json.dumps(pages, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"  [{pdf_path.name}] {new_pages} páginas extraídas, cache salvo em {cache_path.name}")
    else:
        print(f"  [{pdf_path.name}] {total_pages} páginas já em cache ({cache_path.name})")

    return pages


def chunk_page_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Divide o texto de UMA página em pedaços de tamanho fixo com overlap.

    Chunking fica contido dentro da página de propósito: cada chunk tem
    exatamente uma página de origem, então a citação ("p. X") nunca é
    ambígua.
    """
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c]


def build_chunks(pdf_path: Path) -> list[dict]:
    pages = extract_pages(pdf_path)
    chunks = []
    skipped_pages = 0
    source_label = pdf_path.relative_to(DOCS).with_suffix("").as_posix()

    for page_num in sorted(pages):
        text = clean_text(pages[page_num])
        if len(text) < MIN_USEFUL_CHARS:
            skipped_pages += 1
            continue
        for i, piece in enumerate(chunk_page_text(text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)):
            chunks.append(
                {
                    "id": f"{cache_key(pdf_path)}_p{page_num}_{i}",
                    "text": piece,
                    "source": source_label,
                    "file": pdf_path.name,
                    "page": page_num,
                }
            )

    print(f"  [{pdf_path.name}] {len(chunks)} chunks, {skipped_pages} páginas descartadas (só imagem/pouco texto)")
    return chunks


def main():
    pdf_paths = sorted(DOCS.rglob("*.pdf"))
    if not pdf_paths:
        print(f"Nenhum PDF encontrado em {DOCS}. Coloque os arquivos lá antes de rodar.")
        return

    all_chunks = []
    for pdf_path in pdf_paths:
        print(f"Ingerindo {pdf_path.relative_to(DOCS)}...")
        all_chunks.extend(build_chunks(pdf_path))

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHUNKS_DIR / "chunks.json"
    out_path.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal: {len(all_chunks)} chunks salvos em {out_path}")


if __name__ == "__main__":
    main()
