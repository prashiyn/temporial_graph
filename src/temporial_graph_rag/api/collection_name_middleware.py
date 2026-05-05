"""ASGI middleware: strip ``tg_graph_`` from ``collection_name`` fields in JSON bodies."""

from __future__ import annotations

import json
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from temporial_graph_rag.collection_naming import strip_collection_names_in_json


class CollectionNameExposeMiddleware(BaseHTTPMiddleware):
    """Rewrite JSON responses so ``collection_name`` values are logical (no ``tg_graph_``)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        response = await call_next(request)
        if response.status_code == 204 or response.status_code == 205:
            return response
        mt = (response.media_type or response.headers.get("content-type") or "").lower()
        if "application/json" not in mt:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        if not body:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        try:
            text = body.decode("utf-8")
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        stripped = strip_collection_names_in_json(payload)
        new_text = json.dumps(stripped, default=str, ensure_ascii=False)
        new_body = new_text.encode("utf-8")
        h = dict(response.headers)
        h.pop("content-length", None)
        h["content-length"] = str(len(new_body))
        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=h,
            media_type="application/json",
        )
