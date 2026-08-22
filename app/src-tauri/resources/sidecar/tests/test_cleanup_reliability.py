import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


SIDECAR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIDECAR_DIR))

import cleanup  # noqa: E402
import main as sidecar_main  # noqa: E402
import provider  # noqa: E402


class CleanupChunkingTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_chunk_cleanup_preserves_order_and_reports_progress(self):
        original_target = cleanup._CHUNK_TARGET_CHARS
        cleanup._CHUNK_TARGET_CHARS = 12
        seen_chunks = []
        progress = []

        async def clean_chunk(chunk, *_args, **_kwargs):
            seen_chunks.append(chunk)
            return f"clean:{chunk}"

        text = "first block\n\nsecond block\n\nthird block"
        try:
            with patch.object(cleanup, "_clean_one_chunk", side_effect=clean_chunk):
                result = await cleanup.llm_clean(
                    text,
                    {"mode": "api", "model": "chosen"},
                    progress_cb=lambda done, total: progress.append((done, total)),
                )
        finally:
            cleanup._CHUNK_TARGET_CHARS = original_target

        self.assertEqual(seen_chunks, ["first block", "second block", "third block"])
        self.assertEqual(
            result,
            "clean:first block\n\nclean:second block\n\nclean:third block",
        )
        self.assertEqual(progress, [(0, 3), (1, 3), (2, 3), (3, 3)])

    async def test_empty_chunk_output_is_explicit_failure(self):
        with patch.object(cleanup, "_clean_one_chunk", new=AsyncMock(return_value="  ")):
            with self.assertRaises(provider.ProviderEmptyOutput):
                await cleanup.llm_clean(
                    "source text",
                    {"mode": "api", "model": "chosen"},
                )


class SidecarCleanupFailureTests(unittest.IsolatedAsyncioTestCase):
    async def _run_cleanup(self, failure):
        sidecar = sidecar_main.Sidecar()
        messages = []

        async def capture(message):
            messages.append(message)

        sidecar.write = capture
        with patch.object(cleanup, "llm_clean", new=AsyncMock(side_effect=failure)):
            await sidecar._cleanup_ai(
                "cleanup-test",
                "Original Markdown",
                {"key": "secret-key"},
                asyncio.Event(),
            )
        return messages[-1]["result"]

    async def test_inactivity_keeps_original_with_distinct_notice(self):
        result = await self._run_cleanup(
            provider.ProviderIdleTimeout("The provider sent no response data for 1 seconds.")
        )
        self.assertEqual(result["markdown"], "Original Markdown")
        self.assertFalse(result["llm_applied"])
        self.assertIn("stopped because", result["llm_notice"])
        self.assertIn("no response data", result["llm_notice"])

    async def test_empty_output_keeps_original_with_distinct_notice(self):
        result = await self._run_cleanup(provider.ProviderEmptyOutput("no text"))
        self.assertEqual(result["markdown"], "Original Markdown")
        self.assertEqual(
            result["llm_notice"],
            "AI cleanup returned no text — kept the original text.",
        )

    async def test_malformed_response_keeps_original_with_distinct_notice(self):
        result = await self._run_cleanup(provider.ProviderMalformedResponse("bad response"))
        self.assertEqual(result["markdown"], "Original Markdown")
        self.assertEqual(
            result["llm_notice"],
            "AI cleanup received an invalid provider response — kept the original text.",
        )

    async def test_provider_failure_keeps_original_and_redacts_key(self):
        result = await self._run_cleanup(RuntimeError("request failed for secret-key"))
        self.assertEqual(result["markdown"], "Original Markdown")
        self.assertIn("provider failed", result["llm_notice"])
        self.assertNotIn("secret-key", result["llm_notice"])
        self.assertIn("[key]", result["llm_notice"])

    async def test_cancellation_returns_cancelled_error_without_result(self):
        sidecar = sidecar_main.Sidecar()
        messages = []
        cancel_event = asyncio.Event()
        cancel_event.set()

        async def capture(message):
            messages.append(message)

        sidecar.write = capture
        await sidecar._cleanup_ai(
            "cleanup-cancel",
            "Original Markdown",
            {},
            cancel_event,
        )
        self.assertFalse(messages[-1]["ok"])
        self.assertEqual(messages[-1]["error"]["code"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
