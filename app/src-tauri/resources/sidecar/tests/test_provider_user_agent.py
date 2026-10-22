import asyncio
import json
import os
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


SIDECAR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIDECAR_DIR))

import provider  # noqa: E402


class UserAgentTests(unittest.TestCase):
    def test_user_agent_carries_app_version(self):
        with mock.patch.dict(os.environ, {"MDFLUX_APP_VERSION": "9.9.9"}):
            self.assertEqual(provider._user_agent(), "MDFlux/9.9.9")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(provider._user_agent(), "MDFlux/dev")

    def test_openai_compat_probe_sends_mdflux_user_agent(self):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["ua"] = req.get_header("User-agent")
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            provider.check_openai_compat("https://api.groq.com/openai/v1", "k")
        self.assertTrue(seen["ua"].startswith("MDFlux/"), seen)

    def test_anthropic_probe_sends_mdflux_user_agent(self):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["ua"] = req.get_header("User-agent")
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            provider.check_anthropic("sk-ant-test")
        self.assertTrue(seen["ua"].startswith("MDFlux/"), seen)


class ChatUserAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_request_sends_mdflux_user_agent(self):
        seen = {}

        async def handle(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for line in head.decode(errors="replace").split("\r\n"):
                low = line.lower()
                if low.startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
                if low.startswith("user-agent:"):
                    seen["ua"] = line.split(":", 1)[1].strip()
            if length:
                await reader.readexactly(length)
            body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
            )
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            text = await provider.chat_openai_compat(
                f"http://127.0.0.1:{port}/v1", "", "m", "sys", "user", idle_timeout=5,
            )
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(text, "ok")
        self.assertTrue(seen.get("ua", "").startswith("MDFlux/"), seen)


if __name__ == "__main__":
    unittest.main()
