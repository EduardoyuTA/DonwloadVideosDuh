from __future__ import annotations

import unittest
from unittest.mock import patch

import downloader


class DownloaderErrorTests(unittest.TestCase):
    def test_youtube_compat_options_default_to_android_vr_client(self) -> None:
        options: dict[str, object] = {}

        with patch.dict("os.environ", {}, clear=True):
            downloader.apply_youtube_compat_options(options)

        self.assertEqual(
            options["extractor_args"],
            {"youtube": {"player_client": ["android_vr"]}},
        )

    def test_youtube_bot_challenge_gets_specific_preview_message(self) -> None:
        error = Exception("Sign in to confirm you're not a bot")

        message = downloader.build_yt_dlp_error_message(
            "analisar",
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            error,
        )

        self.assertIn("YouTube", message)
        self.assertIn("servidor publicado", message)
        self.assertNotIn("URL esta correta", message)


if __name__ == "__main__":
    unittest.main()
