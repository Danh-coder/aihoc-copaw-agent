# -*- coding: utf-8 -*-
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import os
from ...rag.db import init_db, SessionLocal, Source
from ...rag.ingest import ingest_source, search_query
from ...rag.clients import LLMClient
import shutil
import uuid

router = APIRouter(prefix="/sources", tags=["sources"])

DATA_DIR = os.path.abspath(os.environ.get("RAG_DATA_DIR", "/app/working/sources"))
os.makedirs(DATA_DIR, exist_ok=True)


@router.on_event("startup")
def _startup():
    init_db()


@router.post("/upload")
async def upload_source(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    # Save file to disk and create DB record, then enqueue ingestion
    filename = file.filename
    source_name = os.path.splitext(filename)[0]
    tmp_id = uuid.uuid4().hex[:8]
    dest_filename = f"{int(uuid.uuid4().int>>64)}_{filename}"
    dest_path = os.path.abspath(os.path.join(DATA_DIR, dest_filename))
    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    db = SessionLocal()
    try:
        src = Source(name=source_name, filename=dest_path, status="queued")
        db.add(src)
        db.commit()
        db.refresh(src)
        # schedule background ingestion
        if background_tasks is not None:
            background_tasks.add_task(ingest_source, src.id, dest_path)
        else:
            # fallback: fire-and-forget
            import threading

            threading.Thread(target=ingest_source, args=(src.id, dest_path), daemon=True).start()

        return JSONResponse({"source_id": src.id, "status": "queued"})
    finally:
        db.close()


def _list_sources_impl():
    db = SessionLocal()
    try:
        items = db.query(Source).order_by(Source.created_at.desc()).all()
        out = [{"id": s.id, "name": s.name, "filename": s.filename, "status": s.status} for s in items]
        return out
    finally:
        db.close()


@router.get("")
def list_sources_no_trailing_slash():
    return _list_sources_impl()


@router.get("/")
def list_sources_with_trailing_slash():
    return _list_sources_impl()


@router.post("/{source_id}/reindex")
def reindex_source(source_id: int, background_tasks: BackgroundTasks = None):
    db = SessionLocal()
    try:
        src = db.query(Source).filter(Source.id == source_id).first()
        if not src:
            raise HTTPException(status_code=404, detail="source not found")
        src.status = "queued"
        db.commit()
        if background_tasks is not None:
            background_tasks.add_task(ingest_source, src.id, src.filename)
        else:
            import threading

            threading.Thread(target=ingest_source, args=(src.id, src.filename), daemon=True).start()
        return {"status": "queued"}
    finally:
        db.close()


@router.post("/query")
def query(body: dict):
    q = body.get("query") if isinstance(body, dict) else None
    if not q:
        raise HTTPException(status_code=400, detail="query required")
    items = search_query(q, top_k=body.get("top_k", 5))
    return {"query": q, "results": items}


@router.post("/answer")
def answer(body: dict):
    q = body.get("query") if isinstance(body, dict) else None
    top_k = int(body.get("top_k", 5)) if isinstance(body, dict) else 5
    if not q:
        raise HTTPException(status_code=400, detail="query required")

    # Retrieve candidate chunks
    items = search_query(q, top_k=top_k)

    # Assemble prompt
    context_parts = []
    sources = []
    for i, it in enumerate(items):
        txt = it.get("text", "")
        sid = it.get("source_id")
        cid = it.get("chunk_id")
        context_parts.append(f"[Source {sid} | Chunk {cid}] {txt}")
        sources.append({"source_id": sid, "chunk_id": cid})

    prompt = "You are an assistant. Use the following sources to answer the question.\n\n"
    prompt += "\n\n".join(context_parts)
    prompt += f"\n\nQuestion: {q}\nAnswer concisely and cite sources like [Source <id>]."

    llm = LLMClient()
    try:
        answer_text = llm.generate(prompt, max_tokens=512)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM call failed: {e}")

    return {"answer": answer_text, "sources": sources}
