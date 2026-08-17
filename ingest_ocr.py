"""
Fase 2 do pipeline RAG — ingestão.

Fluxo: PDF -> texto por página -> limpeza -> chunking -> data/chunks/chunks.json

Cada arquivo do corpus usa um método de extração diferente, decidido na
Fase 1 (ver PLANEJAMENTO.md):
  - "text": extração direta do texto embutido no PDF (Basic Rules, SRD).
  - "ocr":  o PDF tem o mapeamento de fonte quebrado (parece OCR ruim de
            origem), então extraímos renderizando cada página como imagem
            e rodando OCR do zero com Tesseract (Player's Handbook).

O resultado de cada etapa cara (extração de página, sobretudo o OCR) é
cacheado em disco, então rodar o script de novo não reprocessa do zero.

Uso:
    python src/ingest.py
"""

import json
import re
import time
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
CHUNKS_DIR = ROOT / "data" / "chunks"
RAW_PAGES_DIR = CHUNKS_DIR / "_raw_pages"

# Adicionar diretório do tesseract.exe
TESSERACT_EXE = r""
pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

# Páginas com menos que isso de texto útil são tratadas como "só imagem"
# e descartadas (não viram chunk).
MIN_USEFUL_CHARS = 40

CHUNK_SIZE_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150

# (arquivo, método de extração, nome curto usado nas citações)
SOURCES = [
    (DOCS / "Basic Rules" / "Player's Basic Rules.pdf", "text", "Basic Rules"),
    (DOCS / "SRD" / "System Reference Document.pdf", "text", "SRD"),
    (DOCS / "Core" / "Player's Handbook.pdf", "ocr", "Player's Handbook"),
]


def clean_text(text: str) -> str:
    """Normaliza espaçamento sem tentar reescrever o conteúdo.

    O SRD extrai com \xa0 (espaço não-quebrável) e \r soltos no lugar de
    espaço/quebra de linha normal — sem isso os chunks ficam com esses
    caracteres literais espalhados entre as palavras.
    """
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(page: fitz.Page) -> str:
    return page.get_text("text")


def ocr_page_text(page: fitz.Page) -> str:
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(img, lang="eng")


def extract_pages(pdf_path: Path, method: str) -> dict[int, str]:
    """
    Retorna {página (1-indexed): texto bruto} para todo o PDF.

    Usa um cache em disco por arquivo (data/chunks/_raw_pages/<nome>.json)
    porque o caminho "ocr" é lento (centenas de páginas) e não deve
    reprocessar do zero a cada execução do script.
    """
    RAW_PAGES_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_PAGES_DIR / f"{pdf_path.stem}.json"

    cached: dict[str, str] = {}
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    pages: dict[int, str] = {int(k): v for k, v in cached.items()}

    extractor = ocr_page_text if method == "ocr" else extract_page_text
    label = "OCR" if method == "ocr" else "texto direto"

    new_pages = 0
    start = time.time()
    for i in range(total_pages):
        page_num = i + 1
        if page_num in pages:
            continue
        pages[page_num] = extractor(doc[i])
        new_pages += 1
        if method == "ocr" and new_pages % 20 == 0:
            elapsed = time.time() - start
            print(f"  [{pdf_path.name}] OCR: {page_num}/{total_pages} páginas ({elapsed:.0f}s)")
            cache_path.write_text(json.dumps(pages, ensure_ascii=False, indent=0), encoding="utf-8")
    doc.close()

    if new_pages:
        cache_path.write_text(json.dumps(pages, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"  [{pdf_path.name}] {new_pages} páginas extraídas via {label}, cache salvo em {cache_path.name}")
    else:
        print(f"  [{pdf_path.name}] {total_pages} páginas já em cache ({cache_path.name})")

    return pages


def chunk_page_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Divide o texto de UMA página em pedaços de tamanho fixo com overlap.

    Chunking fica contido dentro da página de propósito: cada chunk tem
    exatamente uma página de origem, então a citação (\"p. X\") nunca é
    ambígua. Ver PLANEJAMENTO.md Fase 2 — estratégia simples escolhida
    dado o prazo.
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


def build_chunks(pdf_path: Path, method: str, source_label: str) -> list[dict]:
    pages = extract_pages(pdf_path, method)
    chunks = []
    skipped_pages = 0

    for page_num in sorted(pages):
        text = clean_text(pages[page_num])
        if len(text) < MIN_USEFUL_CHARS:
            skipped_pages += 1
            continue
        for i, piece in enumerate(chunk_page_text(text, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS)):
            chunks.append(
                {
                    "id": f"{pdf_path.stem}_p{page_num}_{i}",
                    "text": piece,
                    "source": source_label,
                    "file": pdf_path.name,
                    "page": page_num,
                }
            )

    print(f"  [{pdf_path.name}] {len(chunks)} chunks, {skipped_pages} páginas descartadas (só imagem/pouco texto)")
    return chunks


def main():
    all_chunks = []
    for pdf_path, method, source_label in SOURCES:
        if not pdf_path.exists():
            print(f"AUSENTE: {pdf_path}")
            continue
        print(f"Ingerindo {pdf_path.name} (método: {method})...")
        all_chunks.extend(build_chunks(pdf_path, method, source_label))

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHUNKS_DIR / "chunks.json"
    out_path.write_text(json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal: {len(all_chunks)} chunks salvos em {out_path}")


if __name__ == "__main__":
    main()
