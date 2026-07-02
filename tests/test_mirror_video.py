from __future__ import annotations

import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import downloader


os.environ["VIDEOFLOW_HOSTED"] = "1"

app_module = importlib.import_module("app")


class MirrorVideoValidationTests(unittest.TestCase):
    def test_hosted_mirror_requires_lightweight_quality(self) -> None:
        error = app_module.validate_download_inputs(
            video_url="https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
            format_choice="mp4",
            quality_choice="best",
            download_mode="online",
            mirror_video=True,
        )

        self.assertIn("720p ou 480p", str(error))

    def test_hosted_mirror_allows_720p(self) -> None:
        error = app_module.validate_download_inputs(
            video_url="https://samplelib.com/lib/preview/mp4/sample-5s.mp4",
            format_choice="mp4",
            quality_choice="720",
            download_mode="online",
            mirror_video=True,
        )

        self.assertIsNone(error)


class MirrorVideoCommandTests(unittest.TestCase):
    def test_hardware_encoder_can_be_disabled_for_hosted_servers(self) -> None:
        with (
            patch.dict(os.environ, {"VIDEOFLOW_DISABLE_HARDWARE_ENCODERS": "1"}),
            patch.object(downloader, "list_available_ffmpeg_encoders", return_value={"h264_nvenc"}),
        ):
            commands = downloader.build_mirror_video_commands(
                Path("input.mp4"),
                Path("output.mp4"),
                "mp4",
                "720",
            )

        encoder_labels = [label for _, label in commands]
        self.assertNotIn("h264_nvenc", encoder_labels)

    def test_low_resource_mirror_options_are_added_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VIDEOFLOW_DISABLE_HARDWARE_ENCODERS": "1",
                "VIDEOFLOW_MIRROR_THREADS": "1",
                "VIDEOFLOW_MIRROR_PRESET": "ultrafast",
            },
        ):
            commands = downloader.build_mirror_video_commands(
                Path("input.mp4"),
                Path("output.mp4"),
                "mp4",
                "720",
            )

        software_command = commands[0][0]
        self.assertIn("ultrafast", software_command)
        self.assertIn("-threads", software_command)
        self.assertIn("1", software_command)


if __name__ == "__main__":
    unittest.main()
