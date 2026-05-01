# -*- coding: utf-8 -*-
import os
from .db import SessionLocal, Source, Chunk, init_db
from .clients import EmbeddingClient, QrandtClient
import uuid
import math
import logging

logger = logging.getLogger(__name__)


def _resolve_source_path(file_path: str) -> str:
    """Resolve legacy or relative source paths to the mounted working directory."""
    if not file_path:
        return file_path

    candidates = []
    if os.path.isabs(file_path):
        candidates.append(file_path)
    else:
        candidates.append(os.path.abspath(file_path))
        candidates.append(os.path.join("/app/working", file_path))

    # Legacy DB values often used qwenpaw-data/sources/... while volume is /app/working
    legacy_prefix = "qwenpaw-data/"
    if file_path.startswith(legacy_prefix):
        candidates.append(os.path.join("/app/working", file_path[len(legacy_prefix) :]))

    basename = os.path.basename(file_path)
    if basename:
        candidates.append(os.path.join("/app/working/sources", basename))

    seen = set()
    for path in candidates:
        norm = os.path.abspath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.exists(norm):
            return norm
    return os.path.abspath(file_path)


def _extract_text_from_pdf(path: str) -> str:
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(path)
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n\n".join(pages)
    except Exception:
        # fallback: return empty string (keep demo simple)
        logger.exception("PyPDF2 not available or failed to extract")
        return ""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200):
    if not text:
        return []
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append((start, end, text[start:end]))
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks


def ingest_source(source_id: int, file_path: str):
    """Process file: extract text, chunk, embed, and upsert to qrandt."""
    init_db()
    db = SessionLocal()
    src = None
    try:
        src = db.query(Source).filter(Source.id == source_id).first()
        if not src:
            logger.error("Source not found: %s", source_id)
            return

        src.status = "processing"
        db.commit()

        resolved_path = _resolve_source_path(file_path)
        if not os.path.exists(resolved_path):
            raise FileNotFoundError(f"Source file not found: {file_path} (resolved: {resolved_path})")

        if src.filename != resolved_path:
            src.filename = resolved_path
            db.commit()

        text = _extract_text_from_pdf(resolved_path)
        chunks = chunk_text(text)
        if not chunks:
            logger.warning("No text chunks extracted for source %s", source_id)
            src.status = "failed"
            db.commit()
            return

        emb_client = None
        q_client = None
        vector_ready = True
        try:
            emb_client = EmbeddingClient()
            q_client = QrandtClient()
        except Exception:
            logger.exception("Vector clients init failed for source %s; continuing without vectors", source_id)
            vector_ready = False

        texts = [c[2] for c in chunks]
        embeddings = []
        if texts and vector_ready and emb_client is not None:
            try:
                embeddings = emb_client.embed_texts(texts)
            except Exception:
                logger.exception("Embedding failed for source %s; continuing without vectors", source_id)
                embeddings = []
                vector_ready = False

        vector_items = []
        for idx, (start, end, txt) in enumerate(chunks):
            chunk = Chunk(source_id=source_id, text=txt, page=None, char_start=start, char_end=end)
            db.add(chunk)
            db.commit()
            db.refresh(chunk)

            vec = embeddings[idx] if idx < len(embeddings) else None
            vector_id = f"source-{source_id}-chunk-{chunk.id}-{uuid.uuid4().hex[:8]}"
            chunk.vector_id = vector_id
            db.commit()

            if vec:
                vector_items.append({"id": vector_id, "values": vec, "metadata": {"chunk_id": chunk.id, "source_id": source_id}})

        if vector_items and vector_ready and q_client is not None:
            try:
                q_client.upsert(vector_items)
            except Exception:
                logger.exception("Vector upsert failed for source %s; chunks were still persisted", source_id)

        src.status = "done"
        db.commit()
    except Exception:
        logger.exception("Ingestion failed for source %s", source_id)
        if src:
            src.status = "failed"
            db.commit()
    finally:
        db.close()


def search_query(query: str, top_k: int = 5):
    init_db()
    db = SessionLocal()
    try:
        # Primary path: embedding + vector search.
        try:
            emb_client = EmbeddingClient()
            q_client = QrandtClient()
            qvec = emb_client.embed_texts([query])
            if qvec:
                qvec = qvec[0]
                res = q_client.search(qvec, top_k=top_k)
                # Expect items like: {"id":..., "score":..., "metadata":{...}}
                items = []
                for hit in res.get("matches", []) if isinstance(res, dict) else []:
                    metadata = hit.get("metadata", {})
                    chunk_id = metadata.get("chunk_id")
                    chunk = db.query(Chunk).filter(Chunk.id == chunk_id).first() if chunk_id else None
                    if chunk:
                        items.append(
                            {
                                "score": hit.get("score"),
                                "text": chunk.text,
                                "chunk_id": chunk.id,
                                "source_id": chunk.source_id,
                            }
                        )
                if items:
                    return items
        except Exception:
            logger.exception("Vector retrieval failed; falling back to lexical search")

        # Fallback path for demo reliability: lexical match in stored chunks.
        q = (query or "").strip()
        if not q:
            return []
        pattern = f"%{q}%"
        rows = (
            db.query(Chunk)
            .filter(Chunk.text.ilike(pattern))
            .order_by(Chunk.id.desc())
            .limit(top_k)
            .all()
        )
        return [
            {
                "score": None,
                "text": c.text,
                "chunk_id": c.id,
                "source_id": c.source_id,
            }
            for c in rows
        ]
    finally:
        db.close()
