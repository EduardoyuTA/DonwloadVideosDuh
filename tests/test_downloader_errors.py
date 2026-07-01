from __future__ import annotations

import unittest

import downloader


class DownloaderErrorTests(unittest.TestCase):
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
