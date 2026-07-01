from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from shutil import which
from time import time
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for

from download_manager import DownloadManager, HistoryStore
from downloader import (
    DownloadError,
    FORMAT_OPTIONS,
    QUALITY_OPTIONS_BY_FORMAT,
    download_video,
    extract_video_preview,
    get_quality_options_for_format,
)

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
INSTALL_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
LOCAL_APPDATA_DIR = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
USER_DOWNLOADS_DIR = Path.home() / "Downloads"


def env_flag(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


HOSTED_MODE = (
    env_flag("VIDEOFLOW_HOSTED")
    or bool(os.getenv("RENDER"))
    or bool(os.getenv("RAILWAY_ENVIRONMENT"))
    or bool(os.getenv("FLY_APP_NAME"))
    or bool(os.getenv("K_SERVICE"))
)

if HOSTED_MODE:
    HOSTED_BASE_DIR = Path(
        os.getenv("VIDEOFLOW_BASE_DIR") or (Path(tempfile.gettempdir()) / "videoflow")
    )
    DATA_DIR = Path(os.getenv("VIDEOFLOW_DATA_DIR") or (HOSTED_BASE_DIR / "data"))
    DEFAULT_DOWNLOAD_DIR = Path(
        os.getenv("VIDEOFLOW_DOWNLOAD_DIR") or (HOSTED_BASE_DIR / "downloads")
    )
    RELATIVE_OUTPUT_BASE_DIR = DEFAULT_DOWNLOAD_DIR
elif getattr(sys, "frozen", False):
    DATA_DIR = LOCAL_APPDATA_DIR / "VideoFlow" / "data"
    DEFAULT_DOWNLOAD_DIR = USER_DOWNLOADS_DIR / "VideoFlow"
    RELATIVE_OUTPUT_BASE_DIR = USER_DOWNLOADS_DIR
else:
    DATA_DIR = INSTALL_DIR / "data"
    DEFAULT_DOWNLOAD_DIR = INSTALL_DIR / "downloads"
    RELATIVE_OUTPUT_BASE_DIR = INSTALL_DIR

SUPPORTED_FORMATS = {item["value"] for item in FORMAT_OPTIONS}
SUPPORTED_QUALITIES_BY_FORMAT = {
    format_choice: {item["value"] for item in quality_options}
    for format_choice, quality_options in QUALITY_OPTIONS_BY_FORMAT.items()
}

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
history_store = HistoryStore(DATA_DIR / "download_history.json")
download_manager = DownloadManager(history_store, reveal_on_complete=not HOSTED_MODE)


def is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False

    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def resolve_output_dir(raw_path: str) -> Path:
    if HOSTED_MODE:
        return DEFAULT_DOWNLOAD_DIR

    if not raw_path.strip():
        return DEFAULT_DOWNLOAD_DIR

    output_dir = Path(raw_path).expanduser()
    if not output_dir.is_absolute():
        output_dir = (RELATIVE_OUTPUT_BASE_DIR / output_dir).resolve()

    return output_dir


def get_request_payload() -> dict[str, object]:
    if request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
        return {}

    return request.form.to_dict()


def normalize_choice(payload: dict[str, object], key: str, default: str) -> str:
    return str(payload.get(key) or default).strip().lower()


def normalize_flag(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "sim"}


def validate_download_inputs(
    *,
    video_url: str,
    format_choice: str,
    quality_choice: str,
    add_bpm_intro: bool = False,
    mirror_video: bool = False,
) -> str | None:
    if not is_valid_url(video_url):
        return "Informe um link valido com http:// ou https://."

    if format_choice not in SUPPORTED_FORMATS:
        return "Escolha um formato suportado."

    supported_qualities = SUPPORTED_QUALITIES_BY_FORMAT.get(format_choice, set())
    if quality_choice not in supported_qualities:
        return "Escolha uma qualidade suportada."

    if add_bpm_intro and format_choice != "mp3":
        return "A contagem inicial BPM 75 so esta disponivel para musicas em MP3."

    if mirror_video and format_choice == "mp3":
        return "O espelhamento so esta disponivel para downloads de video."

    if mirror_video and which("ffmpeg") is None:
        return "Para espelhar videos, instale o FFmpeg e tente novamente."

    return None


def build_page_context(**overrides: object) -> dict[str, object]:
    static_files = [
        RESOURCE_DIR / "static" / "styles.css",
        RESOURCE_DIR / "static" / "app.js",
        RESOURCE_DIR / "static" / "videoflow-mark.svg",
    ]
    static_version = max(
        (int(path.stat().st_mtime) for path in static_files if path.exists()),
        default=int(time()),
    )

    context: dict[str, object] = {
        "default_output_dir": str(DEFAULT_DOWNLOAD_DIR),
        "video_url": "",
        "output_dir": str(DEFAULT_DOWNLOAD_DIR),
        "format_choice": "mp4",
        "quality_choice": "best",
        "format_options": FORMAT_OPTIONS,
        "quality_options": get_quality_options_for_format("mp4"),
        "quality_options_by_format": QUALITY_OPTIONS_BY_FORMAT,
        "ffmpeg_available": which("ffmpeg") is not None,
        "add_bpm_intro": False,
        "mirror_video": False,
        "hosted_mode": HOSTED_MODE,
        "static_version": static_version,
        "success": None,
        "notice": None,
        "error": None,
        "details": None,
        "downloaded_file": None,
    }
    context.update(overrides)

    format_choice = str(context.get("format_choice") or "mp4").strip().lower()
    quality_options = get_quality_options_for_format(format_choice)
    supported_qualities = {item["value"] for item in quality_options}
    if str(context.get("quality_choice") or "") not in supported_qualities:
        context["quality_choice"] = quality_options[0]["value"]

    context["quality_options"] = quality_options
    return context


def add_download_urls(items: list[dict[str, object]]) -> list[dict[str, object]]:
    enriched_items: list[dict[str, object]] = []
    for item in items:
        next_item = dict(item)
        if (
            str(next_item.get("status") or "completed") == "completed"
            and next_item.get("id")
            and next_item.get("file_path")
        ):
            next_item["download_url"] = url_for(
                "api_download_file",
                job_id=str(next_item["id"]),
            )
        enriched_items.append(next_item)

    return enriched_items


def find_download_file_path(job_id: str) -> Path | None:
    job = download_manager.get_job(job_id)
    if job is not None and str(job.get("status")) == "completed":
        raw_file_path = str(job.get("file_path") or "")
        return Path(raw_file_path) if raw_file_path else None

    for entry in history_store.list_entries():
        if str(entry.get("id") or "") == job_id:
            raw_file_path = str(entry.get("file_path") or "")
            return Path(raw_file_path) if raw_file_path else None

    return None


@app.get("/")
def index() -> str:
    return render_template("index.html", **build_page_context())


@app.post("/api/preview")
def api_preview() -> tuple[object, int] | object:
    payload = get_request_payload()
    video_url = str(payload.get("video_url") or "").strip()
    format_choice = normalize_choice(payload, "format_choice", "mp4")
    quality_choice = normalize_choice(payload, "quality_choice", "best")
    add_bpm_intro = normalize_flag(payload, "add_bpm_intro")
    mirror_video = normalize_flag(payload, "mirror_video")

    error_message = validate_download_inputs(
        video_url=video_url,
        format_choice=format_choice,
        quality_choice=quality_choice,
        add_bpm_intro=add_bpm_intro,
        mirror_video=mirror_video,
    )
    if error_message:
        return jsonify({"error": error_message}), 400

    try:
        preview = extract_video_preview(
            video_url,
            format_choice,
            quality_choice,
            add_bpm_intro,
            mirror_video,
        )
    except DownloadError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"preview": preview})


@app.post("/api/downloads")
def api_create_download() -> tuple[object, int] | object:
    payload = get_request_payload()
    video_url = str(payload.get("video_url") or "").strip()
    format_choice = normalize_choice(payload, "format_choice", "mp4")
    quality_choice = normalize_choice(payload, "quality_choice", "best")
    add_bpm_intro = normalize_flag(payload, "add_bpm_intro")
    mirror_video = normalize_flag(payload, "mirror_video")
    output_dir_input = str(payload.get("output_dir") or "").strip()
    preview = payload.get("preview")
    if not isinstance(preview, dict):
        preview = None

    error_message = validate_download_inputs(
        video_url=video_url,
        format_choice=format_choice,
        quality_choice=quality_choice,
        add_bpm_intro=add_bpm_intro,
        mirror_video=mirror_video,
    )
    if error_message:
        return jsonify({"error": error_message}), 400

    resolved_output_dir = resolve_output_dir(output_dir_input)
    job = download_manager.create_job(
        video_url=video_url,
        output_dir=resolved_output_dir,
        format_choice=format_choice,
        quality_choice=quality_choice,
        add_bpm_intro=add_bpm_intro,
        mirror_video=mirror_video,
        preview=preview,
    )
    return jsonify({"job": job}), 202


@app.get("/api/downloads/<job_id>/file")
def api_download_file(job_id: str) -> object:
    raw_file_path = find_download_file_path(job_id)
    if raw_file_path is None:
        abort(404)

    try:
        file_path = raw_file_path.resolve(strict=True)
    except OSError:
        abort(404)

    if not file_path.is_file():
        abort(404)

    response = send_file(
        file_path,
        as_attachment=True,
        download_name=file_path.name,
        mimetype="application/octet-stream",
        conditional=True,
        max_age=0,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/jobs")
def api_jobs() -> object:
    return jsonify({"jobs": add_download_urls(download_manager.list_jobs())})


@app.get("/api/history")
def api_history() -> object:
    return jsonify({"history": add_download_urls(history_store.list_entries())})


@app.post("/download")
def download() -> tuple[str, int] | str:
    payload = get_request_payload()
    video_url = str(payload.get("video_url") or "").strip()
    output_dir_input = str(payload.get("output_dir") or "").strip()
    format_choice = normalize_choice(payload, "format_choice", "mp4")
    quality_choice = normalize_choice(payload, "quality_choice", "best")
    add_bpm_intro = normalize_flag(payload, "add_bpm_intro")
    mirror_video = normalize_flag(payload, "mirror_video")

    context = build_page_context(
        video_url=video_url,
        output_dir=output_dir_input or str(DEFAULT_DOWNLOAD_DIR),
        format_choice=format_choice,
        quality_choice=quality_choice,
        add_bpm_intro=add_bpm_intro,
        mirror_video=mirror_video,
    )

    error_message = validate_download_inputs(
        video_url=video_url,
        format_choice=format_choice,
        quality_choice=quality_choice,
        add_bpm_intro=add_bpm_intro,
        mirror_video=mirror_video,
    )
    if error_message:
        context["error"] = error_message
        return render_template("index.html", **context), 400

    try:
        resolved_output_dir = resolve_output_dir(output_dir_input)
        result = download_video(
            video_url,
            resolved_output_dir,
            format_choice,
            quality_choice,
            add_bpm_intro=add_bpm_intro,
            mirror_video=mirror_video,
        )
    except DownloadError as exc:
        context["error"] = str(exc)
        return render_template("index.html", **context), 400
    except Exception as exc:  # pragma: no cover - fallback de seguranca
        context["error"] = "Nao foi possivel concluir o download agora."
        context["details"] = str(exc)
        return render_template("index.html", **context), 500

    context["success"] = (
        f'Download concluido: "{result["title"]}" em {result["selection_summary"]}.'
    )
    context["notice"] = result["notice"]
    context["downloaded_file"] = str(result["file_path"])
    context["output_dir"] = str(resolved_output_dir)
    return render_template("index.html", **context)


if __name__ == "__main__":
    port = int(os.getenv("PORT") or "5000")
    host = os.getenv("HOST") or ("0.0.0.0" if HOSTED_MODE else "127.0.0.1")
    debug = env_flag("FLASK_DEBUG") or (not HOSTED_MODE and env_flag("VIDEOFLOW_DEBUG"))
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)
