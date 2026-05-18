# -*- coding: utf-8 -*-
"""Custom channel: wsocket. Edit and implement required methods."""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import aiohttp
from aiohttp import web

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.schema import ChannelType


logger = logging.getLogger("qwenpaw.custom_channels.wsocket")


class CustomChannel(BaseChannel):
    channel: ChannelType = "wsocket"
    uses_manager_queue = True
    requires_sequential_reload = True

    def __init__(
        self,
        process,
        enabled=True,
        bot_prefix="",
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
        ws_host="0.0.0.0",
        ws_port=9101,
        ws_path="/api/custom/wsocket/ws",
        access_token="",
        **kwargs,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix or ""
        self._ws_host = ws_host or "0.0.0.0"
        self._ws_port = int(ws_port or 9101)
        self._ws_path = ws_path or "/api/custom/wsocket/ws"
        self._access_token = access_token or os.getenv("WSOCKET_ACCESS_TOKEN", "")

        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._connections: set[web.WebSocketResponse] = set()
        self._user_connections: dict[str, set[web.WebSocketResponse]] = {}
        self._connection_ids: dict[web.WebSocketResponse, str] = {}
        self._connections_by_id: dict[str, web.WebSocketResponse] = {}

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
        **kwargs,
    ):
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            bot_prefix=getattr(config, "bot_prefix", ""),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            ws_host=getattr(config, "ws_host", "0.0.0.0"),
            ws_port=getattr(config, "ws_port", 9101),
            ws_path=getattr(config, "ws_path", "/api/custom/wsocket/ws"),
            access_token=getattr(config, "access_token", "") or os.getenv("WSOCKET_ACCESS_TOKEN", ""),
            filter_tool_messages=kwargs.get(
                "filter_tool_messages",
                getattr(config, "filter_tool_messages", False),
            ),
            filter_thinking=kwargs.get(
                "filter_thinking",
                getattr(config, "filter_thinking", False),
            ),
        )

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(
            process=process,
            enabled=os.getenv("WSOCKET_CHANNEL_ENABLED", "0") == "1",
            bot_prefix=os.getenv("WSOCKET_BOT_PREFIX", ""),
            ws_host=os.getenv("WSOCKET_HOST", "0.0.0.0"),
            ws_port=int(os.getenv("WSOCKET_PORT", "9101")),
            ws_path=os.getenv("WSOCKET_PATH", "/api/custom/wsocket/ws"),
            access_token=os.getenv("WSOCKET_ACCESS_TOKEN", ""),
            on_reply_sent=on_reply_sent,
        )

    def build_agent_request_from_native(self, native_payload: Any):
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        content_parts = payload.get("content_parts") or []
        if not content_parts:
            text = payload.get("text", "")
            content_parts = [TextContent(type=ContentType.TEXT, text=text)]
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    def merge_native_items(self, items):
        if not items:
            return None
        first = items[0] if isinstance(items[0], dict) else {}
        merged_parts = []
        merged_meta = dict(first.get("meta") or {})

        for item in items:
            payload = item if isinstance(item, dict) else {}
            merged_parts.extend(payload.get("content_parts") or [])
            meta = payload.get("meta") or {}
            merged_meta.update(meta)

        return {
            "channel_id": first.get("channel_id") or self.channel,
            "sender_id": first.get("sender_id") or "",
            "content_parts": merged_parts,
            "meta": merged_meta,
        }

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        if self._access_token:
            auth_header = request.headers.get("Authorization", "")
            query_token = request.query.get("access_token", "")
            valid = (
                auth_header == f"Bearer {self._access_token}"
                or auth_header == f"Token {self._access_token}"
                or query_token == self._access_token
            )
            if not valid:
                return web.Response(status=401, text="Unauthorized")

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        conn_id = uuid.uuid4().hex
        self._connections.add(ws)
        self._connection_ids[ws] = conn_id
        self._connections_by_id[conn_id] = ws

        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue

                raw_text = (msg.data or "").strip()
                if not raw_text:
                    continue

                try:
                    body = json.loads(raw_text)
                    if not isinstance(body, dict):
                        body = {"text": str(body)}
                except json.JSONDecodeError:
                    body = {"text": raw_text}

                sender_id = str(
                    body.get("sender_id")
                    or body.get("user_id")
                    or body.get("from")
                    or body.get("from_id")
                    or ""
                ).strip()
                if not sender_id:
                    sender_id = f"anon:{conn_id}"

                text = str(
                    body.get("text")
                    or body.get("message")
                    or body.get("content")
                    or ""
                ).strip()
                if not text:
                    await ws.send_str(json.dumps({"error": "'text' field is required"}))
                    continue

                self._user_connections.setdefault(sender_id, set()).add(ws)

                meta = {
                    k: v
                    for k, v in body.items()
                    if k not in {"sender_id", "user_id", "from", "from_id", "text", "message", "content"}
                }
                meta["connection_id"] = conn_id
                meta["remote"] = str(request.remote or "")

                native_payload = {
                    "channel_id": self.channel,
                    "sender_id": sender_id,
                    "content_parts": [TextContent(type=ContentType.TEXT, text=text)],
                    "meta": meta,
                }

                if self._enqueue is None:
                    await ws.send_str(json.dumps({"error": "channel queue is not ready"}))
                    continue

                self._enqueue(native_payload)
        except Exception:
            logger.exception("wsocket websocket loop error")
        finally:
            self._connections.discard(ws)
            conn_id = self._connection_ids.pop(ws, None)
            if conn_id:
                self._connections_by_id.pop(conn_id, None)
            empty_users = []
            for user_id, conns in self._user_connections.items():
                conns.discard(ws)
                if not conns:
                    empty_users.append(user_id)
            for user_id in empty_users:
                self._user_connections.pop(user_id, None)

        return ws

    async def start(self):
        if not self.enabled:
            logger.info("wsocket start skipped: channel disabled")
            return
        if self._runner is not None:
            logger.info("wsocket start skipped: server already running")
            return

        self._app = web.Application()
        self._app.router.add_get(self._ws_path, self._handle_ws)
        self._app.router.add_get(f"{self._ws_path}/", self._handle_ws)

        self._runner = web.AppRunner(self._app)
        try:
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._ws_host, self._ws_port)
            await self._site.start()
            logger.info(
                "wsocket listening on ws://%s:%s%s",
                self._ws_host,
                self._ws_port,
                self._ws_path,
            )
        except OSError as exc:
            logger.error(
                "wsocket start failed: bind ws://%s:%s%s failed: %s",
                self._ws_host,
                self._ws_port,
                self._ws_path,
                exc,
            )
            if self._runner is not None:
                try:
                    await self._runner.cleanup()
                except Exception:
                    logger.exception("wsocket start cleanup failed after bind error")
            self._runner = None
            self._site = None
            self._app = None
            raise
        except Exception:
            logger.exception(
                "wsocket start failed: ws://%s:%s%s",
                self._ws_host,
                self._ws_port,
                self._ws_path,
            )
            if self._runner is not None:
                try:
                    await self._runner.cleanup()
                except Exception:
                    logger.exception("wsocket start cleanup failed")
            self._runner = None
            self._site = None
            self._app = None
            raise

    async def stop(self):
        for ws in list(self._connections):
            try:
                await ws.close()
            except Exception:
                logger.exception("wsocket stop: failed to close websocket")
        self._connections.clear()
        self._user_connections.clear()
        self._connection_ids.clear()
        self._connections_by_id.clear()

        if self._site is not None:
            await self._site.stop()
            self._site = None

        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

        self._app = None

    async def send(self, to_handle: str, text: str, meta=None):
        out_text = (text or "").strip()
        if not out_text:
            return

        meta = meta or {}
        payload = {
            "reply": out_text,
            "user_id": to_handle,
            "channel": self.channel,
        }
        message_id = meta.get("message_id")
        if message_id:
            payload["message_id"] = str(message_id)

        body = json.dumps(payload, ensure_ascii=False)

        primary_ws = None
        connection_id = meta.get("connection_id")
        if connection_id:
            ws_by_id = self._connections_by_id.get(str(connection_id))
            if isinstance(ws_by_id, web.WebSocketResponse) and not ws_by_id.closed:
                primary_ws = ws_by_id
        targets: list[web.WebSocketResponse] = []
        if isinstance(primary_ws, web.WebSocketResponse) and not primary_ws.closed:
            targets = [primary_ws]
        else:
            for ws in self._user_connections.get(to_handle, set()):
                if not ws.closed:
                    targets.append(ws)

        if not targets:
            logger.warning(
                "wsocket send skipped: no websocket for to_handle=%s",
                to_handle,
            )
            return

        for ws in targets:
            try:
                await ws.send_str(body)
            except Exception:
                logger.exception(
                    "wsocket send failed: to_handle=%s",
                    to_handle,
                )
