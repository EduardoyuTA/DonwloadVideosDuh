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


class HostedModeTests(unittest.TestCase):
    def setUp(self) -> None:
        app_module.download_manager.jobs.clear()

    def test_hosted_mode_ignores_local_output_directory(self) -> None:
        resolved = app_module.resolve_output_dir("C:/Users/example/Desktop")

        self.assertEqual(resolved, app_module.DEFAULT_DOWNLOAD_DIR)

    def test_database_url_selects_postgres_history_store(self) -> None:
        database_url = "postgresql://user:pass@example.test/db?sslmode=require"

        with (
            patch.dict(os.environ, {"DATABASE_URL": database_url}),
            patch.object(app_module, "PostgresHistoryStore") as postgres_store,
        ):
            selected_store = app_module.create_history_store()

        postgres_store.assert_called_once_with(database_url)
        self.assertEqual(selected_store, postgres_store.return_value)

    def test_jobs_api_exposes_browser_download_url_for_completed_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "video.mp4"
            output_file.write_bytes(b"video")
            app_module.download_manager.jobs["job123"] = {
                "id": "job123",
                "status": "completed",
                "file_path": str(output_file),
                "created_at": "2026-07-01T10:00:00",
            }

            response = app_module.app.test_client().get("/api/jobs")
            payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payload["jobs"][0]["download_url"],
            "/api/downloads/job123/file",
        )

    def test_download_file_endpoint_sends_completed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "video.mp4"
            output_file.write_bytes(b"video")
            app_module.download_manager.jobs["job123"] = {
                "id": "job123",
                "status": "completed",
                "file_path": str(output_file),
                "created_at": "2026-07-01T10:00:00",
            }

            response = app_module.app.test_client().get("/api/downloads/job123/file")
            try:
                response_data = response.data
                content_disposition = response.headers["Content-Disposition"]
                content_type = response.headers["Content-Type"]
                nosniff = response.headers.get("X-Content-Type-Options")
            finally:
                response.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_data, b"video")
        self.assertIn("attachment", content_disposition)
        self.assertIn("video.mp4", content_disposition)
        self.assertEqual(content_type, "application/octet-stream")
        self.assertEqual(nosniff, "nosniff")

    def test_download_file_endpoint_forces_audio_attachment_for_safari(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "musica.mp3"
            output_file.write_bytes(b"audio")
            app_module.download_manager.jobs["job123"] = {
                "id": "job123",
                "status": "completed",
                "file_path": str(output_file),
                "created_at": "2026-07-01T10:00:00",
            }

            response = app_module.app.test_client().get("/api/downloads/job123/file")
            try:
                response_data = response.data
                content_disposition = response.headers["Content-Disposition"]
                content_type = response.headers["Content-Type"]
            finally:
                response.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_data, b"audio")
        self.assertIn("attachment", content_disposition)
        self.assertIn("musica.mp3", content_disposition)
        self.assertEqual(content_type, "application/octet-stream")

    def test_download_file_endpoint_can_use_history_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "video.mp4"
            output_file.write_bytes(b"video")
            previous_history = app_module.history_store
            app_module.history_store = manager_module.HistoryStore(
                Path(temp_dir) / "history.json"
            )
            app_module.history_store.add_entry(
                {
                    "id": "job123",
                    "file_path": str(output_file),
                    "completed_at": "2026-07-01T10:00:00",
                }
            )

            try:
                response = app_module.app.test_client().get(
                    "/api/downloads/job123/file"
                )
                response_data = response.data
                response.close()
            finally:
                app_module.history_store = previous_history

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response_data, b"video")


class HostedDownloadManagerTests(unittest.TestCase):
    def test_reveal_folder_is_skipped_when_disabled(self) -> None:
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
                "video_url": "https://example.com/video",
                "output_dir": str(temp_path),
                "format_choice": "mp4",
                "quality_choice": "best",
                "add_bpm_intro": False,
                "mirror_video": False,
                "title": "Video",
                "uploader": "",
                "platform_label": "Link",
                "thumbnail_url": None,
                "duration_label": None,
                "selection_summary": "MP4",
                "status": "queued",
                "created_at": "2026-07-01T10:00:00",
            }

            with (
                patch.object(
                    manager_module,
                    "download_video",
                    return_value={
                        "file_path": output_file,
                        "title": "Video",
                        "selection_summary": "MP4",
                        "uploader": "",
                        "platform_label": "Link",
                        "thumbnail_url": None,
                        "duration_label": None,
                        "notice": None,
                    },
                ),
                patch.object(manager_module, "reveal_download_in_explorer") as reveal,
            ):
                download_manager._run_job("job123")

        reveal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
