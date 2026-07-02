from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from uuid import uuid4

from downloader import DownloadError, build_selection_summary, download_video


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reveal_download_in_explorer(file_path: Path) -> None:
    resolved_path = file_path.resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {resolved_path}")

    if sys.platform.startswith("win"):
        try:
            subprocess.Popen(
                ["explorer", "/select,", str(resolved_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            os.startfile(str(resolved_path.parent))
            return

    if hasattr(os, "startfile"):
        os.startfile(str(resolved_path.parent))
        return

    raise OSError("Nao foi possivel abrir a pasta automaticamente nesta plataforma.")


class HistoryStore:
    def __init__(self, file_path: Path, *, limit: int = 30) -> None:
        self.file_path = file_path
        self.limit = limit
        self.lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.file_path.exists():
            self.file_path.write_text("[]", encoding="utf-8")

    def _read_entries(self) -> list[dict[str, object]]:
        try:
            raw_content = self.file_path.read_text(encoding="utf-8")
            parsed = json.loads(raw_content)
        except (OSError, json.JSONDecodeError):
            parsed = []

        if not isinstance(parsed, list):
            return []

        return [entry for entry in parsed if isinstance(entry, dict)]

    def _write_entries(self, entries: list[dict[str, object]]) -> None:
        self.file_path.write_text(
            json.dumps(entries[: self.limit], ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def list_entries(self) -> list[dict[str, object]]:
        with self.lock:
            return [dict(entry) for entry in self._read_entries()]

    def add_entry(self, entry: dict[str, object]) -> None:
        with self.lock:
            entries = self._read_entries()
            entries.insert(0, dict(entry))
            self._write_entries(entries)

    def clear(self) -> None:
        with self.lock:
            self._write_entries([])


class PostgresHistoryStore:
    def __init__(
        self,
        database_url: str,
        *,
        limit: int = 30,
        connect_factory: object | None = None,
    ) -> None:
        self.database_url = database_url
        self.limit = limit
        self.connect_factory = connect_factory
        self.lock = Lock()
        self._ensure_schema()

    def _connect(self) -> object:
        if self.connect_factory is not None:
            return self.connect_factory(self.database_url)  # type: ignore[misc]

        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "DATABASE_URL foi configurado, mas o pacote psycopg nao esta instalado."
            ) from exc

        return psycopg.connect(self.database_url, autocommit=True)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS download_history (
                        id TEXT PRIMARY KEY,
                        completed_at TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

    def list_entries(self) -> list[dict[str, object]]:
        with self.lock:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT payload::text
                        FROM download_history
                        ORDER BY completed_at DESC, updated_at DESC
                        LIMIT %s
                        """,
                        (self.limit,),
                    )
                    rows = cursor.fetchall()

        entries: list[dict[str, object]] = []
        for row in rows:
            try:
                parsed = json.loads(str(row[0]))
            except (IndexError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)

        return entries

    def add_entry(self, entry: dict[str, object]) -> None:
        next_entry = dict(entry)
        entry_id = str(next_entry.get("id") or uuid4().hex[:12])
        completed_at = str(next_entry.get("completed_at") or now_iso())
        next_entry["id"] = entry_id
        next_entry["completed_at"] = completed_at
        payload = json.dumps(next_entry, ensure_ascii=True)

        with self.lock:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO download_history (id, completed_at, payload)
                        VALUES (%s, %s, %s::jsonb)
                        ON CONFLICT (id) DO UPDATE SET
                            completed_at = EXCLUDED.completed_at,
                            payload = EXCLUDED.payload,
                            updated_at = NOW()
                        """,
                        (entry_id, completed_at, payload),
                    )
                    cursor.execute(
                        """
                        DELETE FROM download_history
                        WHERE id NOT IN (
                            SELECT id
                            FROM download_history
                            ORDER BY completed_at DESC, updated_at DESC
                            LIMIT %s
                        )
                        """,
                        (self.limit,),
                    )

    def clear(self) -> None:
        with self.lock:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM download_history")


class DownloadManager:
    def __init__(
        self,
        history_store: HistoryStore,
        *,
        reveal_on_complete: bool = True,
    ) -> None:
        self.history_store = history_store
        self.reveal_on_complete = reveal_on_complete
        self.jobs: dict[str, dict[str, object]] = {}
        self.lock = Lock()
        self.queue: Queue[str] = Queue()
        self.worker = Thread(
            target=self._worker_loop,
            name="videoflow-download-worker",
            daemon=True,
        )
        self.worker.start()

    def create_job(
        self,
        *,
        video_url: str,
        output_dir: Path,
        format_choice: str,
        quality_choice: str,
        add_bpm_intro: bool = False,
        mirror_video: bool = False,
        preview: dict[str, object] | None = None,
    ) -> dict[str, object]:
        preview = preview or {}
        job_id = uuid4().hex[:12]
        selection_summary = str(
            preview.get("selection_summary")
            or build_selection_summary(
                format_choice,
                quality_choice,
                add_bpm_intro,
                mirror_video,
            )
        )

        job = {
            "id": job_id,
            "video_url": video_url,
            "output_dir": str(output_dir),
            "format_choice": format_choice,
            "quality_choice": quality_choice,
            "add_bpm_intro": add_bpm_intro,
            "mirror_video": mirror_video,
            "selection_summary": selection_summary,
            "status": "queued",
            "status_label": "Na fila",
            "queue_position": None,
            "progress_pct": 0.0,
            "downloaded_label": "0 B",
            "total_label": str(preview.get("filesize_estimate_label") or "Calculando"),
            "speed_label": "--",
            "eta_label": "--",
            "title": str(preview.get("title") or "Preparando download"),
            "uploader": str(preview.get("uploader") or "Origem nao identificada"),
            "platform_label": str(preview.get("platform_label") or "Link"),
            "thumbnail_url": preview.get("thumbnail_url"),
            "duration_label": preview.get("duration_label"),
            "notice": None,
            "error": None,
            "file_path": None,
            "created_at": now_iso(),
            "started_at": None,
            "completed_at": None,
        }

        with self.lock:
            self.jobs[job_id] = job
            self._recompute_queue_positions_locked()

        self.queue.put(job_id)
        return self.get_job(job_id) or dict(job)

    def list_jobs(self) -> list[dict[str, object]]:
        with self.lock:
            jobs = [dict(job) for job in self.jobs.values()]

        jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return jobs

    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            return dict(job)

    def _recompute_queue_positions_locked(self) -> None:
        queued_jobs = sorted(
            (
                job
                for job in self.jobs.values()
                if str(job.get("status")) == "queued"
            ),
            key=lambda item: str(item.get("created_at") or ""),
        )

        queued_ids = {str(job["id"]) for job in queued_jobs}
        for index, job in enumerate(queued_jobs, start=1):
            job["queue_position"] = index

        for job in self.jobs.values():
            if str(job["id"]) not in queued_ids:
                job["queue_position"] = None

    def _update_job(self, job_id: str, **changes: object) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return

            job.update(changes)
            self._recompute_queue_positions_locked()

    def _worker_loop(self) -> None:
        while True:
            job_id = self.queue.get()
            try:
                self._run_job(job_id)
            finally:
                self.queue.task_done()

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            return

        self._update_job(
            job_id,
            status="starting",
            status_label="Iniciando",
            started_at=now_iso(),
            error=None,
        )

        def on_progress(payload: dict[str, object]) -> None:
            next_status = str(payload.get("status") or "downloading")
            next_label = "Baixando"
            if next_status == "processing":
                next_label = "Processando arquivo"
            next_label = str(payload.get("status_label") or next_label)

            updates = {
                "status": next_status,
                "status_label": next_label,
                "progress_pct": float(payload.get("progress_pct") or 0.0),
                "downloaded_label": str(
                    payload.get("downloaded_label") or "Calculando"
                ),
                "total_label": str(payload.get("total_label") or "Calculando"),
                "speed_label": str(payload.get("speed_label") or "--"),
                "eta_label": str(payload.get("eta_label") or "--"),
                "title": str(payload.get("title") or job.get("title") or "Video"),
            }
            self._update_job(job_id, **updates)

        try:
            result = download_video(
                str(job["video_url"]),
                Path(str(job["output_dir"])),
                str(job["format_choice"]),
                str(job["quality_choice"]),
                add_bpm_intro=bool(job.get("add_bpm_intro")),
                mirror_video=bool(job.get("mirror_video")),
                progress_callback=on_progress,
            )
        except DownloadError as exc:
            self._update_job(
                job_id,
                status="failed",
                status_label="Falhou",
                error=str(exc),
                completed_at=now_iso(),
            )
            return
        except Exception as exc:  # pragma: no cover - seguranca
            self._update_job(
                job_id,
                status="failed",
                status_label="Falhou",
                error=f"Falha interna: {exc}",
                completed_at=now_iso(),
            )
            return

        completed_at = now_iso()
        file_path = str(result["file_path"])

        completed_job = {
            "status": "completed",
            "status_label": "Concluido",
            "progress_pct": 100.0,
            "downloaded_label": result.get("notice") and "Finalizado" or "Pronto",
            "total_label": "100%",
            "speed_label": "--",
            "eta_label": "Agora",
            "file_path": file_path,
            "title": str(result["title"]),
            "uploader": str(result.get("uploader") or job.get("uploader") or ""),
            "platform_label": str(
                result.get("platform_label") or job.get("platform_label") or "Link"
            ),
            "thumbnail_url": result.get("thumbnail_url") or job.get("thumbnail_url"),
            "duration_label": result.get("duration_label") or job.get("duration_label"),
            "selection_summary": str(result["selection_summary"]),
            "notice": result.get("notice"),
            "completed_at": completed_at,
        }
        self._update_job(job_id, **completed_job)

        self.history_store.add_entry(
            {
                "id": job_id,
                "title": str(result["title"]),
                "uploader": str(result.get("uploader") or ""),
                "platform_label": str(result.get("platform_label") or "Link"),
                "thumbnail_url": result.get("thumbnail_url"),
                "duration_label": result.get("duration_label"),
                "selection_summary": str(result["selection_summary"]),
                "file_path": file_path,
                "output_dir": str(job["output_dir"]),
                "completed_at": completed_at,
                "format_choice": str(job["format_choice"]),
                "quality_choice": str(job["quality_choice"]),
                "add_bpm_intro": bool(job.get("add_bpm_intro")),
                "mirror_video": bool(job.get("mirror_video")),
            }
        )

        if self.reveal_on_complete:
            try:
                reveal_download_in_explorer(Path(file_path))
            except OSError:
                # Abrir a pasta e um extra de UX; uma falha aqui nao pode invalidar
                # um download que ja terminou com sucesso.
                pass
