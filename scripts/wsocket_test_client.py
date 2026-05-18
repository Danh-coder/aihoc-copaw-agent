# -*- coding: utf-8 -*-
"""WebSocket test client for custom channel `wsocket`.

This script verifies both directions:
1. Client -> QwenPaw: send text messages over WebSocket.
2. QwenPaw -> Client: receive channel replies over the same connection.

Usage examples:
  python scripts/wsocket_test_client.py
  python scripts/wsocket_test_client.py --mode interactive
  python scripts/wsocket_test_client.py --url ws://127.0.0.1:9101/api/custom/wsocket/ws
  python scripts/wsocket_test_client.py --token your_token

Environment variables:
  WSOCKET_TEST_URL      (default: ws://127.0.0.1:9101/api/custom/wsocket/ws)
  WSOCKET_TEST_SENDER   (default: test_user_001)
  WSOCKET_TEST_TOKEN    (default: empty)
  WSOCKET_TEST_MODE     (default: batch)
  WSOCKET_TEST_TIMEOUT  (default: 30)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import websockets

DEFAULT_MESSAGES = [
    "Hello from wsocket test client.",
    "Please summarize this sentence in one line.",
    "Give me 3 bullet points about local AI assistant setup.",
]


def add_token_to_ws_url(ws_url: str, token: str) -> str:
    """Attach access_token query parameter to URL if provided."""
    if not token:
        return ws_url

    parsed = urlparse(ws_url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    q["access_token"] = token
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(q),
            parsed.fragment,
        )
    )


def build_payload(sender_id: str, text: str) -> str:
    payload: dict[str, Any] = {
        "sender_id": sender_id,
        "text": text,
        "trace_id": uuid.uuid4().hex,
    }
    return json.dumps(payload, ensure_ascii=False)


async def recv_reply(ws: Any, timeout_s: float) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {"raw": data}
    except json.JSONDecodeError:
        return {"raw": raw}


def print_reply(idx: int, data: dict[str, Any]) -> bool:
    if "error" in data:
        print(f"[{idx}] ERROR: {data['error']}")
        return False
    reply = data.get("reply")
    if reply is not None:
        print(f"[{idx}] REPLY: {reply}")
        return True
    print(f"[{idx}] RAW: {data}")
    return True


async def run_batch(ws_url: str, sender_id: str, timeout_s: float) -> int:
    print(f"Connecting: {ws_url}")
    success = 0
    async with websockets.connect(ws_url) as ws:
        print(f"Connected. sender_id={sender_id}")
        for i, text in enumerate(DEFAULT_MESSAGES, start=1):
            print(f"[{i}] SEND: {text}")
            await ws.send(build_payload(sender_id, text))
            data = await recv_reply(ws, timeout_s)
            if print_reply(i, data):
                success += 1
    print(f"Batch done: {success}/{len(DEFAULT_MESSAGES)} responses received")
    return 0 if success == len(DEFAULT_MESSAGES) else 2


async def run_interactive(ws_url: str, sender_id: str, timeout_s: float) -> int:
    print(f"Connecting: {ws_url}")
    async with websockets.connect(ws_url) as ws:
        print(f"Connected. sender_id={sender_id}")
        print('Type a message and press Enter. Type "exit" to quit.')

        loop = asyncio.get_event_loop()
        idx = 1
        while True:
            try:
                text = await loop.run_in_executor(None, lambda: input("YOU> ").strip())
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if text.lower() in {"exit", "quit", "q"}:
                break
            if not text:
                continue

            await ws.send(build_payload(sender_id, text))
            data = await recv_reply(ws, timeout_s)
            print_reply(idx, data)
            idx += 1

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test custom channel wsocket send/receive flow")
    parser.add_argument(
        "--url",
        default=os.getenv("WSOCKET_TEST_URL", "ws://127.0.0.1:9101/api/custom/wsocket/ws"),
        help="WebSocket endpoint URL",
    )
    parser.add_argument(
        "--sender-id",
        default=os.getenv("WSOCKET_TEST_SENDER", "test_user_001"),
        help="sender_id used in test payload",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("WSOCKET_TEST_TOKEN", ""),
        help="Access token (sent as access_token query param)",
    )
    parser.add_argument(
        "--mode",
        choices=["batch", "interactive"],
        default=os.getenv("WSOCKET_TEST_MODE", "batch"),
        help="Run mode",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("WSOCKET_TEST_TIMEOUT", "30")),
        help="Seconds to wait for each reply",
    )
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    ws_url = add_token_to_ws_url(args.url, args.token)

    if args.mode == "interactive":
        return await run_interactive(ws_url, args.sender_id, args.timeout)
    return await run_batch(ws_url, args.sender_id, args.timeout)


def main() -> int:
    try:
        return asyncio.run(_main())
    except TimeoutError:
        print("ERROR: timed out waiting for server reply")
        return 3
    except OSError as exc:
        print(f"ERROR: cannot connect to websocket endpoint: {exc}")
        return 1
    except websockets.exceptions.InvalidStatus as exc:
        print(f"ERROR: websocket handshake failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
