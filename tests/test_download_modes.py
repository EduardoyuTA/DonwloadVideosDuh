from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ["VIDEOFLOW_HOSTED"] = "1"

app_module = importlib.import_module("app")
manager_module = importlib.import_module("download_manager")


class DownloadModeValidationTests(unittest.TestCase):
    def test_online_mode_rejects_youtube_before_preview_extraction(self) -> None:
        with patch.object(app_module, "extract_video_preview") as extract_preview:
            response = app_module.app.test_client().post(
                "/api/preview",
                json={
                    "video_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
                    "format_choice": "mp4",
                    "quality_choice": "best",
                    "download_mode": "online",
                },
            )
            payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertIn("Modo Online", payload["error"])
        extract_preview.assert_not_called()

    def test_youtube_mode_requires_local_app(self) -> None:
        response = app_module.app.test_client().post(
            "/api/preview",
            json={
                "video_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
                "format_choice": "mp4",
                "quality_choice": "best",
                "download_mode": "youtube",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertIn("app local", payload["error"])

    def test_youtube_mode_accepts_youtube_when_running_locally(self) -> None:
        with patch.object(app_module, "HOSTED_MODE", False):
            error = app_module.validate_download_inputs(
                video_url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
                format_choice="mp4",
                quality_choice="best",
                download_mode="youtube",
            )

        self.assertIsNone(error)

    def test_youtube_mode_rejects_non_youtube_when_running_locally(self) -> None:
        with patch.object(app_module, "HOSTED_MODE", False):
            error = app_module.validate_download_inputs(
                video_url="https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
                format_choice="mp4",
                quality_choice="best",
                download_mode="youtube",
            )

        self.assertIn("apenas links do YouTube", str(error))


class DownloadModeHistoryTests(unittest.TestCase):
    def test_completed_youtube_job_keeps_download_mode_in_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            history = manager_module.HistoryStore(temp_path / "history.json")
            download_manager = manager_module.DownloadManager(
                history,
                reveal_on_complete=False,
            )
            output_file = temp_path / "video.mp4"
            output_file.write_bytes(b"video")
            download_manager.jobs["job123"] = {
                "id": "job123",
                "video_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
                "output_dir": str(temp_path),
                "format_choice": "mp4",
                "quality_choice": "best",
                "download_mode": "youtube",
                "add_bpm_intro": False,
                "mirror_video": False,
                "title": "Video",
                "uploader": "",
                "platform_label": "YouTube",
                "thumbnail_url": None,
                "duration_label": None,
                "selection_summary": "MP4",
                "status": "queued",
                "created_at": "2026-07-01T10:00:00",
            }

            with patch.object(
                manager_module,
                "download_video",
                return_value={
                    "file_path": output_file,
                    "title": "Video",
                    "selection_summary": "MP4",
                    "uploader": "",
                    "platform_label": "YouTube",
                    "thumbnail_url": None,
                    "duration_label": None,
                    "notice": None,
                },
            ):
                download_manager._run_job("job123")

            self.assertEqual(history.list_entries()[0]["download_mode"], "youtube")


if __name__ == "__main__":
    unittest.main()
