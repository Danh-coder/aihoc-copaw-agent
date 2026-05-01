---
name: rag_sources_qa
description: Query uploaded RAG Sources from CoPaw and answer with citations.
---

# RAG Sources QA

Use this skill when the user asks questions that should be answered from uploaded RAG Sources.

## Preconditions
- Prefer this skill when user asks about uploaded internal documents.
- If no sources are available, ask user to upload documents first.

## Steps
1. Resolve API base URL first, then check source status via `GET {base}/api/sources/`.
   - Preferred local bases in order: `http://localhost:8088`, `http://127.0.0.1:8088`, `http://localhost:8080`.
   - If env var `COPAW_API_BASE` exists, try it first.
   - Do not conclude "no source files" unless the API call succeeds and returns an empty list.
2. If relevant source is `queued` or `processing`, inform user indexing is still running.
3. For retrieval, call `POST {base}/api/sources/query` with JSON:
   - `query`: user question
   - `top_k`: 3 to 8
4. Use returned chunks and source ids as evidence.
5. If `{base}/api/sources/answer` is available and healthy, you may call it; otherwise synthesize answer directly from `/query` results.

## Tooling Guidance
- Use `execute_shell_command` to run a short Python `requests` snippet for API calls.
- Use this probing pattern before any RAG call:

```python
import os, requests
bases = []
if os.getenv("COPAW_API_BASE"):
   bases.append(os.getenv("COPAW_API_BASE").rstrip("/"))
bases += ["http://localhost:8088", "http://127.0.0.1:8088", "http://localhost:8080"]

base = None
for b in bases:
   try:
      r = requests.get(f"{b}/api/sources/", timeout=3)
      if r.status_code == 200:
         base = b
         break
   except Exception:
      pass

if not base:
   raise RuntimeError("RAG API unavailable on all known local ports")
```
- Do not fabricate facts; only answer from returned chunks.
- Include source citations like `[Source <id>]`.

## Failure Handling
- If query API returns errors, report exact error and suggest reindexing via `POST /api/sources/{source_id}/reindex`.
- If no matches are returned, say no relevant evidence was found in current uploaded sources.
- If API is unreachable, report the exact attempted base URLs and ask user to verify current mapped port.
