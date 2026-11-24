import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime

from extensions.hdhub4u.client import build_media_naming


def _find_binary(name: str) -> str | None:
    candidates = [
        os.path.join(os.path.dirname(sys.executable), name),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bin", name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which(name)


def detect_torrent_engine() -> str | None:
    """Return available CLI torrent downloader ('aria2c' or 'transmission-cli')."""
    if _find_binary("aria2c"):
        return "aria2c"
    if _find_binary("transmission-cli"):
        return "transmission-cli"
    return None


class TorrentDownloadManager:
    """Runs torrent/magnet downloads via local CLI engine and records jobs in shared DownloadManager."""

    def __init__(self, download_manager, x1337_client=None):
        self.download_manager = download_manager
        self.x1337_client = x1337_client
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}

    def start_torrent_download(
        self,
        title: str,
        media_type: str,
        destination_dir: str,
        magnet_or_url: str = "",
        torrent_page_url: str = "",
        category: str = "movies",
    ) -> dict:
        job_id = uuid.uuid4().hex[:10]
        base_dir = os.path.abspath(os.path.expanduser(destination_dir))
        naming = build_media_naming(
            title=title,
            media_type=media_type,
        )
        target_dir = os.path.join(base_dir, naming["folder_name"])
        cancel_event = threading.Event()

        job = {
            "id": job_id,
            "title": title,
            "source_url": magnet_or_url or torrent_page_url,
            "resolved_url": magnet_or_url,
            "media_type": media_type,
            "destination_dir": target_dir,
            "filename": naming["movie_name"],
            "file_path": target_dir,
            "status": "resolving",
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "progress_pct": 0,
            "speed_mbps": 0.0,
            "error": "",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with self.download_manager._lock:
            self.download_manager._jobs[job_id] = job
            self.download_manager._cancel_flags[job_id] = cancel_event
        self.download_manager._persist_job(job)

        worker = threading.Thread(
            target=self._run_torrent,
            args=(
                job_id,
                magnet_or_url,
                torrent_page_url,
                category,
                target_dir,
                cancel_event,
            ),
            daemon=True,
        )
        worker.start()
        return dict(job)

    def cancel_process(self, job_id: str):
        with self._lock:
            proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            proc.terminate()

    def _run_torrent(
        self,
        job_id: str,
        magnet_or_url: str,
        torrent_page_url: str,
        category: str,
        target_dir: str,
        cancel_event: threading.Event,
    ):
        try:
            magnet = magnet_or_url
            if not magnet and torrent_page_url and self.x1337_client is not None:
                details = self.x1337_client.fetch_torrent_details(
                    torrent_page_url, category=category
                )
                magnet = details.get("magnet") or details.get("torrent_file_url") or ""

            if not magnet:
                raise RuntimeError("No magnet link or torrent URL found for this release.")

            engine = detect_torrent_engine()
            if not engine:
                raise RuntimeError(
                    "No torrent CLI engine installed (install aria2c or transmission-cli, e.g. 'brew install aria2')."
                )

            os.makedirs(target_dir, exist_ok=True)
            self.download_manager._update_job(
                job_id,
                persist=True,
                resolved_url=magnet,
                status="downloading",
                error="",
            )

            if engine == "aria2c":
                aria2_bin = _find_binary("aria2c") or "aria2c"
                cmd = [
                    aria2_bin,
                    "--seed-time=0",
                    "--summary-interval=1",
                    "--dir",
                    target_dir,
                    magnet,
                ]
            else:
                trans_bin = _find_binary("transmission-cli") or "transmission-cli"
                cmd = [trans_bin, "-w", target_dir, magnet]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                self._procs[job_id] = proc

            last_output = ""
            if proc.stdout:
                for line in proc.stdout:
                    if cancel_event.is_set():
                        proc.terminate()
                        break
                    clean_line = line.strip()
                    if clean_line:
                        last_output = clean_line
                    pct_match = re.search(r"\((\d{1,3})%\)", clean_line)
                    speed_match = re.search(r"DL:([\d.]+)(KiB|MiB|GiB|B)", clean_line)
                    updates = {}
                    if pct_match:
                        updates["progress_pct"] = min(int(pct_match.group(1)), 100)
                    if speed_match:
                        val = float(speed_match.group(1))
                        unit = speed_match.group(2)
                        mbps = (
                            val
                            if unit == "MiB"
                            else val / 1024
                            if unit == "KiB"
                            else val * 1024
                            if unit == "GiB"
                            else val / (1024 * 1024)
                        )
                        updates["speed_mbps"] = round(mbps, 2)
                    if updates:
                        self.download_manager._update_job(job_id, **updates)

            rc = proc.wait()
            with self._lock:
                self._procs.pop(job_id, None)

            if cancel_event.is_set():
                self.download_manager._update_job(
                    job_id, persist=True, status="cancelled", error="Cancelled"
                )
                return

            if rc != 0:
                raise RuntimeError(
                    f"{engine} exited with code {rc}"
                    + (f": {last_output}" if last_output else "")
                )

            self.download_manager._update_job(
                job_id,
                persist=True,
                status="completed",
                progress_pct=100,
                speed_mbps=0.0,
            )
        except Exception as exc:
            self.download_manager._update_job(
                job_id, persist=True, status="failed", error=str(exc)
            )
