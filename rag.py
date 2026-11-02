# -*- coding: utf-8 -*-
#
# AiVersus – RAG-Modul (Evo V0.3)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
RAG: Dokument -> Chunks -> Embeddings (NVIDIA Build) -> ChromaDB (lokal, Ordner rag_store/) -> Retrieval.
Nutzt denselben NVIDIA-Build-Key wie die Modell-Aufrufe. Das Embedding-Modell wird live aus dem
Katalog gewählt (siehe models.fetch_embedding_models), nicht fest verdrahtet - NVIDIA Build
entfernt/ersetzt Modelle, siehe models.py.
"""

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

CHUNK_SIZE = 1000     # Zeichen pro Chunk
CHUNK_OVERLAP = 150   # Überlappung zwischen Chunks


@dataclass
class RetrievedChunk:
    text: str
    source: str
    chunk_index: int


class EmbedModelMismatch(Exception):
    """Die Collection enthält bereits Embeddings eines anderen Modells.

    Vektoren verschiedener Embedding-Modelle sind nicht vergleichbar (oft sogar
    unterschiedliche Dimension) - ein stillschweigendes Mischen würde das Retrieval
    unbemerkt kaputt machen, deshalb wird der Wechsel verweigert statt ihn zuzulassen.
    """

    def __init__(self, stored_model: str, requested_model: str):
        self.stored_model = stored_model
        self.requested_model = requested_model
        super().__init__(f"Collection wurde mit {stored_model!r} aufgebaut, nicht {requested_model!r}.")


def clear_persisted_collection(persist_dir: str, embed_model: str | None = None) -> None:
    """Leert die Collection ohne eine RagIndex-Instanz - Rettungsweg für den Fall, dass

    RagIndex.__init__ selbst wegen EmbedModelMismatch nicht durchläuft (dann gibt es noch
    kein Objekt, auf dem man .clear() aufrufen könnte).
    """
    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)
    try:
        collection = client.get_collection("documents")
    except Exception:
        return
    ids = collection.get()["ids"]
    if ids:
        collection.delete(ids=ids)
    collection.modify(metadata={"embed_model": embed_model} if embed_model else {})


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    if suffix in (".txt", ".md"):
        return data.decode("utf-8", errors="ignore")
    raise ValueError(f"Dateityp {suffix!r} nicht unterstützt (PDF, TXT, MD).")


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """Sliding-Window über Zeichen, mit Überlappung."""
    text = text.strip()
    chunks, start = [], 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break
        start += size - overlap
    return chunks


class RagIndex:
    def __init__(self, api_key: str, base_url: str, embed_model: str, persist_dir: str = "rag_store"):
        import chromadb  # lazy - schwere Abhängigkeit, nur laden, wenn RAG tatsächlich genutzt wird

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._embed_model = embed_model
        collection = chromadb.PersistentClient(path=persist_dir).get_or_create_collection("documents")
        # Eine Collection, ein Embedding-Modell pro Collection via Metadaten statt eine Collection
        # pro Modell (Modell-IDs enthalten "/", keine gültigen ChromaDB-Collection-Namen) - bei
        # Abweichung mit vorhandenen Chunks wird verweigert (siehe EmbedModelMismatch), ist die
        # Collection leer (z.B. nach .clear()), wird das neue Modell stillschweigend übernommen.
        stored_model = (collection.metadata or {}).get("embed_model")
        if stored_model is None:
            collection.modify(metadata={"embed_model": embed_model})
        elif stored_model != embed_model:
            if collection.count() > 0:
                raise EmbedModelMismatch(stored_model, embed_model)
            collection.modify(metadata={"embed_model": embed_model})
        self._collection = collection

    def _embed(self, texts: list) -> list:
        resp = self._client.embeddings.create(model=self._embed_model, input=texts)
        return [item.embedding for item in resp.data]

    def add_document(self, filename: str, data: bytes) -> int:
        """Text extrahieren, chunken, embedden, speichern. Gibt die Chunk-Anzahl zurück."""
        chunks = chunk_text(extract_text(filename, data))
        if not chunks:
            return 0
        ids = [hashlib.sha256(f"{filename}:{i}:{c[:50]}".encode()).hexdigest() for i, c in enumerate(chunks)]
        self._collection.upsert(
            ids=ids,
            embeddings=self._embed(chunks),
            documents=chunks,
            metadatas=[{"source": filename, "chunk_index": i} for i in range(len(chunks))],
        )
        return len(chunks)

    def retrieve(self, query: str, top_k: int = 4) -> list:
        """Die top_k ähnlichsten Chunks zur Anfrage."""
        if self._collection.count() == 0:
            return []
        res = self._collection.query(query_embeddings=self._embed([query]), n_results=top_k)
        return [
            RetrievedChunk(text=doc, source=meta["source"], chunk_index=meta["chunk_index"])
            for doc, meta in zip(res["documents"][0], res["metadatas"][0])
        ]

    def sources(self) -> dict:
        """{Dateiname: Anzahl Chunks} aller indexierten Dokumente."""
        counts = {}
        for meta in self._collection.get(include=["metadatas"])["metadatas"] or []:
            counts[meta["source"]] = counts.get(meta["source"], 0) + 1
        return counts

    def document_count(self) -> int:
        return self._collection.count()

    def clear(self) -> None:
        ids = self._collection.get()["ids"]
        if ids:
            self._collection.delete(ids=ids)


def build_prompt(question: str, chunks: list) -> str:
    """Setzt den abgerufenen Kontext vor die eigentliche Frage."""
    if not chunks:
        return question
    context = "\n\n---\n\n".join(f"[Quelle: {c.source}, Abschnitt {c.chunk_index}]\n{c.text}" for c in chunks)
    return (
        "Beantworte die Frage ausschließlich auf Basis des folgenden Kontexts. "
        "Steht die Antwort nicht im Kontext, sag das ausdrücklich, statt zu spekulieren.\n\n"
        f"Kontext:\n{context}\n\nFrage: {question}"
    )
