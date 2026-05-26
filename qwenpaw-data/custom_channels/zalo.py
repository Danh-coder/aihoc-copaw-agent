# -*- coding: utf-8 -*-
"""Custom channel: zalo. Edit and implement required methods."""
from __future__ import annotations

import asyncio
import json
import inspect
import os
from pathlib import Path
from typing import Any, Callable
import logging
from urllib.parse import quote

from zlapi.Async import ZaloAPI
from zlapi.models import Message, ThreadType

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.schema import ChannelType


logger = logging.getLogger("qwenpaw.custom_channels.zalo")


class QwenPawZaloAPI(ZaloAPI):
    def __init__(self, *args, message_receiver: Callable[..., None] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._message_receiver = message_receiver

    async def onMessage(
        self,
        mid=None,
        author_id=None,
        message=None,
        message_object=None,
        thread_id=None,
        thread_type=ThreadType.USER,
    ):
        if self._message_receiver is None:
            return await super().onMessage(
                mid=mid,
                author_id=author_id,
                message=message,
                message_object=message_object,
                thread_id=thread_id,
                thread_type=thread_type,
            )
        try:
            result = self._message_receiver(
                mid,
                author_id,
                message,
                message_object,
                thread_id,
                thread_type,
            )
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("zalo onMessage dispatch failed")


class CustomChannel(BaseChannel):
    channel: ChannelType = "zalo"
    uses_manager_queue = True

    def __init__(
        self,
        process,
        enabled=True,
        bot_prefix="",
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
        imei="",
        cookies=None,
        phone="",
        password="",
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

        self._imei = imei or os.getenv("ZALO_IMEI", "")
        self._cookies = self._parse_cookies(
            cookies if cookies is not None else os.getenv("ZALO_COOKIES", ""),
        )
        self._phone = phone or os.getenv("ZALO_PHONE", "")
        self._password = password or os.getenv("ZALO_PASSWORD", "")
        self._file_base_url = os.getenv("ZALO_FILE_BASE_URL", "").rstrip("/")

        logger.info(
            "zalo init: enabled=%s imei_set=%s cookies_type=%s",
            self.enabled,
            bool(self._imei),
            type(self._cookies).__name__,
        )
        
        logger.debug(
            "zalo init details: imei=%s cookies=%s",
            self._imei,
            self._cookies,
        )

        self._is_ready = False
        self._listen_task: asyncio.Task | None = None
        self.bot = None
        # Defer SDK construction to start() so initialization can run in a
        # worker thread and never call asyncio.run() inside a running loop.

    def _init_bot_sync(self) -> None:
        """Initialize SDK client in a non-event-loop thread."""
        try:
            self.bot = QwenPawZaloAPI(
                phone=self._phone,
                password=self._password,
                imei=self._imei,
                cookies=self._cookies,
                message_receiver=self._on_message,
            )
        except TypeError:
            logger.exception("zalo init failed: unsupported ZaloAPI constructor")
            self.bot = None
            self._is_ready = False
            return
        except Exception:
            logger.exception("zalo init failed while creating SDK client")
            self.bot = None
            self._is_ready = False
            return

        if self._cookies:
            try:
                logged_in = bool(self.bot.isLoggedIn())
                self._is_ready = logged_in
                logger.info(
                    "zalo auth: cookies_present=%s logged_in=%s",
                    True,
                    logged_in,
                )
            except Exception:
                logger.exception("zalo auth failed while setting cookies")
                self._is_ready = False
        else:
            logger.warning(
                "zalo auth: no cookies configured; channel will not start",
            )

    def _on_message(
        self,
        message_id: str,
        author_id: str,
        text: str,
        native_message: Any,
        thread_id: str,
        thread_type: Any,
    ) -> None:
        logger.info(
            "zalo onMessage: msg_id=%s author=%s thread=%s",
            str(message_id)[:32] + ("..." if len(str(message_id)) > 32 else ""),
            str(author_id)[:32] + ("..." if len(str(author_id)) > 32 else ""),
            str(thread_id)[:32] + ("..." if len(str(thread_id)) > 32 else ""),
        )
        # zlapi dispatches incoming messages via onMessage callback.
        self._on_native_event(
            {
                "message_id": message_id,
                "sender_id": author_id,
                "text": text,
                "thread_id": thread_id,
                "thread_type": getattr(thread_type, "name", str(thread_type)),
                "native": native_message,
            }
        )

    @staticmethod
    def _parse_cookies(raw: Any) -> Any:
        if raw is None or raw == "":
            return {}
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except Exception:
                logger.warning(
                    "zalo config: cookies is not valid JSON; keeping raw string",
                )
                return raw
        return raw

    @staticmethod
    def _extract_field(payload: Any, *keys: str) -> Any:
        if isinstance(payload, dict):
            for key in keys:
                if key in payload and payload[key] not in (None, ""):
                    return payload[key]
        for key in keys:
            value = getattr(payload, key, None)
            if value not in (None, ""):
                return value
        return None

    def _extract_incoming(self, native: Any, *args: Any, **kwargs: Any) -> tuple[str, str, dict]:
        sender_id = ""
        text = ""
        meta = {
            "raw_type": type(native).__name__,
        }

        text_val = self._extract_field(
            native,
            "text",
            "content",
            "message",
            "body",
            "msg",
        )
        if text_val is not None:
            text = str(text_val)

        sender_val = self._extract_field(
            native,
            "sender_id",
            "from_id",
            "author_id",
            "uidFrom",
            "uid",
            "senderId",
        )
        if sender_val is not None:
            sender_id = str(sender_val)

        thread_id_val = self._extract_field(
            native,
            "thread_id",
            "conversation_id",
            "threadId",
            "to_id",
        )
        if thread_id_val is not None:
            meta["thread_id"] = str(thread_id_val)

        thread_type_val = self._extract_field(native, "thread_type", "threadType")
        if thread_type_val is not None:
            meta["thread_type"] = str(thread_type_val)

        message_id_val = self._extract_field(native, "message_id", "msgId", "mid")
        if message_id_val is not None:
            meta["message_id"] = str(message_id_val)

        if not sender_id:
            for item in args:
                guessed = self._extract_field(
                    item,
                    "sender_id",
                    "uidFrom",
                    "author_id",
                    "uid",
                )
                if guessed is not None:
                    sender_id = str(guessed)
                    break

        if not sender_id:
            guessed = kwargs.get("sender_id") or kwargs.get("uidFrom")
            if guessed:
                sender_id = str(guessed)

        if not sender_id and meta.get("thread_id"):
            sender_id = str(meta["thread_id"])

        return sender_id, text.strip(), meta

    def _on_native_event(self, *args: Any, **kwargs: Any) -> None:
        native = args[0] if args else kwargs
        sender_id, text, meta = self._extract_incoming(native, *args, **kwargs)

        logger.info(
            "zalo recv: sender=%s text_len=%s enqueue_ready=%s",
            sender_id[:64] + ("..." if len(sender_id) > 64 else ""),
            len(text),
            self._enqueue is not None,
        )

        if not text:
            logger.debug("zalo recv dropped: empty text payload")
            return
        if not sender_id:
            logger.warning("zalo recv dropped: sender_id missing")
            return

        native_payload = {
            "channel_id": self.channel,
            "sender_id": sender_id,
            "content_parts": [
                TextContent(type=ContentType.TEXT, text=text),
            ],
            "meta": meta,
        }

        if self._enqueue is not None:
            self._enqueue(native_payload)
            logger.info(
                "zalo enqueue queued: sender=%s message_id=%s",
                sender_id[:64] + ("..." if len(sender_id) > 64 else ""),
                str(meta.get("message_id", ""))[:32]
                + ("..." if len(str(meta.get("message_id", ""))) > 32 else ""),
            )
        else:
            logger.warning("zalo recv dropped: _enqueue not set")

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
        **kwargs,
    ):
        cookies = getattr(config, "cookies", None)
        if cookies is None:
            cookies = os.getenv("ZALO_COOKIES", "")
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            bot_prefix=getattr(config, "bot_prefix", ""),
            imei=getattr(config, "imei", "") or os.getenv("ZALO_IMEI", ""),
            cookies=cookies,
            phone=getattr(config, "phone", "") or os.getenv("ZALO_PHONE", "<phone>"),
            password=getattr(config, "password", "") or os.getenv("ZALO_PASSWORD", "<password>"),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
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
            enabled=os.getenv("ZALO_CHANNEL_ENABLED", "0") == "1",
            bot_prefix=os.getenv("ZALO_BOT_PREFIX", ""),
            imei=os.getenv("ZALO_IMEI", ""),
            cookies=os.getenv("ZALO_COOKIES", ""),
            phone=os.getenv("ZALO_PHONE", "<phone>"),
            password=os.getenv("ZALO_PASSWORD", "<password>"),
            on_reply_sent=on_reply_sent,
        )

    def build_agent_request_from_native(self, native_payload: Any):
        logger.info(
            "zalo build_agent_request_from_native: payload_type=%s, payload_keys=%s",
            type(native_payload).__name__,
            list(native_payload.keys()) if isinstance(native_payload, dict) else None,
        )
        
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
        logger.info(
            "zalo request: session=%s sender=%s parts=%s",
            session_id[:64] + ("..." if len(session_id) > 64 else ""),
            sender_id[:32] + ("..." if len(sender_id) > 32 else ""),
            len(content_parts),
        )
        return request

    async def start(self):
        if not self.enabled:
            logger.info("zalo start skipped: channel disabled")
            return

        if self.bot is None:
            await asyncio.to_thread(self._init_bot_sync)

        if self.bot is None:
            logger.warning("zalo start skipped: bot is not initialized")
            return
        if not self._is_ready:
            # Async SDK may need explicit login when cookie session is not
            # available; do this here (inside event loop), not in __init__.
            if self._phone and self._password:
                try:
                    await self.bot.login(
                        self._phone,
                        self._password,
                        self._imei,
                    )
                    self._is_ready = bool(self.bot.isLoggedIn())
                    logger.info(
                        "zalo auth: credential login attempted, logged_in=%s",
                        self._is_ready,
                    )
                except Exception:
                    logger.exception("zalo auth failed during start login")

        if not self._is_ready:
            logger.warning("zalo start skipped: session is not ready")
            return

        if self._listen_task and not self._listen_task.done():
            logger.info("zalo start skipped: listener already running")
            return

        logger.info("zalo start: listener task start")

        self._listen_task = asyncio.create_task(
            self.bot._listen(
                thread=False,
                reconnect=5,
            ),
            name="zalo_listener",
        )
        self._listen_task.add_done_callback(self._on_listener_done)

    def _on_listener_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            logger.info("zalo listener task cancelled")
        except Exception:
            logger.exception("zalo listener task crashed")

    async def stop(self):
        logger.info("zalo stop requested")
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        try:
            ws = getattr(self.bot, "ws", None) if self.bot else None
            if ws is not None:
                ws.close()
        except Exception:
            logger.exception("zalo stop: failed to close websocket")

    async def send(self, to_handle: str, text: str, meta=None):
        # Implement: send text to the channel (e.g. HTTP API).
        # Called by CoPaw to send messages to Zalo users
        if not self._is_ready:
            logger.warning("zalo send skipped: session is not ready")
            return

        out_text = (text or "").strip()
        if not out_text:
            logger.debug("zalo send skipped: empty text")
            return

        thread_type = ThreadType.USER
        meta = meta or {}
        thread_type_name = str(meta.get("thread_type") or "").upper()
        if thread_type_name == "GROUP" and hasattr(ThreadType, "GROUP"):
            thread_type = ThreadType.GROUP

        logger.info(
            "zalo send: to=%s text_len=%s thread_type=%s",
            str(to_handle)[:64],
            len(out_text),
            getattr(thread_type, "name", str(thread_type)),
        )
        try:
            await self.bot.send(
                Message(text=out_text),
                thread_id=to_handle,
                thread_type=thread_type,
            )
            logger.info(
                "zalo send ok: to=%s thread_type=%s",
                str(to_handle)[:64],
                getattr(thread_type, "name", str(thread_type)),
            )
        except Exception:
            logger.exception("zalo send failed: to=%s", str(to_handle)[:64])
            raise

    @staticmethod
    def _resolve_thread_type(meta: dict[str, Any]) -> Any:
        thread_type = ThreadType.USER
        thread_type_name = str(meta.get("thread_type") or "").upper()
        if thread_type_name == "GROUP" and hasattr(ThreadType, "GROUP"):
            thread_type = ThreadType.GROUP
        return thread_type

    def _to_zalo_remote_file_url(self, file_ref: str) -> str | None:
        if not file_ref:
            return None
        ref = str(file_ref).strip()
        if not ref:
            return None
        if ref.startswith("http://") or ref.startswith("https://"):
            return ref
        if ref.startswith("file://"):
            if not self._file_base_url:
                return None
            local_path = ref[len("file://") :]
            normalized = local_path.replace("\\", "/").lstrip("/")
            return f"{self._file_base_url}/files/preview/{quote(normalized, safe='/')}"
        return None

    async def send_content_parts(self, to_handle: str, parts, meta=None):
        meta = meta or {}
        text_parts = []
        file_parts = []

        for part in parts or []:
            part_type = getattr(part, "type", None)
            if part_type == ContentType.TEXT and getattr(part, "text", None):
                text_parts.append(str(part.text))
            elif (
                part_type == ContentType.REFUSAL
                and getattr(part, "refusal", None)
            ):
                text_parts.append(str(part.refusal))
            elif part_type == ContentType.FILE:
                file_parts.append(part)

        body = "\n".join(text_parts).strip()
        if body:
            await self.send(to_handle, body, meta)

        if not file_parts:
            return

        thread_type = self._resolve_thread_type(meta)
        for part in file_parts:
            file_ref = getattr(part, "file_url", None) or getattr(
                part,
                "file_id",
                None,
            )
            if not file_ref:
                continue

            remote_url = self._to_zalo_remote_file_url(str(file_ref))
            filename = getattr(part, "filename", None) or Path(
                str(file_ref).replace("file://", ""),
            ).name

            if not remote_url:
                await self.send(
                    to_handle,
                    f"[File: {file_ref}]\nKhong the gui tep truc tiep qua Zalo voi duong dan local. Neu can gui tep truc tiep, dat ZALO_FILE_BASE_URL den host public cua QwenPaw.",
                    meta,
                )
                continue

            try:
                await self.bot.sendRemoteFile(
                    remote_url,
                    thread_id=to_handle,
                    thread_type=thread_type,
                    fileName=filename or "attachment",
                )
                logger.info(
                    "zalo send file ok: to=%s file=%s",
                    str(to_handle)[:64],
                    str(filename)[:128],
                )
            except Exception:
                logger.exception(
                    "zalo send file failed: to=%s file=%s",
                    str(to_handle)[:64],
                    str(file_ref)[:160],
                )
                await self.send(
                    to_handle,
                    f"[File: {file_ref}]\nGui tep truc tiep that bai, vui long mo link tep thu cong.",
                    meta,
                )
