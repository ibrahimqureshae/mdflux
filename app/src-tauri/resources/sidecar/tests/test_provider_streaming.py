import asyncio
import json
import sys
import unittest
from pathlib import Path


SIDECAR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIDECAR_DIR))

import provider  # noqa: E402
import main as sidecar_main  # noqa: E402


def _sse(text: str) -> bytes:
    event = {"choices": [{"delta": {"content": text}}]}
    return f"data: {json.dumps(event)}\n\n".encode()


class OpenAIStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.responder = None

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                content_length = 0
                for line in head.decode(errors="replace").split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                if content_length:
                    await reader.readexactly(content_length)
                await self.responder(writer)
            except (ConnectionError, asyncio.IncompleteReadError):
                # Cancellation intentionally closes the client socket while the
                # fixture server may still be writing the next token.
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}/v1"

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def test_generation_can_exceed_idle_window_when_data_keeps_arriving(self):
        async def respond(writer):
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
            for piece in ("one", " ", "two", " ", "three"):
                await asyncio.sleep(0.04)
                writer.write(_sse(piece))
                await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()

        self.responder = respond
        result = await provider.chat_openai_compat(
            self.base_url, "key", "model", "system", "user",
            idle_timeout=0.08,
        )
        self.assertEqual(result, "one two three")

    async def test_silent_stream_raises_provider_idle_timeout(self):
        async def respond(writer):
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
            await asyncio.sleep(0.12)

        self.responder = respond
        with self.assertRaises(provider.ProviderIdleTimeout):
            await provider.chat_openai_compat(
                self.base_url, "key", "model", "system", "user",
                idle_timeout=0.04,
            )

    async def test_cancel_event_aborts_an_active_stream(self):
        async def respond(writer):
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
            for piece in ("one", "two", "three"):
                await asyncio.sleep(0.02)
                writer.write(_sse(piece))
                await writer.drain()

        self.responder = respond
        cancelled = asyncio.Event()

        def mark_activity():
            cancelled.set()

        with self.assertRaises(asyncio.CancelledError):
            await provider.chat_openai_compat(
                self.base_url, "key", "model", "system", "user",
                idle_timeout=0.2, cancel_event=cancelled,
                activity_cb=mark_activity,
            )

    async def test_json_response_is_accepted_from_compatible_server(self):
        async def respond(writer):
            body = json.dumps({
                "choices": [{"message": {"content": "cleaned"}}]
            }).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + body
            )
            await writer.drain()

        self.responder = respond
        result = await provider.chat_openai_compat(
            self.base_url, "key", "model", "system", "user",
            idle_timeout=0.2,
        )
        self.assertEqual(result, "cleaned")

    async def test_streaming_rejection_falls_back_to_async_json(self):
        calls = 0

        async def respond(writer):
            nonlocal calls
            calls += 1
            if calls == 1:
                body = b'{"error":"stream is unsupported"}'
                status = b"HTTP/1.1 400 Bad Request\r\n"
            else:
                body = json.dumps({
                    "choices": [{"message": {"content": "fallback"}}]
                }).encode()
                status = b"HTTP/1.1 200 OK\r\n"
            writer.write(
                status
                + b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + body
            )
            await writer.drain()

        self.responder = respond
        result = await provider.chat_openai_compat(
            self.base_url, "key", "model", "system", "user",
            idle_timeout=0.2,
        )
        self.assertEqual(result, "fallback")
        self.assertEqual(calls, 2)

    async def test_malformed_stream_raises_a_safe_response_error(self):
        async def respond(writer):
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Connection: close\r\n\r\n"
                b"data: this is not JSON\n\n"
                b"data: [DONE]\n\n"
            )
            await writer.drain()

        self.responder = respond
        with self.assertRaises(provider.ProviderMalformedResponse):
            await provider.chat_openai_compat(
                self.base_url, "key", "model", "system", "user",
                idle_timeout=0.2,
            )

    async def test_empty_json_response_raises_empty_output_error(self):
        async def respond(writer):
            body = json.dumps({
                "choices": [{"message": {"content": ""}}]
            }).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + body
            )
            await writer.drain()

        self.responder = respond
        with self.assertRaises(provider.ProviderEmptyOutput):
            await provider.chat_openai_compat(
                self.base_url, "key", "model", "system", "user",
                idle_timeout=0.2,
            )

    async def test_sidecar_cleanup_uses_streamed_result(self):
        async def respond(writer):
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Connection: close\r\n\r\n"
            )
            await writer.drain()
            for piece in ("Original", " text", "."):
                await asyncio.sleep(0.01)
                writer.write(_sse(piece))
                await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()

        self.responder = respond
        sidecar = sidecar_main.Sidecar()
        messages = []

        async def capture(message):
            messages.append(message)

        sidecar.write = capture
        await sidecar._cleanup_ai(
            "cleanup-1",
            "Original text.",
            {
                "mode": "api",
                "api_type": "openai_compat",
                "base_url": self.base_url,
                "key": "key",
                "model": "model",
            },
            asyncio.Event(),
        )
        result = messages[-1]["result"]
        self.assertTrue(result["llm_applied"])
        self.assertEqual(result["markdown"], "Original text.")


if __name__ == "__main__":
    unittest.main()
