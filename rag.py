# -*- coding: utf-8 -*-
#
# AiVersus – RAG-Modul (Evo V0.3)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
RAG: Dokument -> Chunks -> Embeddings (OpenAI) -> ChromaDB (lokal, Ordner rag_store/) -> Retrieval.
Nutzt denselben OpenAI-Key wie die Modell-Aufrufe.
"""

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import chromadb
from openai import OpenAI

EMBED_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 1000     # Zeichen pro Chunk
CHUNK_OVERLAP = 150   # Überlappung zwischen Chunks


@dataclass
class RetrievedChunk:
    text: str
    source: str
    chunk_index: int


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
    def __init__(self, api_key: str, persist_dir: str = "rag_store"):
        self._client = OpenAI(api_key=api_key)
        self._collection = chromadb.PersistentClient(path=persist_dir).get_or_create_collection("documents")

    def _embed(self, texts: list) -> list:
        resp = self._client.embeddings.create(model=EMBED_MODEL, input=texts)
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
