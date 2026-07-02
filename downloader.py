from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from time import time
from pathlib import Path
from shutil import which
from typing import Callable
from urllib.parse import urlparse

import yt_dlp

logger = logging.getLogger(__name__)

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
AUDIO_ASSETS_DIR = RESOURCE_DIR / "assets" / "audio"
BPM75_INTRO_PATH = AUDIO_ASSETS_DIR / "bpm75_intro.wav"
TARGET_AUDIO_SAMPLE_RATE = "44100"
TARGET_AUDIO_CHANNELS = "2"
INTRO_NORMALIZE_GAIN = 1.08
DEFAULT_YOUTUBE_PLAYER_CLIENTS = ("android_vr",)
VIDEO_MIRROR_CRF_BY_QUALITY = {
    "best": "18",
    "2160": "18",
    "1440": "19",
    "1080": "20",
    "720": "21",
    "480": "23",
}
VIDEO_MIRROR_NVENC_CQ_BY_QUALITY = {
    "best": "18",
    "2160": "18",
    "1440": "19",
    "1080": "21",
    "720": "23",
    "480": "25",
}
VIDEO_MIRROR_PROGRESS_RANGE = (92.0, 99.0)
STALE_MIRROR_TEMP_MAX_AGE_SECONDS = 60 * 60
DEFAULT_MIRROR_SOFTWARE_PRESET = "veryfast"

FORMAT_OPTIONS = (
    {
        "value": "mp4",
        "label": "MP4",
        "description": "Alta compatibilidade para video e boa qualidade.",
    },
    {
        "value": "webm",
        "label": "WEBM",
        "description": "Container leve, comum em streams de alta resolucao.",
    },
    {
        "value": "mkv",
        "label": "MKV",
        "description": "Melhor opcao para preservar qualidade maxima.",
    },
    {
        "value": "mp3",
        "label": "MP3",
        "description": "Baixa apenas a musica ou audio do link, com presets dedicados.",
    },
)

VIDEO_QUALITY_OPTIONS = (
    {
        "value": "best",
        "label": "Maxima disponivel",
        "description": "Baixa a melhor resolucao liberada pela plataforma.",
    },
    {
        "value": "2160",
        "label": "4K / 2160p",
        "description": "Limita o video em ate 2160p quando houver essa opcao.",
    },
    {
        "value": "1440",
        "label": "1440p",
        "description": "Equilibrio forte entre nitidez e tamanho do arquivo.",
    },
    {
        "value": "1080",
        "label": "Full HD / 1080p",
        "description": "Padrao de alta qualidade para a maioria dos videos.",
    },
    {
        "value": "720",
        "label": "HD / 720p",
        "description": "Opcao mais leve sem perder boa definicao.",
    },
    {
        "value": "480",
        "label": "SD / 480p",
        "description": "Usa menos espaco quando a resolucao nao importa tanto.",
    },
)

MUSIC_QUALITY_OPTIONS = (
    {
        "value": "best",
        "label": "VBR alta",
        "description": "Converte para MP3 com VBR de alta qualidade para equilibrar fidelidade e tamanho.",
    },
    {
        "value": "320",
        "label": "320 kbps",
        "description": "Usa bitrate fixo de 320 kbps para quem quer o preset mais alto em MP3.",
    },
    {
        "value": "256",
        "label": "256 kbps",
        "description": "Qualidade alta para musica com arquivo um pouco mais leve que 320 kbps.",
    },
    {
        "value": "192",
        "label": "192 kbps",
        "description": "Boa qualidade geral para ouvir musica e podcasts com tamanho moderado.",
    },
    {
        "value": "128",
        "label": "128 kbps",
        "description": "Opcao mais leve para fala ou quando o tamanho do arquivo importa mais.",
    },
)

QUALITY_OPTIONS_BY_FORMAT = {
    "mp4": VIDEO_QUALITY_OPTIONS,
    "webm": VIDEO_QUALITY_OPTIONS,
    "mkv": VIDEO_QUALITY_OPTIONS,
    "mp3": MUSIC_QUALITY_OPTIONS,
}

FORMAT_LABELS = {item["value"]: item["label"] for item in FORMAT_OPTIONS}
VIDEO_QUALITY_LABELS = {
    item["value"]: item["label"] for item in VIDEO_QUALITY_OPTIONS
}
MUSIC_QUALITY_LABELS = {
    item["value"]: item["label"] for item in MUSIC_QUALITY_OPTIONS
}
QUALITY_LIMITS = {
    "best": None,
    "2160": 2160,
    "1440": 1440,
    "1080": 1080,
    "720": 720,
    "480": 480,
}
MUSIC_BITRATE_ESTIMATES = {
    "best": 245,
    "320": 320,
    "256": 256,
    "192": 192,
    "128": 128,
}

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "twitter": "Twitter",
    "x": "X",
    "facebook": "Facebook",
    "vimeo": "Vimeo",
    "twitch": "Twitch",
    "reddit": "Reddit",
}


class DownloadError(Exception):
    """Erro amigavel para exibir na interface."""


def is_youtube_url(video_url: str) -> bool:
    try:
        hostname = (urlparse(str(video_url or "")).hostname or "").lower()
    except ValueError:
        return False

    return hostname == "youtu.be" or hostname.endswith(".youtube.com")


def summarize_url_for_log(video_url: str) -> str:
    try:
        parsed = urlparse(str(video_url or ""))
    except ValueError:
        return "url-invalida"

    host = parsed.hostname or "sem-host"
    return f"{host}{parsed.path or ''}"


def build_yt_dlp_error_message(action: str, video_url: str, exc: Exception) -> str:
    detail = str(exc or "").strip()
    normalized_detail = detail.lower()
    youtube_related = is_youtube_url(video_url) or "youtube" in normalized_detail

    if youtube_related:
        blocked_markers = (
            "not a bot",
            "sign in to confirm",
            "captcha",
            "too many requests",
            "http error 429",
            "http error 403",
            "forbidden",
            "po token",
        )
        if any(marker in normalized_detail for marker in blocked_markers):
            return (
                f"Nao foi possivel {action} esse link do YouTube no servidor "
                "publicado. O YouTube pediu uma verificacao ou recusou a leitura "
                "automatica a partir deste servidor. O link pode estar correto; "
                "tente novamente mais tarde ou use o app local para links do YouTube."
            )

        return (
            f"Nao foi possivel {action} esse link do YouTube no servidor publicado. "
            "O link pode estar correto, mas o YouTube nao liberou os metadados para "
            "este servidor agora. Tente novamente mais tarde ou use o app local."
        )

    if action == "analisar":
        return (
            "Nao foi possivel analisar esse link. Verifique se a plataforma permite "
            "leitura dos metadados."
        )

    return (
        "Nao foi possivel baixar esse link. Verifique se a plataforma e o conteudo "
        "permitem o download."
    )


def log_yt_dlp_failure(action: str, video_url: str, exc: Exception) -> None:
    logger.warning(
        "yt-dlp falhou ao %s %s: %s",
        action,
        summarize_url_for_log(video_url),
        exc,
    )


def env_flag(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def get_mirror_software_preset() -> str:
    preset = str(
        os.getenv("VIDEOFLOW_MIRROR_PRESET") or DEFAULT_MIRROR_SOFTWARE_PRESET
    ).strip()
    return preset or DEFAULT_MIRROR_SOFTWARE_PRESET


def get_mirror_thread_args() -> list[str]:
    raw_threads = str(os.getenv("VIDEOFLOW_MIRROR_THREADS") or "").strip()
    if not raw_threads:
        return []

    try:
        thread_count = int(raw_threads)
    except ValueError:
        return []

    if thread_count <= 0:
        return []

    return ["-threads", str(thread_count)]


def get_youtube_player_clients() -> list[str]:
    raw_clients = str(os.getenv("VIDEOFLOW_YOUTUBE_PLAYER_CLIENTS") or "").strip()
    if not raw_clients:
        return list(DEFAULT_YOUTUBE_PLAYER_CLIENTS)

    if raw_clients.lower() in {"off", "none", "disabled"}:
        return []

    clients = [item.strip() for item in raw_clients.split(",") if item.strip()]
    return clients or list(DEFAULT_YOUTUBE_PLAYER_CLIENTS)


def apply_youtube_compat_options(options: dict[str, object]) -> None:
    player_clients = get_youtube_player_clients()
    if not player_clients:
        return

    extractor_args = options.get("extractor_args")
    if not isinstance(extractor_args, dict):
        extractor_args = {}
        options["extractor_args"] = extractor_args

    youtube_args = extractor_args.get("youtube")
    if not isinstance(youtube_args, dict):
        youtube_args = {}
        extractor_args["youtube"] = youtube_args

    # Ajuda o yt-dlp em servidores hospedados, onde alguns clientes do YouTube
    # podem receber desafios ou respostas sem formatos baixaveis.
    youtube_args["player_client"] = player_clients


def is_music_format(format_choice: str) -> bool:
    return format_choice == "mp3"


def is_video_format(format_choice: str) -> bool:
    return not is_music_format(format_choice)


def get_quality_options_for_format(format_choice: str) -> tuple[dict[str, str], ...]:
    return QUALITY_OPTIONS_BY_FORMAT.get(format_choice, VIDEO_QUALITY_OPTIONS)


def get_quality_labels_for_format(format_choice: str) -> dict[str, str]:
    if is_music_format(format_choice):
        return MUSIC_QUALITY_LABELS
    return VIDEO_QUALITY_LABELS


def get_quality_label(format_choice: str, quality_choice: str) -> str:
    labels = get_quality_labels_for_format(format_choice)
    return labels.get(quality_choice, quality_choice)


def merge_notices(*messages: str | None) -> str | None:
    parts = [str(message).strip() for message in messages if str(message or "").strip()]
    if not parts:
        return None
    return " ".join(parts)


def format_duration(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None

    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_bytes(num_bytes: int | float | None) -> str | None:
    if num_bytes is None:
        return None

    value = float(num_bytes)
    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    decimals = 0 if unit_index == 0 else 1
    return f"{value:.{decimals}f} {units[unit_index]}"


def format_speed(speed_bytes: int | float | None) -> str:
    label = format_bytes(speed_bytes)
    if label is None:
        return "--"
    return f"{label}/s"


def parse_ffmpeg_timestamp(value: str) -> float | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    parts = raw_value.split(":")
    if len(parts) != 3:
        return None

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None

    return hours * 3600 + minutes * 60 + seconds


def parse_ffmpeg_speed_multiplier(value: str) -> float | None:
    raw_value = str(value or "").strip().lower()
    if not raw_value.endswith("x"):
        return None

    try:
        return float(raw_value[:-1])
    except ValueError:
        return None


def build_quality_filter(quality_choice: str) -> str:
    limit = QUALITY_LIMITS[quality_choice]
    if limit is None:
        return ""
    return f"[height<={limit}]"


def build_video_selector(
    format_choice: str, quality_choice: str, ffmpeg_available: bool
) -> tuple[dict[str, object], str | None]:
    quality_filter = build_quality_filter(quality_choice)

    if format_choice == "mkv":
        if not ffmpeg_available:
            raise DownloadError(
                "Para exportar em MKV com alta qualidade, instale o FFmpeg."
            )

        return (
            {
                "format": f"bestvideo{quality_filter}+bestaudio/best{quality_filter}",
                "merge_output_format": "mkv",
            },
            None,
        )

    if format_choice == "webm":
        if ffmpeg_available:
            return (
                {
                    "format": (
                        f"bestvideo{quality_filter}[ext=webm]+bestaudio[ext=webm]/"
                        f"bestvideo{quality_filter}[ext=webm]+bestaudio/"
                        f"best{quality_filter}[ext=webm]/best{quality_filter}"
                    ),
                    "merge_output_format": "webm",
                },
                None,
            )

        return (
            {"format": f"best{quality_filter}[ext=webm]/best{quality_filter}"},
            (
                "FFmpeg nao foi detectado. O app baixou a melhor faixa unica "
                "disponivel, o que pode limitar a resolucao final."
            ),
        )

    if ffmpeg_available:
        return (
            {
                "format": (
                    f"bestvideo{quality_filter}[ext=mp4]+bestaudio[ext=m4a]/"
                    f"bestvideo{quality_filter}+bestaudio/"
                    f"best{quality_filter}[ext=mp4]/best{quality_filter}"
                ),
                "merge_output_format": "mp4",
            },
            None,
        )

    return (
        {"format": f"best{quality_filter}[ext=mp4]/best{quality_filter}"},
        (
            "FFmpeg nao foi detectado. O app baixou a melhor faixa unica "
            "disponivel, o que pode limitar a resolucao final."
        ),
    )


def build_options(
    output_dir: Path, format_choice: str, quality_choice: str
) -> tuple[dict[str, object], str | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    template = str(output_dir / "%(title).120s [%(id)s].%(ext)s")
    ffmpeg_available = which("ffmpeg") is not None

    options: dict[str, object] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": template,
    }
    apply_youtube_compat_options(options)

    if format_choice == "mp3":
        if not ffmpeg_available:
            raise DownloadError(
                "Para exportar em MP3, instale o FFmpeg e tente novamente."
            )

        preferred_quality = "0" if quality_choice == "best" else quality_choice
        options.update(
            {
                "format": "bestaudio[acodec!=none][abr>0]/bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": preferred_quality,
                    }
                ],
            }
        )
        return (
            options,
            (
                "A qualidade final da musica tambem depende da faixa de audio "
                "original oferecida pela plataforma."
            ),
        )

    video_options, notice = build_video_selector(
        format_choice, quality_choice, ffmpeg_available
    )
    options.update(video_options)
    return options, notice


def build_selection_summary(
    format_choice: str,
    quality_choice: str,
    add_bpm_intro: bool = False,
    mirror_video: bool = False,
) -> str:
    format_label = FORMAT_LABELS[format_choice]
    summary = f"{format_label} em {get_quality_label(format_choice, quality_choice)}"
    if add_bpm_intro and is_music_format(format_choice):
        summary = f"{summary} + Contagem BPM 75"
    if mirror_video and is_video_format(format_choice):
        summary = f"{summary} + Video espelhado"
    return summary


def normalize_height(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def pick_thumbnail(info: dict[str, object]) -> str | None:
    thumbnail = info.get("thumbnail")
    if thumbnail:
        return str(thumbnail)

    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list) and thumbnails:
        last_item = thumbnails[-1]
        if isinstance(last_item, dict) and last_item.get("url"):
            return str(last_item["url"])

    return None


def get_format_size(format_data: dict[str, object], duration: int | float | None) -> int | None:
    size = format_data.get("filesize") or format_data.get("filesize_approx")
    if size:
        try:
            return int(size)
        except (TypeError, ValueError):
            return None

    bitrate = normalize_float(format_data.get("tbr"))
    if bitrate and duration:
        return int((bitrate * 1000 / 8) * float(duration))

    return None


def format_score(
    format_data: dict[str, object],
    duration: int | float | None,
    preferred_exts: tuple[str, ...],
) -> tuple[int, int, float, int]:
    ext = str(format_data.get("ext") or "")
    height = normalize_height(format_data.get("height"))
    bitrate = normalize_float(format_data.get("tbr"))
    size = get_format_size(format_data, duration) or 0
    ext_score = 1 if ext in preferred_exts else 0
    return (ext_score, height, bitrate, size)


def pick_best_format(
    formats: list[dict[str, object]],
    duration: int | float | None,
    preferred_exts: tuple[str, ...],
    *,
    require_video: bool,
    require_audio: bool,
    quality_limit: int | None,
) -> dict[str, object] | None:
    candidates: list[dict[str, object]] = []

    for format_data in formats:
        acodec = str(format_data.get("acodec") or "none")
        vcodec = str(format_data.get("vcodec") or "none")
        has_audio = acodec != "none"
        has_video = vcodec != "none"

        if require_video and not has_video:
            continue
        if not require_video and has_video:
            continue
        if require_audio and not has_audio:
            continue
        if not require_audio and has_audio:
            continue

        if quality_limit is not None and has_video:
            height = normalize_height(format_data.get("height"))
            if height and height > quality_limit:
                continue

        candidates.append(format_data)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: format_score(item, duration, preferred_exts),
    )


def estimate_filesize(
    info: dict[str, object], format_choice: str, quality_choice: str
) -> int | None:
    formats = info.get("formats")
    if not isinstance(formats, list):
        return None

    duration = info.get("duration")

    if format_choice == "mp3":
        target_bitrate = MUSIC_BITRATE_ESTIMATES.get(quality_choice)
        if target_bitrate and duration:
            return int((target_bitrate * 1000 / 8) * float(duration))

        audio_format = pick_best_format(
            formats,
            duration,
            ("m4a", "mp3", "webm", "opus"),
            require_video=False,
            require_audio=True,
            quality_limit=None,
        )
        if audio_format:
            return get_format_size(audio_format, duration)
        return None

    quality_limit = QUALITY_LIMITS[quality_choice]

    if format_choice == "mp4":
        video_format = pick_best_format(
            formats,
            duration,
            ("mp4",),
            require_video=True,
            require_audio=False,
            quality_limit=quality_limit,
        )
        audio_format = pick_best_format(
            formats,
            duration,
            ("m4a", "mp4"),
            require_video=False,
            require_audio=True,
            quality_limit=None,
        )
        combined_format = pick_best_format(
            formats,
            duration,
            ("mp4",),
            require_video=True,
            require_audio=True,
            quality_limit=quality_limit,
        )
    elif format_choice == "webm":
        video_format = pick_best_format(
            formats,
            duration,
            ("webm",),
            require_video=True,
            require_audio=False,
            quality_limit=quality_limit,
        )
        audio_format = pick_best_format(
            formats,
            duration,
            ("webm", "opus"),
            require_video=False,
            require_audio=True,
            quality_limit=None,
        )
        combined_format = pick_best_format(
            formats,
            duration,
            ("webm",),
            require_video=True,
            require_audio=True,
            quality_limit=quality_limit,
        )
    else:
        video_format = pick_best_format(
            formats,
            duration,
            tuple(),
            require_video=True,
            require_audio=False,
            quality_limit=quality_limit,
        )
        audio_format = pick_best_format(
            formats,
            duration,
            tuple(),
            require_video=False,
            require_audio=True,
            quality_limit=None,
        )
        combined_format = pick_best_format(
            formats,
            duration,
            tuple(),
            require_video=True,
            require_audio=True,
            quality_limit=quality_limit,
        )

    if video_format and audio_format:
        video_size = get_format_size(video_format, duration)
        audio_size = get_format_size(audio_format, duration)
        if video_size and audio_size:
            return video_size + audio_size

    if combined_format:
        return get_format_size(combined_format, duration)

    return None


def build_platform_label(info: dict[str, object]) -> str:
    raw_platform = str(
        info.get("extractor_key")
        or info.get("extractor")
        or info.get("webpage_url_domain")
        or "Link"
    ).lower()

    for key, label in PLATFORM_LABELS.items():
        if key in raw_platform:
            return label

    cleaned = raw_platform.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return "Link"
    return cleaned.title()


def build_preview_payload(
    info: dict[str, object],
    format_choice: str,
    quality_choice: str,
    add_bpm_intro: bool = False,
    mirror_video: bool = False,
) -> dict[str, object]:
    estimated_size = estimate_filesize(info, format_choice, quality_choice)
    uploader = str(
        info.get("uploader")
        or info.get("channel")
        or info.get("uploader_id")
        or "Origem nao identificada"
    )
    title = str(info.get("title") or "Video")
    duration = info.get("duration")

    return {
        "title": title,
        "uploader": uploader,
        "thumbnail_url": pick_thumbnail(info),
        "duration_seconds": int(duration) if duration else None,
        "duration_label": format_duration(duration),
        "platform_label": build_platform_label(info),
        "selection_summary": build_selection_summary(
            format_choice, quality_choice, add_bpm_intro, mirror_video
        ),
        "format_label": FORMAT_LABELS[format_choice],
        "quality_label": get_quality_label(format_choice, quality_choice),
        "add_bpm_intro": add_bpm_intro,
        "mirror_video": mirror_video,
        "filesize_estimate_bytes": estimated_size,
        "filesize_estimate_label": format_bytes(estimated_size),
        "video_url": str(info.get("webpage_url") or info.get("original_url") or ""),
    }


def extract_video_preview(
    video_url: str,
    format_choice: str,
    quality_choice: str,
    add_bpm_intro: bool = False,
    mirror_video: bool = False,
) -> dict[str, object]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    apply_youtube_compat_options(options)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        log_yt_dlp_failure("analisar", video_url, exc)
        raise DownloadError(
            build_yt_dlp_error_message("analisar", video_url, exc)
        ) from exc

    return build_preview_payload(
        info, format_choice, quality_choice, add_bpm_intro, mirror_video
    )


def build_progress_payload(progress_data: dict[str, object]) -> dict[str, object] | None:
    raw_status = str(progress_data.get("status") or "")
    info_dict = progress_data.get("info_dict")
    if not isinstance(info_dict, dict):
        info_dict = {}

    title = str(info_dict.get("title") or "Preparando download")
    total_bytes = progress_data.get("total_bytes") or progress_data.get(
        "total_bytes_estimate"
    )
    downloaded_bytes = progress_data.get("downloaded_bytes")
    speed = progress_data.get("speed")
    eta = progress_data.get("eta")

    if raw_status == "finished":
        return {
            "status": "processing",
            "title": title,
            "progress_pct": VIDEO_MIRROR_PROGRESS_RANGE[0],
            "downloaded_bytes": downloaded_bytes,
            "downloaded_label": format_bytes(downloaded_bytes),
            "total_bytes": total_bytes,
            "total_label": format_bytes(total_bytes),
            "speed_label": format_speed(speed),
            "eta_seconds": 0,
            "eta_label": "Finalizando",
        }

    if raw_status != "downloading":
        return None

    progress_pct = 0.0
    if total_bytes and downloaded_bytes:
        progress_pct = min((float(downloaded_bytes) / float(total_bytes)) * 100, 100)

    eta_label = "--"
    if isinstance(eta, (int, float)):
        eta_label = f"{max(int(eta), 0)}s"

    return {
        "status": "downloading",
        "title": title,
        "progress_pct": round(progress_pct, 2),
        "downloaded_bytes": downloaded_bytes,
        "downloaded_label": format_bytes(downloaded_bytes),
        "total_bytes": total_bytes,
        "total_label": format_bytes(total_bytes),
        "speed_label": format_speed(speed),
        "eta_seconds": int(eta) if isinstance(eta, (int, float)) else None,
        "eta_label": eta_label,
    }


def resolve_file_path(
    ydl: yt_dlp.YoutubeDL,
    info: dict[str, object],
    output_dir: Path,
    format_choice: str,
) -> Path:
    video_id = str(info.get("id") or "").strip()
    if video_id:
        marker = f"[{video_id}]."
        candidates = sorted(
            (
                path
                for path in output_dir.iterdir()
                if path.is_file() and marker in path.name
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]

    prepared = Path(ydl.prepare_filename(info))

    if format_choice == "mp3":
        return prepared.with_suffix(".mp3")

    return prepared


def build_mp3_encoder_args(quality_choice: str) -> list[str]:
    if quality_choice == "best":
        return ["-codec:a", "libmp3lame", "-q:a", "0"]
    return ["-codec:a", "libmp3lame", "-b:a", f"{quality_choice}k"]


def run_media_command(command: list[str], failure_message: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode == 0:
        return completed.stdout

    stderr = (completed.stderr or "").strip()
    detail = stderr.splitlines()[-1] if stderr else "Sem detalhes do FFmpeg."
    raise DownloadError(f"{failure_message} Detalhe: {detail}")


def run_ffmpeg_command_with_progress(
    command: list[str],
    failure_message: str,
    *,
    total_duration_seconds: float | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
    title: str = "Video",
    status_label: str = "Processando arquivo",
) -> None:
    ffmpeg_command = [
        command[0],
        "-hide_banner",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        *command[1:],
    ]
    process = subprocess.Popen(
        ffmpeg_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    current_speed_label = "--"
    progress_start, progress_end = VIDEO_MIRROR_PROGRESS_RANGE

    if progress_callback is not None:
        progress_callback(
            {
                "status": "processing",
                "status_label": status_label,
                "title": title,
                "progress_pct": progress_start,
                "downloaded_label": "0%",
                "total_label": status_label,
                "speed_label": current_speed_label,
                "eta_label": "Calculando",
            }
        )

    stderr_output = ""
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                if key == "speed" and value:
                    current_speed_label = value.strip()
                    continue

                if key != "out_time":
                    continue

                elapsed_seconds = parse_ffmpeg_timestamp(value)
                if (
                    elapsed_seconds is None
                    or total_duration_seconds is None
                    or total_duration_seconds <= 0
                    or progress_callback is None
                ):
                    continue

                stage_ratio = min(max(elapsed_seconds / total_duration_seconds, 0.0), 1.0)
                progress_pct = progress_start + (
                    (progress_end - progress_start) * stage_ratio
                )

                eta_label = "Calculando"
                speed_multiplier = parse_ffmpeg_speed_multiplier(current_speed_label)
                if (
                    speed_multiplier
                    and speed_multiplier > 0
                    and elapsed_seconds < total_duration_seconds
                ):
                    remaining_seconds = max(total_duration_seconds - elapsed_seconds, 0.0)
                    eta_seconds = int(remaining_seconds / speed_multiplier)
                    eta_label = f"{eta_seconds}s"

                progress_callback(
                    {
                        "status": "processing",
                        "status_label": status_label,
                        "title": title,
                        "progress_pct": round(progress_pct, 2),
                        "downloaded_label": f"{stage_ratio * 100:.0f}%",
                        "total_label": status_label,
                        "speed_label": current_speed_label,
                        "eta_label": eta_label,
                    }
                )

        if process.stderr is not None:
            stderr_output = process.stderr.read()
        return_code = process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    if return_code == 0:
        return

    stderr = (stderr_output or "").strip()
    detail = stderr.splitlines()[-1] if stderr else "Sem detalhes do FFmpeg."
    raise DownloadError(f"{failure_message} Detalhe: {detail}")


def require_bpm_intro_asset() -> Path:
    if BPM75_INTRO_PATH.exists():
        return BPM75_INTRO_PATH

    raise DownloadError(
        "O arquivo da contagem inicial BPM 75 nao foi encontrado em "
        f'"{BPM75_INTRO_PATH}".'
    )


def probe_audio_stream(file_path: Path) -> dict[str, object]:
    ffprobe_cmd = which("ffprobe")
    if ffprobe_cmd is None:
        raise DownloadError(
            "O FFprobe nao foi encontrado. Instale o pacote completo do FFmpeg "
            "para validar a musica antes de adicionar a contagem BPM 75."
        )

    output = run_media_command(
        [
            ffprobe_cmd,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "a:0",
            str(file_path),
        ],
        "Nao foi possivel validar o audio da musica para adicionar a contagem BPM 75.",
    )

    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError as exc:
        raise DownloadError(
            "O FFprobe retornou um resultado invalido ao analisar a musica."
        ) from exc

    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise DownloadError(
            "A musica baixada nao possui uma faixa de audio valida para receber a contagem BPM 75."
        )

    first_stream = streams[0]
    if not isinstance(first_stream, dict):
        raise DownloadError(
            "Nao foi possivel confirmar os dados do audio antes da concatenacao."
        )

    return first_stream


def probe_video_stream(file_path: Path) -> dict[str, object]:
    ffprobe_cmd = which("ffprobe")
    if ffprobe_cmd is None:
        raise DownloadError(
            "O FFprobe nao foi encontrado. Instale o pacote completo do FFmpeg "
            "para validar o video antes de aplicar o espelhamento."
        )

    output = run_media_command(
        [
            ffprobe_cmd,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "v:0",
            str(file_path),
        ],
        "Nao foi possivel validar o video antes de aplicar o espelhamento.",
    )

    try:
        payload = json.loads(output or "{}")
    except json.JSONDecodeError as exc:
        raise DownloadError(
            "O FFprobe retornou um resultado invalido ao analisar o video."
        ) from exc

    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise DownloadError(
            "O arquivo baixado nao possui uma faixa de video valida para ser espelhada."
        )

    first_stream = streams[0]
    if not isinstance(first_stream, dict):
        raise DownloadError(
            "Nao foi possivel confirmar os dados do video antes do espelhamento."
        )

    return first_stream


def probe_media_duration(file_path: Path) -> float | None:
    ffprobe_cmd = which("ffprobe")
    if ffprobe_cmd is None:
        return None

    try:
        output = run_media_command(
            [
                ffprobe_cmd,
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            "Nao foi possivel medir a duracao da midia antes do processamento.",
        )
    except DownloadError:
        return None

    try:
        duration = float(str(output or "").strip())
    except ValueError:
        return None

    if duration <= 0:
        return None
    return duration


@lru_cache(maxsize=1)
def list_available_ffmpeg_encoders() -> set[str]:
    ffmpeg_cmd = which("ffmpeg")
    if ffmpeg_cmd is None:
        return set()

    completed = subprocess.run(
        [ffmpeg_cmd, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return set()

    encoders: set[str] = set()
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            encoders.add(parts[1].strip())

    return encoders


def normalize_audio_for_concat(
    input_path: Path,
    output_path: Path,
    *,
    volume: float | None = None,
) -> None:
    ffmpeg_cmd = which("ffmpeg")
    if ffmpeg_cmd is None:
        raise DownloadError(
            "O FFmpeg nao foi encontrado. Instale o FFmpeg para adicionar a contagem BPM 75."
        )

    filter_parts = [
        f"aresample={TARGET_AUDIO_SAMPLE_RATE}",
        (
            "aformat="
            f"sample_rates={TARGET_AUDIO_SAMPLE_RATE}:channel_layouts=stereo"
        ),
    ]
    if volume is not None:
        filter_parts.append(f"volume={volume}")

    run_media_command(
        [
            ffmpeg_cmd,
            "-y",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            ",".join(filter_parts),
            "-ar",
            TARGET_AUDIO_SAMPLE_RATE,
            "-ac",
            TARGET_AUDIO_CHANNELS,
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        "Nao foi possivel preparar os audios para adicionar a contagem BPM 75.",
    )


def build_bpm75_file_path(file_path: Path) -> Path:
    if file_path.stem.endswith("_bpm75"):
        return file_path
    return file_path.with_name(f"{file_path.stem}_bpm75{file_path.suffix}")


def build_mirrored_file_path(file_path: Path) -> Path:
    if file_path.stem.endswith("_espelhado"):
        return file_path
    return file_path.with_name(f"{file_path.stem}_espelhado{file_path.suffix}")


def build_mirror_video_commands(
    input_path: Path,
    output_path: Path,
    format_choice: str,
    quality_choice: str,
) -> list[tuple[list[str], str]]:
    ffmpeg_cmd = which("ffmpeg")
    if ffmpeg_cmd is None:
        raise DownloadError(
            "O FFmpeg nao foi encontrado. Instale o FFmpeg para espelhar videos."
        )

    base_command = [
        ffmpeg_cmd,
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        "hflip",
    ]

    if format_choice == "webm":
        webm_command = [
            *base_command,
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "31",
            "-b:v",
            "0",
            "-deadline",
            "good",
            "-cpu-used",
            "4",
            "-row-mt",
            "1",
            "-c:a",
            "copy",
            str(output_path),
        ]
        return [(webm_command, "software")]

    commands: list[tuple[list[str], str]] = []
    available_encoders = list_available_ffmpeg_encoders()
    hardware_encoders_disabled = env_flag("VIDEOFLOW_DISABLE_HARDWARE_ENCODERS")
    if not hardware_encoders_disabled and "h264_nvenc" in available_encoders:
        nvenc_command = [
            *base_command,
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-cq",
            VIDEO_MIRROR_NVENC_CQ_BY_QUALITY.get(quality_choice, "21"),
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
        ]
        if format_choice == "mp4":
            nvenc_command.extend(["-movflags", "+faststart"])
        nvenc_command.append(str(output_path))
        commands.append((nvenc_command, "h264_nvenc"))

    software_command = [
        *base_command,
        "-c:v",
        "libx264",
        "-preset",
        get_mirror_software_preset(),
        "-crf",
        VIDEO_MIRROR_CRF_BY_QUALITY.get(quality_choice, "20"),
        "-pix_fmt",
        "yuv420p",
        *get_mirror_thread_args(),
        "-c:a",
        "copy",
    ]
    if format_choice == "mp4":
        software_command.extend(["-movflags", "+faststart"])
    software_command.append(str(output_path))
    commands.append((software_command, "software"))

    return commands


def cleanup_stale_mirror_temp_files(output_dir: Path) -> None:
    now_ts = time()
    for temp_file in output_dir.glob("videoflow-mirror-*"):
        try:
            if not temp_file.is_file():
                continue
            if temp_file.stat().st_size == 0:
                temp_file.unlink(missing_ok=True)
                continue
            file_age = now_ts - temp_file.stat().st_mtime
            if file_age >= STALE_MIRROR_TEMP_MAX_AGE_SECONDS:
                temp_file.unlink(missing_ok=True)
        except OSError:
            continue


def mirror_video_file(
    file_path: Path,
    format_choice: str,
    quality_choice: str,
    *,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
    title: str = "Video",
) -> Path:
    probe_video_stream(file_path)
    cleanup_stale_mirror_temp_files(file_path.parent)
    media_duration_seconds = probe_media_duration(file_path)

    file_descriptor, temp_name = tempfile.mkstemp(
        prefix="videoflow-mirror-",
        suffix=file_path.suffix,
        dir=file_path.parent,
    )
    os.close(file_descriptor)
    mirrored_output = Path(temp_name)
    mirrored_output.unlink(missing_ok=True)

    try:
        # O espelhamento horizontal do video entra aqui: o arquivo ja baixado
        # passa por um hflip no FFmpeg e volta para a mesma extensao final.
        last_error: DownloadError | None = None
        for command, encoder_label in build_mirror_video_commands(
            file_path,
            mirrored_output,
            format_choice,
            quality_choice,
        ):
            try:
                run_ffmpeg_command_with_progress(
                    command,
                    "Nao foi possivel espelhar o video baixado.",
                    total_duration_seconds=media_duration_seconds,
                    progress_callback=progress_callback,
                    title=title,
                    status_label="Espelhando video",
                )
                break
            except DownloadError as exc:
                last_error = exc
                mirrored_output.unlink(missing_ok=True)
        else:
            if last_error is not None:
                raise last_error

        if not mirrored_output.exists() or mirrored_output.stat().st_size == 0:
            raise DownloadError(
                "O FFmpeg nao gerou um arquivo final valido com o video espelhado."
            )

        final_path = build_mirrored_file_path(file_path)
        if final_path.exists() and final_path != file_path:
            final_path.unlink()

        mirrored_output.replace(final_path)
    finally:
        mirrored_output.unlink(missing_ok=True)

    if final_path != file_path and file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            # Se o Windows ainda estiver segurando o arquivo original por alguns
            # instantes, mantemos o arquivo espelhado pronto sem falhar o job.
            pass

    return final_path


def prepend_bpm75_intro(file_path: Path, quality_choice: str) -> Path:
    intro_asset_path = require_bpm_intro_asset()
    probe_audio_stream(file_path)

    with tempfile.TemporaryDirectory(prefix="videoflow-bpm75-") as temp_dir:
        temp_root = Path(temp_dir)
        normalized_intro = temp_root / "intro.wav"
        normalized_music = temp_root / "music.wav"
        merged_output = temp_root / "merged.mp3"

        # A contagem BPM 75 entra aqui: os dois arquivos sao normalizados para
        # o mesmo codec/taxa de amostragem/canais antes da concatenacao final.
        normalize_audio_for_concat(
            intro_asset_path,
            normalized_intro,
            volume=INTRO_NORMALIZE_GAIN,
        )
        normalize_audio_for_concat(file_path, normalized_music)

        ffmpeg_cmd = which("ffmpeg")
        if ffmpeg_cmd is None:
            raise DownloadError(
                "O FFmpeg nao foi encontrado. Instale o FFmpeg para adicionar a contagem BPM 75."
            )

        run_media_command(
            [
                ffmpeg_cmd,
                "-y",
                "-i",
                str(normalized_intro),
                "-i",
                str(normalized_music),
                "-filter_complex",
                "[0:a][1:a]concat=n=2:v=0:a=1[outa]",
                "-map",
                "[outa]",
                *build_mp3_encoder_args(quality_choice),
                str(merged_output),
            ],
            "Nao foi possivel juntar a contagem BPM 75 com a musica baixada.",
        )

        if not merged_output.exists() or merged_output.stat().st_size == 0:
            raise DownloadError(
                "O FFmpeg nao gerou um arquivo final valido com a contagem BPM 75."
            )

        final_path = build_bpm75_file_path(file_path)
        if final_path.exists() and final_path != file_path:
            final_path.unlink()

        merged_output.replace(final_path)

    if final_path != file_path and file_path.exists():
        file_path.unlink()

    return final_path


def download_video(
    video_url: str,
    output_dir: Path,
    format_choice: str,
    quality_choice: str,
    add_bpm_intro: bool = False,
    mirror_video: bool = False,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    options, notice = build_options(output_dir, format_choice, quality_choice)

    if progress_callback is not None:
        def progress_hook(progress_data: dict[str, object]) -> None:
            payload = build_progress_payload(progress_data)
            if payload is not None:
                progress_callback(payload)

        options["progress_hooks"] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=True)
            file_path = resolve_file_path(ydl, info, output_dir, format_choice)
    except yt_dlp.utils.DownloadError as exc:
        log_yt_dlp_failure("baixar", video_url, exc)
        raise DownloadError(
            build_yt_dlp_error_message("baixar", video_url, exc)
        ) from exc

    title = str(info.get("title") or "Video")

    if add_bpm_intro and format_choice == "mp3":
        # A introducao de 4 batidas em BPM 75 so e aplicada ao fluxo de musica.
        file_path = prepend_bpm75_intro(file_path, quality_choice)
        if not file_path.stem.endswith("_bpm75"):
            raise DownloadError(
                "A contagem BPM 75 foi solicitada, mas o arquivo final nao foi gerado com a identificacao esperada."
            )
        notice = merge_notices(
            notice,
            "A contagem inicial BPM 75 foi adicionada antes da musica.",
        )

    if mirror_video and is_video_format(format_choice):
        file_path = mirror_video_file(
            file_path,
            format_choice,
            quality_choice,
            progress_callback=progress_callback,
            title=title,
        )
        if not file_path.stem.endswith("_espelhado"):
            raise DownloadError(
                "O espelhamento foi solicitado, mas o arquivo final nao foi gerado com a identificacao esperada."
            )
        notice = merge_notices(
            notice,
            "O video foi espelhado horizontalmente antes de ser salvo.",
        )

    return {
        "title": title,
        "uploader": str(
            info.get("uploader")
            or info.get("channel")
            or info.get("uploader_id")
            or "Origem nao identificada"
        ),
        "thumbnail_url": pick_thumbnail(info),
        "duration_label": format_duration(info.get("duration")),
        "platform_label": build_platform_label(info),
        "file_path": file_path,
        "output_dir": output_dir,
        "format_choice": format_choice,
        "quality_choice": quality_choice,
        "add_bpm_intro": add_bpm_intro,
        "mirror_video": mirror_video,
        "selection_summary": build_selection_summary(
            format_choice, quality_choice, add_bpm_intro, mirror_video
        ),
        "notice": notice,
    }
