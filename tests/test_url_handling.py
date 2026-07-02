from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch


os.environ["VIDEOFLOW_HOSTED"] = "1"

app_module = importlib.import_module("app")


class UrlHandlingTests(unittest.TestCase):
    def test_normalize_video_url_adds_https_to_pasted_youtube_domain(self) -> None:
        normalized = app_module.normalize_video_url(
            "www.youtube.com/watch?v=jNQXAC9IVRw"
        )

        self.assertEqual(normalized, "https://www.youtube.com/watch?v=jNQXAC9IVRw")

    def test_normalize_video_url_extracts_url_from_share_text(self) -> None:
        normalized = app_module.normalize_video_url(
            "Olha esse video: https://youtu.be/jNQXAC9IVRw?si=abc."
        )

        self.assertEqual(normalized, "https://youtu.be/jNQXAC9IVRw?si=abc")

    def test_preview_api_uses_normalized_url(self) -> None:
        expected_preview = {
            "title": "Video",
            "selection_summary": "MP4 em Maxima disponivel",
        }

        with patch.object(
            app_module,
            "extract_video_preview",
            return_value=expected_preview,
        ) as extract_preview:
            response = app_module.app.test_client().post(
                "/api/preview",
                json={
                    "video_url": "samplelib.com/lib/preview/mp4/sample-5s.mp4",
                    "format_choice": "mp4",
                    "quality_choice": "best",
                },
            )

        self.assertEqual(response.status_code, 200)
        extract_preview.assert_called_once_with(
            "https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
            "mp4",
            "best",
            False,
            False,
        )


if __name__ == "__main__":
    unittest.main()
