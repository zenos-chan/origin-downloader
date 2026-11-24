import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import unquote

import requests

from .client import (
    DEFAULT_HEADERS,
    HDHub4uClient,
    HDHub4uError,
    _sanitize_filename,
    build_media_naming,
)


class DownloadManager:
    """Manages background streaming downloads into configured media folders."""

    def __init__(self, client: HDHub4uClient | None = None, db_path: str | None = None):
        self.client = client or HDHub4uClient()
        self.db_path = db_path
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        if self.db_path:
            self._init_storage()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_storage(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    resolved_url TEXT NOT NULL DEFAULT '',
                    media_type TEXT NOT NULL,
                    destination_dir TEXT NOT NULL,
                    file_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                    progress_pct INTEGER NOT NULL DEFAULT 0,
                    speed_mbps REAL NOT NULL DEFAULT 0.0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                UPDATE downloads
                SET status = 'failed', error = 'Interrupted by server restart'
                WHERE status IN ('resolving', 'downloading')
                """
            )
            rows = conn.execute(
                "SELECT * FROM downloads ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
            conn.commit()
            for row in rows:
                self._jobs[row["id"]] = dict(row)

    def _persist_job(self, job: dict):
        if not self.db_path:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO downloads (
                    id, title, filename, source_url, resolved_url, media_type,
                    destination_dir, file_path, status, total_bytes,
                    downloaded_bytes, progress_pct, speed_mbps, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    filename = excluded.filename,
                    resolved_url = excluded.resolved_url,
                    destination_dir = excluded.destination_dir,
                    file_path = excluded.file_path,
                    status = excluded.status,
                    total_bytes = excluded.total_bytes,
                    downloaded_bytes = excluded.downloaded_bytes,
                    progress_pct = excluded.progress_pct,
                    speed_mbps = excluded.speed_mbps,
                    error = excluded.error
                """,
                (
                    job["id"],
                    job["title"],
                    job["filename"],
                    job["source_url"],
                    job["resolved_url"],
                    job["media_type"],
                    job["destination_dir"],
                    job["file_path"],
                    job["status"],
                    job["total_bytes"],
                    job["downloaded_bytes"],
                    job["progress_pct"],
                    job["speed_mbps"],
                    job["error"],
                    job["created_at"],
                ),
            )
            conn.commit()

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [dict(job) for job in reversed(list(self._jobs.values()))]

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_flags.get(job_id)
            job = self._jobs.get(job_id)
            if not event or not job:
                return False
            if job["status"] in ("completed", "failed", "cancelled"):
                return False
            event.set()
            job["status"] = "cancelled"
            snapshot = dict(job)
        self._persist_job(snapshot)
        return True

    def start_download(
        self,
        title: str,
        source_url: str,
        media_type: str,
        destination_dir: str,
        filename: str = "",
        quality_label: str = "",
    ) -> dict:
        job_id = uuid.uuid4().hex[:10]
        base_dir = os.path.abspath(os.path.expanduser(destination_dir))
        naming = build_media_naming(
            title=title,
            quality_label=quality_label,
            original_filename=filename,
            media_type=media_type,
        )
        target_dir = os.path.join(base_dir, naming["folder_name"])
        cancel_event = threading.Event()

        job = {
            "id": job_id,
            "title": title,
            "source_url": source_url,
            "resolved_url": "",
            "media_type": media_type,
            "destination_dir": target_dir,
            "filename": naming["filename"],
            "file_path": "",
            "status": "resolving",
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "progress_pct": 0,
            "speed_mbps": 0.0,
            "error": "",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with self._lock:
            self._jobs[job_id] = job
            self._cancel_flags[job_id] = cancel_event
        self._persist_job(job)

        worker = threading.Thread(
            target=self._run_download,
            args=(
                job_id,
                source_url,
                target_dir,
                title,
                filename,
                quality_label,
                media_type,
                cancel_event,
            ),
            daemon=True,
        )
        worker.start()
        return dict(job)

    def _update_job(self, job_id: str, persist: bool = False, **fields):
        snapshot = None
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)
                if persist:
                    snapshot = dict(self._jobs[job_id])
        if snapshot is not None:
            self._persist_job(snapshot)

    def _run_download(
        self,
        job_id: str,
        source_url: str,
        destination_dir: str,
        title: str,
        requested_filename: str,
        quality_label: str,
        media_type: str,
        cancel_event: threading.Event,
    ):
        part_path = ""
        try:
            mirrors = self.client.resolve_download_links(source_url, fallback_title=title)
            if cancel_event.is_set():
                return

            if mirrors and all(m.get("is_pack_item") for m in mirrors):
                raise HDHub4uError(
                    "This link is an episode pack. Click 'Mirrors' to select or download episodes."
                )

            os.makedirs(destination_dir, exist_ok=True)

            last_error = None
            for mirror in mirrors:
                if cancel_event.is_set():
                    return
                direct_url = mirror["url"]
                raw_mirror_name = requested_filename or mirror.get("filename") or ""
                pre_naming = build_media_naming(
                    title=title,
                    quality_label=quality_label,
                    original_filename=raw_mirror_name,
                    media_type=media_type,
                )
                self._update_job(
                    job_id,
                    persist=True,
                    resolved_url=direct_url,
                    filename=pre_naming["filename"],
                    status="downloading",
                    error="",
                )

                try:
                    with requests.get(
                        direct_url,
                        headers=DEFAULT_HEADERS,
                        stream=True,
                        timeout=(15, 60),
                    ) as resp:
                        resp.raise_for_status()

                        header_name = self._filename_from_headers(resp.headers)
                        final_naming = build_media_naming(
                            title=title,
                            quality_label=quality_label,
                            original_filename=header_name or raw_mirror_name,
                            media_type=media_type,
                        )
                        final_name = _sanitize_filename(final_naming["filename"])
                        final_path = self._unique_path(destination_dir, final_name)
                        part_path = f"{final_path}.part"
                        total_bytes = int(resp.headers.get("Content-Length") or 0)

                        self._update_job(
                            job_id,
                            persist=True,
                            filename=os.path.basename(final_path),
                            file_path=final_path,
                            total_bytes=total_bytes,
                        )

                        downloaded = 0
                        start_time = time.monotonic()
                        last_tick = start_time

                        with open(part_path, "wb") as fh:
                            for chunk in resp.iter_content(chunk_size=1024 * 256):
                                if cancel_event.is_set():
                                    raise InterruptedError("Download cancelled by user.")
                                if not chunk:
                                    continue
                                fh.write(chunk)
                                downloaded += len(chunk)

                                now = time.monotonic()
                                if now - last_tick >= 0.25 or (
                                    total_bytes and downloaded >= total_bytes
                                ):
                                    elapsed = max(now - start_time, 0.001)
                                    speed_mbps = round(
                                        (downloaded / (1024 * 1024)) / elapsed, 2
                                    )
                                    pct = (
                                        min(round((downloaded / total_bytes) * 100), 100)
                                        if total_bytes
                                        else 0
                                    )
                                    self._update_job(
                                        job_id,
                                        downloaded_bytes=downloaded,
                                        progress_pct=pct,
                                        speed_mbps=speed_mbps,
                                    )
                                    last_tick = now

                        os.replace(part_path, final_path)
                        part_path = ""
                        self._update_job(
                            job_id,
                            persist=True,
                            status="completed",
                            downloaded_bytes=downloaded,
                            total_bytes=total_bytes or downloaded,
                            progress_pct=100,
                        )
                        return
                except InterruptedError:
                    self._cleanup_part(part_path)
                    self._update_job(job_id, persist=True, status="cancelled", error="Cancelled")
                    return
                except (requests.RequestException, OSError) as exc:
                    self._cleanup_part(part_path)
                    part_path = ""
                    last_error = exc
                    continue

            raise HDHub4uError(str(last_error or "All download mirrors failed."))
        except (HDHub4uError, OSError) as exc:
            self._cleanup_part(part_path)
            self._update_job(job_id, persist=True, status="failed", error=str(exc))

    @staticmethod
    def _filename_from_headers(headers) -> str:
        cd = headers.get("Content-Disposition") or ""
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
        if match:
            return unquote(match.group(1)).strip()
        return ""

    @staticmethod
    def _unique_path(directory: str, filename: str) -> str:
        candidate = os.path.join(directory, filename)
        if not os.path.exists(candidate):
            return candidate
        stem, ext = os.path.splitext(filename)
        idx = 1
        while True:
            alt = os.path.join(directory, f"{stem} ({idx}){ext}")
            if not os.path.exists(alt):
                return alt
            idx += 1

    @staticmethod
    def _cleanup_part(part_path: str):
        if part_path and os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
