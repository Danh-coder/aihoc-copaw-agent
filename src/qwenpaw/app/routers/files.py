# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

router = APIRouter(prefix="/files", tags=["files"])


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file",
)
async def preview_file(
    filepath: str,
):
    """Preview file."""
    raw = (filepath or "").strip()
    path = Path(raw)

    # Accept both "C:/..." and "/C:/..." forms on Windows.
    if os.name == "nt":
        if re.match(r"^[a-zA-Z]:[\\/]", raw):
            path = Path(raw)
        elif raw.startswith("/") and re.match(r"^[a-zA-Z]:[\\/]", raw[1:]):
            path = Path(raw[1:])

    if not path.is_absolute():
        path = Path("/" + raw)

    path = path.resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=path.name)
