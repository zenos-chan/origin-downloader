import argparse
import importlib
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

_x1337_mod = importlib.import_module("extensions.1337x")
DEFAULT_1337X_BASE_URL = _x1337_mod.DEFAULT_1337X_BASE_URL
TorrentDownloadManager = _x1337_mod.TorrentDownloadManager
X1337Client = _x1337_mod.X1337Client
X1337Error = _x1337_mod.X1337Error
detect_torrent_engine = _x1337_mod.detect_torrent_engine

from extensions.hdhub4u import (
    DEFAULT_BASE_URL as DEFAULT_HDHUB4U_BASE_URL,
    DownloadManager,
    HDHub4uClient,
    HDHub4uError,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_SETTINGS = {
    "site_name": "Origin Admin",
    "site_tagline": "Media & Asset Pipeline Control",
    "support_email": "support@origin-admin.local",
    "maintenance_mode": "0",
    "max_concurrent_downloads": "12",
    "storage_quota_gb": "500",
    "session_timeout_minutes": "60",
    "require_2fa": "0",
    "email_alerts": "1",
    "failed_job_alerts": "1",
    "daily_digest": "0",
    "webhook_url": "https://hooks.origin-admin.local/events",
    "movies_download_path": os.path.join(BASE_DIR, "downloads", "movies"),
    "tv_download_path": os.path.join(BASE_DIR, "downloads", "tv"),
    "anime_download_path": os.path.join(BASE_DIR, "downloads", "anime"),
    "hdhub4u_base_url": DEFAULT_HDHUB4U_BASE_URL,
    "x1337_base_url": DEFAULT_1337X_BASE_URL,
}


def create_app(
    test_config=None,
    path_overrides=None,
    create_dirs=False,
    hdhub_client=None,
    download_manager=None,
    x1337_client=None,
    torrent_manager=None,
):
    app = Flask(__name__, instance_relative_config=True)

    default_db_path = os.path.join(app.instance_path, "origin_admin.db")
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-origin-admin-secret-change-me"),
        DATABASE=default_db_path,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=60),
    )

    if test_config is not None:
        app.config.update(test_config)

    db_dir = os.path.dirname(app.config["DATABASE"])
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    init_db(app, path_overrides=path_overrides, create_dirs=create_dirs)

    hdhub = hdhub_client or HDHub4uClient()
    dl_manager = download_manager or DownloadManager(
        client=hdhub, db_path=app.config["DATABASE"]
    )
    x1337 = x1337_client or X1337Client()
    torrent_mgr = torrent_manager or TorrentDownloadManager(
        download_manager=dl_manager, x1337_client=x1337
    )

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def load_settings():
        db = get_db()
        rows = db.execute("SELECT key, value FROM settings").fetchall()
        settings = dict(DEFAULT_SETTINGS)
        for row in rows:
            settings[row["key"]] = row["value"]
        return settings

    def get_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(32)
        return session["_csrf_token"]

    def validate_csrf():
        token = session.get("_csrf_token")
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or not submitted or not secrets.compare_digest(token, submitted):
            abort(400, description="Invalid or missing CSRF token.")

    @app.before_request
    def load_request_context():
        g.settings = load_settings()
        timeout_mins = _safe_int(g.settings.get("session_timeout_minutes"), 60, 5, 1440)
        app.permanent_session_lifetime = timedelta(minutes=timeout_mins)

        hdhub_url = (g.settings.get("hdhub4u_base_url") or DEFAULT_HDHUB4U_BASE_URL).strip().rstrip("/")
        x1337_url = (g.settings.get("x1337_base_url") or DEFAULT_1337X_BASE_URL).strip().rstrip("/")
        if hdhub_url:
            hdhub.base_url = hdhub_url
        if x1337_url:
            x1337.base_url = x1337_url

        admin_id = session.get("admin_id")
        g.admin = None
        if admin_id is not None:
            db = get_db()
            g.admin = db.execute(
                "SELECT id, username, display_name, email, role, updated_at FROM admins WHERE id = ?",
                (admin_id,),
            ).fetchone()
            if g.admin is None:
                session.clear()

    @app.context_processor
    def inject_globals():
        all_jobs = dl_manager.list_jobs()
        active_transfers_count = sum(
            1 for j in all_jobs if j["status"] in ("resolving", "downloading")
        )
        recent_alerts = []
        for job in all_jobs[:4]:
            if job["status"] == "completed":
                recent_alerts.append(
                    {
                        "title": f"Completed: {job['filename'] or job['title']}",
                        "detail": f"Saved to {job['destination_dir']}",
                        "icon": "fa-check",
                        "style": "bg-emerald-50 text-emerald-600",
                    }
                )
            elif job["status"] == "failed":
                recent_alerts.append(
                    {
                        "title": f"Failed: {job['filename'] or job['title']}",
                        "detail": job["error"] or "Transfer error",
                        "icon": "fa-triangle-exclamation",
                        "style": "bg-rose-50 text-rose-600",
                    }
                )
            elif job["status"] in ("resolving", "downloading"):
                recent_alerts.append(
                    {
                        "title": f"Downloading: {job['filename'] or job['title']}",
                        "detail": f"{job['progress_pct']}% · {job['speed_mbps']} MB/s",
                        "icon": "fa-cloud-arrow-down",
                        "style": "bg-sky-50 text-sky-600",
                    }
                )
        return {
            "site_settings": getattr(g, "settings", DEFAULT_SETTINGS),
            "current_admin": getattr(g, "admin", None),
            "csrf_token": get_csrf_token,
            "recent_alerts": recent_alerts,
            "active_transfers_count": active_transfers_count,
        }

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.admin is None:
                flash("Please sign in to access the admin console.", "warning")
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    @app.route("/")
    def index():
        if g.admin is not None:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.admin is not None:
            return redirect(url_for("dashboard"))

        login_error = False
        entered_username = ""

        if request.method == "POST":
            validate_csrf()
            entered_username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            remember = request.form.get("remember") == "on"

            db = get_db()
            admin = db.execute(
                "SELECT * FROM admins WHERE username = ? OR email = ?",
                (entered_username, entered_username),
            ).fetchone()

            if admin and check_password_hash(admin["password_hash"], password):
                session.clear()
                session["admin_id"] = admin["id"]
                session.permanent = remember
                get_csrf_token()
                flash(f"Welcome back, {admin['display_name']}!", "success")

                next_url = request.args.get("next") or request.form.get("next")
                if next_url and _is_safe_redirect(next_url):
                    return redirect(next_url)
                return redirect(url_for("dashboard"))

            login_error = True
            flash("Invalid username/email or password.", "error")

        return render_template(
            "login.html",
            login_error=login_error,
            entered_username=entered_username,
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        validate_csrf()
        session.clear()
        flash("You have been signed out securely.", "info")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        jobs = dl_manager.list_jobs()
        quota_gb = _safe_int(g.settings.get("storage_quota_gb"), 500, 10, 10000)
        max_concurrent = _safe_int(g.settings.get("max_concurrent_downloads"), 12, 1, 100)

        media_dirs = [
            g.settings.get("movies_download_path", DEFAULT_SETTINGS["movies_download_path"]),
            g.settings.get("tv_download_path", DEFAULT_SETTINGS["tv_download_path"]),
            g.settings.get("anime_download_path", DEFAULT_SETTINGS["anime_download_path"]),
        ]
        used_bytes = sum(_dir_size_bytes(path) for path in media_dirs)
        used_gb = round(used_bytes / (1024 ** 3), 2)
        storage_pct = min(round((used_gb / quota_gb) * 100), 100) if quota_gb else 0

        active_count = sum(1 for j in jobs if j["status"] in ("resolving", "downloading"))
        completed_count = sum(1 for j in jobs if j["status"] == "completed")
        failed_count = sum(1 for j in jobs if j["status"] == "failed")
        finished_count = completed_count + failed_count
        success_rate = (
            round((completed_count / finished_count) * 100, 1)
            if finished_count > 0
            else 100.0
        )
        queue_pct = min(round((active_count / max_concurrent) * 100), 100) if max_concurrent else 0

        disk_pct, disk_label = _disk_usage_summary(media_dirs)
        cpu_pct = _system_cpu_load_pct()
        folders_ready = sum(
            1 for p in media_dirs if os.path.isdir(os.path.expanduser(p))
        )

        kpis = [
            {
                "label": "Total Downloads",
                "value": len(jobs),
                "suffix": "",
                "decimals": 0,
                "delta": f"{completed_count} completed" if jobs else "No downloads yet",
                "trend": "up" if completed_count > 0 else "neutral",
                "icon": "fa-cloud-arrow-down",
                "gradient": "from-indigo-500 to-violet-600",
                "bg_soft": "bg-indigo-50 text-indigo-600",
            },
            {
                "label": "Active Transfers",
                "value": active_count,
                "suffix": f" / {max_concurrent}",
                "decimals": 0,
                "delta": "Running now" if active_count else "Queue idle",
                "trend": "neutral",
                "icon": "fa-bolt",
                "gradient": "from-sky-500 to-cyan-500",
                "bg_soft": "bg-sky-50 text-sky-600",
            },
            {
                "label": "Storage Used",
                "value": used_gb,
                "suffix": " GB",
                "decimals": 2,
                "delta": f"{storage_pct}% of {quota_gb} GB quota",
                "trend": "neutral",
                "icon": "fa-hard-drive",
                "gradient": "from-amber-500 to-orange-500",
                "bg_soft": "bg-amber-50 text-amber-600",
            },
            {
                "label": "Success Rate",
                "value": success_rate,
                "suffix": "%",
                "decimals": 1,
                "delta": (
                    f"{failed_count} failed" if failed_count else "Zero failures"
                ),
                "trend": "up" if failed_count == 0 else "neutral",
                "icon": "fa-circle-check",
                "gradient": "from-emerald-500 to-teal-500",
                "bg_soft": "bg-emerald-50 text-emerald-600",
            },
        ]

        chart_datasets = _build_chart_datasets(jobs)

        system_metrics = [
            {
                "label": "Media Quota Used",
                "value": f"{used_gb:.2f} / {quota_gb} GB",
                "pct": storage_pct,
                "color": "bg-indigo-600",
            },
            {
                "label": "Concurrent Queue",
                "value": f"{active_count} / {max_concurrent} slots",
                "pct": queue_pct,
                "color": "bg-sky-500",
            },
            {
                "label": "Host Disk Usage",
                "value": disk_label,
                "pct": disk_pct,
                "color": "bg-amber-500",
            },
            {
                "label": "System CPU Load",
                "value": f"{cpu_pct}% · {folders_ready}/3 folders ready",
                "pct": cpu_pct,
                "color": "bg-emerald-500",
            },
        ]

        transfers = [_job_to_transfer_row(job) for job in jobs]

        return render_template(
            "dashboard.html",
            active_page="dashboard",
            kpis=kpis,
            chart_bars=chart_datasets["7d"],
            chart_datasets=chart_datasets,
            transfers=transfers,
            system_metrics=system_metrics,
        )

    @app.route("/movies")
    @login_required
    def movies():
        page = _safe_int(request.args.get("page"), 1, 1, 50)
        search_query = request.args.get("q", "").strip()
        media_filter = request.args.get("type", "all").strip().lower()
        if media_filter not in ("all", "movie", "tv", "anime"):
            media_filter = "all"

        items = []
        fetch_error = ""
        try:
            items = hdhub.fetch_recent(page=page, search=search_query)
            if media_filter != "all":
                items = [item for item in items if item["media_type"] == media_filter]
        except HDHub4uError as exc:
            fetch_error = str(exc)

        media_folders = {
            "movie": g.settings.get("movies_download_path", DEFAULT_SETTINGS["movies_download_path"]),
            "tv": g.settings.get("tv_download_path", DEFAULT_SETTINGS["tv_download_path"]),
            "anime": g.settings.get("anime_download_path", DEFAULT_SETTINGS["anime_download_path"]),
        }

        return render_template(
            "movies.html",
            active_page="movies",
            items=items,
            page=page,
            search_query=search_query,
            media_filter=media_filter,
            fetch_error=fetch_error,
            jobs=dl_manager.list_jobs(),
            media_folders=media_folders,
        )

    @app.route("/api/hdhub4u/details")
    @login_required
    def api_hdhub4u_details():
        movie_url = request.args.get("url", "").strip()
        if not movie_url:
            return jsonify({"error": "Missing movie URL."}), 400
        try:
            details = hdhub.fetch_movie_details(movie_url)
            return jsonify(details)
        except HDHub4uError as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/hdhub4u/resolve", methods=["POST"])
    @login_required
    def api_hdhub4u_resolve():
        validate_csrf()
        payload = request.get_json(silent=True) or {}
        source_url = (payload.get("url") or "").strip()
        title = (payload.get("title") or "video").strip()
        if not source_url:
            return jsonify({"error": "Missing source URL."}), 400
        try:
            mirrors = hdhub.resolve_download_links(source_url, fallback_title=title)
            return jsonify({"mirrors": mirrors})
        except HDHub4uError as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/hdhub4u/download", methods=["POST"])
    @login_required
    def api_hdhub4u_download():
        validate_csrf()
        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "HDHub4u Download").strip()
        source_url = (payload.get("url") or "").strip()
        media_type = (payload.get("media_type") or "movie").strip().lower()
        filename = (payload.get("filename") or "").strip()
        quality_label = (payload.get("quality_label") or "").strip()

        if not source_url:
            return jsonify({"error": "Missing download URL."}), 400
        if media_type not in ("movie", "tv", "anime"):
            return jsonify({"error": "Invalid media type."}), 400

        folder_map = {
            "movie": g.settings.get("movies_download_path", DEFAULT_SETTINGS["movies_download_path"]),
            "tv": g.settings.get("tv_download_path", DEFAULT_SETTINGS["tv_download_path"]),
            "anime": g.settings.get("anime_download_path", DEFAULT_SETTINGS["anime_download_path"]),
        }
        dest_dir = folder_map[media_type]
        job = dl_manager.start_download(
            title=title,
            source_url=source_url,
            media_type=media_type,
            destination_dir=dest_dir,
            filename=filename,
            quality_label=quality_label,
        )
        return jsonify({"job": job}), 202

    @app.route("/torrents")
    @login_required
    def torrents():
        category = request.args.get("cat", "movies").strip().lower()
        if category not in ("movies", "tv", "anime"):
            category = "movies"
        search_query = request.args.get("q", "").strip()

        items = []
        fetch_error = ""
        try:
            items = x1337.fetch_popular(category=category, search=search_query)
        except X1337Error as exc:
            fetch_error = str(exc)

        media_folders = {
            "movie": g.settings.get("movies_download_path", DEFAULT_SETTINGS["movies_download_path"]),
            "tv": g.settings.get("tv_download_path", DEFAULT_SETTINGS["tv_download_path"]),
            "anime": g.settings.get("anime_download_path", DEFAULT_SETTINGS["anime_download_path"]),
        }

        return render_template(
            "torrents.html",
            active_page="torrents",
            items=items,
            category=category,
            search_query=search_query,
            fetch_error=fetch_error,
            torrent_engine=detect_torrent_engine(),
            x1337_base_url=g.settings.get("x1337_base_url", DEFAULT_1337X_BASE_URL),
            media_folders=media_folders,
            jobs=dl_manager.list_jobs(),
        )

    @app.route("/api/1337x/details")
    @login_required
    def api_1337x_details():
        torrent_url = request.args.get("url", "").strip()
        category = request.args.get("category", "movies").strip().lower()
        if not torrent_url:
            return jsonify({"error": "Missing torrent URL."}), 400
        try:
            details = x1337.fetch_torrent_details(torrent_url, category=category)
            return jsonify(details)
        except X1337Error as exc:
            return jsonify({"error": str(exc)}), 502

    @app.route("/api/1337x/download", methods=["POST"])
    @login_required
    def api_1337x_download():
        validate_csrf()
        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "1337x Torrent").strip()
        magnet = (payload.get("magnet") or "").strip()
        torrent_page_url = (payload.get("torrent_page_url") or "").strip()
        media_type = (payload.get("media_type") or "movie").strip().lower()
        category = (payload.get("category") or "movies").strip().lower()

        if not magnet and not torrent_page_url:
            return jsonify({"error": "Missing magnet link or torrent URL."}), 400
        if media_type not in ("movie", "tv", "anime"):
            return jsonify({"error": "Invalid media type."}), 400

        folder_map = {
            "movie": g.settings.get("movies_download_path", DEFAULT_SETTINGS["movies_download_path"]),
            "tv": g.settings.get("tv_download_path", DEFAULT_SETTINGS["tv_download_path"]),
            "anime": g.settings.get("anime_download_path", DEFAULT_SETTINGS["anime_download_path"]),
        }
        job = torrent_mgr.start_torrent_download(
            title=title,
            media_type=media_type,
            destination_dir=folder_map[media_type],
            magnet_or_url=magnet,
            torrent_page_url=torrent_page_url,
            category=category,
        )
        return jsonify({"job": job}), 202

    @app.route("/api/downloads")
    @login_required
    def api_downloads():
        return jsonify({"jobs": dl_manager.list_jobs()})

    @app.route("/api/downloads/<job_id>/cancel", methods=["POST"])
    @login_required
    def api_cancel_download(job_id):
        validate_csrf()
        cancelled = dl_manager.cancel_job(job_id)
        if not cancelled:
            return jsonify({"error": "Job not found or already finished."}), 404
        torrent_mgr.cancel_process(job_id)
        return jsonify({"cancelled": True})

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        active_tab = request.args.get("tab", "general")
        if active_tab not in ("general", "paths", "sources", "security", "notifications"):
            active_tab = "general"

        def build_path_statuses(current_settings):
            return {
                key: os.path.isdir(os.path.expanduser(current_settings.get(key, "")))
                for key in ("movies_download_path", "tv_download_path", "anime_download_path")
            }

        def render_settings_page(tab_name):
            return render_template(
                "settings.html",
                active_page="settings",
                active_tab=tab_name,
                path_statuses=build_path_statuses(g.settings),
            )

        if request.method == "POST":
            validate_csrf()
            section = request.form.get("section", "general")
            db = get_db()

            if section == "paths":
                active_tab = "paths"
                movies_path = request.form.get("movies_download_path", "").strip()
                tv_path = request.form.get("tv_download_path", "").strip()
                anime_path = request.form.get("anime_download_path", "").strip()
                create_dirs = request.form.get("create_missing_dirs") == "on"

                path_fields = [
                    ("Movies", movies_path),
                    ("TV Shows", tv_path),
                    ("Anime", anime_path),
                ]
                for label, path_val in path_fields:
                    if not path_val or "\x00" in path_val:
                        flash(f"{label} folder path must be a valid non-empty path.", "error")
                        return render_settings_page(active_tab)

                if create_dirs:
                    for label, path_val in path_fields:
                        resolved_path = os.path.abspath(os.path.expanduser(path_val))
                        try:
                            os.makedirs(resolved_path, exist_ok=True)
                        except OSError as exc:
                            flash(
                                f"Could not create {label} folder ({resolved_path}): {exc.strerror or exc}. "
                                "Choose a writable location such as ~/Downloads or inside the project folder.",
                                "error",
                            )
                            return render_settings_page(active_tab)

                _upsert_settings(
                    db,
                    {
                        "movies_download_path": movies_path,
                        "tv_download_path": tv_path,
                        "anime_download_path": anime_path,
                    },
                )
                db.commit()
                flash("Download folder paths saved successfully.", "success")
                return redirect(url_for("settings", tab="paths"))

            if section == "sources":
                active_tab = "sources"
                hdhub4u_url = request.form.get("hdhub4u_base_url", "").strip().rstrip("/")
                x1337_url = request.form.get("x1337_base_url", "").strip().rstrip("/")

                for label, raw_url in (("HDHub4u", hdhub4u_url), ("1337x", x1337_url)):
                    parsed = urlparse(raw_url)
                    if parsed.scheme not in ("http", "https") or not parsed.netloc:
                        flash(
                            f"{label} Base URL must be a valid http:// or https:// URL.",
                            "error",
                        )
                        return render_settings_page(active_tab)

                _upsert_settings(
                    db,
                    {
                        "hdhub4u_base_url": hdhub4u_url,
                        "x1337_base_url": x1337_url,
                    },
                )
                db.commit()
                hdhub.base_url = hdhub4u_url
                x1337.base_url = x1337_url
                flash("Source base URLs saved successfully.", "success")
                return redirect(url_for("settings", tab="sources"))

            if section == "general":
                active_tab = "general"
                site_name = request.form.get("site_name", "").strip()
                site_tagline = request.form.get("site_tagline", "").strip()
                support_email = request.form.get("support_email", "").strip()
                maintenance_mode = "1" if request.form.get("maintenance_mode") == "on" else "0"
                max_concurrent = request.form.get("max_concurrent_downloads", "").strip()
                storage_quota = request.form.get("storage_quota_gb", "").strip()

                if not site_name:
                    flash("Application name cannot be empty.", "error")
                    return render_settings_page(active_tab)

                if not support_email or "@" not in support_email:
                    flash("Please enter a valid support email address.", "error")
                    return render_settings_page(active_tab)

                try:
                    max_c_val = int(max_concurrent)
                    quota_val = int(storage_quota)
                    if not (1 <= max_c_val <= 100):
                        raise ValueError("Max concurrent downloads must be between 1 and 100.")
                    if not (10 <= quota_val <= 10000):
                        raise ValueError("Storage quota must be between 10 GB and 10,000 GB.")
                except ValueError as exc:
                    flash(str(exc), "error")
                    return render_settings_page(active_tab)

                _upsert_settings(
                    db,
                    {
                        "site_name": site_name,
                        "site_tagline": site_tagline,
                        "support_email": support_email,
                        "maintenance_mode": maintenance_mode,
                        "max_concurrent_downloads": str(max_c_val),
                        "storage_quota_gb": str(quota_val),
                    },
                )
                db.commit()
                flash("General settings saved successfully.", "success")
                return redirect(url_for("settings", tab="general"))

            if section == "security":
                active_tab = "security"
                display_name = request.form.get("display_name", "").strip()
                email = request.form.get("email", "").strip()
                session_timeout = request.form.get("session_timeout_minutes", "").strip()
                require_2fa = "1" if request.form.get("require_2fa") == "on" else "0"

                current_password = request.form.get("current_password", "")
                new_password = request.form.get("new_password", "")
                confirm_password = request.form.get("confirm_password", "")

                if not display_name:
                    flash("Display name cannot be empty.", "error")
                    return render_settings_page(active_tab)

                if not email or "@" not in email:
                    flash("Please provide a valid admin email address.", "error")
                    return render_settings_page(active_tab)

                try:
                    timeout_val = int(session_timeout)
                    if not (5 <= timeout_val <= 1440):
                        raise ValueError("Session timeout must be between 5 and 1440 minutes.")
                except ValueError as exc:
                    flash(str(exc), "error")
                    return render_settings_page(active_tab)

                admin_row = db.execute(
                    "SELECT * FROM admins WHERE id = ?",
                    (g.admin["id"],),
                ).fetchone()

                new_hash = admin_row["password_hash"]
                if new_password or current_password or confirm_password:
                    if not check_password_hash(admin_row["password_hash"], current_password):
                        flash("Current password is incorrect.", "error")
                        return render_settings_page(active_tab)
                    if len(new_password) < 8:
                        flash("New password must be at least 8 characters long.", "error")
                        return render_settings_page(active_tab)
                    if new_password != confirm_password:
                        flash("New password and confirmation do not match.", "error")
                        return render_settings_page(active_tab)
                    new_hash = generate_password_hash(new_password)

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.execute(
                    """
                    UPDATE admins
                    SET display_name = ?, email = ?, password_hash = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (display_name, email, new_hash, now_str, g.admin["id"]),
                )
                _upsert_settings(
                    db,
                    {
                        "session_timeout_minutes": str(timeout_val),
                        "require_2fa": require_2fa,
                    },
                )
                db.commit()
                flash("Security & account settings updated.", "success")
                return redirect(url_for("settings", tab="security"))

            if section == "notifications":
                active_tab = "notifications"
                email_alerts = "1" if request.form.get("email_alerts") == "on" else "0"
                failed_job_alerts = "1" if request.form.get("failed_job_alerts") == "on" else "0"
                daily_digest = "1" if request.form.get("daily_digest") == "on" else "0"
                webhook_url = request.form.get("webhook_url", "").strip()

                if webhook_url and not (
                    webhook_url.startswith("http://") or webhook_url.startswith("https://")
                ):
                    flash("Webhook URL must start with http:// or https://.", "error")
                    return render_settings_page(active_tab)

                _upsert_settings(
                    db,
                    {
                        "email_alerts": email_alerts,
                        "failed_job_alerts": failed_job_alerts,
                        "daily_digest": daily_digest,
                        "webhook_url": webhook_url,
                    },
                )
                db.commit()
                flash("Notification preferences saved.", "success")
                return redirect(url_for("settings", tab="notifications"))

        return render_settings_page(active_tab)

    return app


def init_db(app, path_overrides=None, create_dirs=False):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Super Admin',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        existing_admin = conn.execute("SELECT id FROM admins LIMIT 1").fetchone()
        if existing_admin is None:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO admins (username, display_name, email, password_hash, role, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "admin",
                    "Alex Morgan",
                    "admin@origin-admin.local",
                    generate_password_hash("admin123"),
                    "Super Admin",
                    now_str,
                ),
            )

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

        if path_overrides:
            clean_overrides = {}
            for key in ("movies_download_path", "tv_download_path", "anime_download_path"):
                raw_val = path_overrides.get(key)
                if raw_val is not None:
                    cleaned = raw_val.strip()
                    if not cleaned or "\x00" in cleaned:
                        raise ValueError(f"Invalid path value for {key}.")
                    if create_dirs:
                        os.makedirs(os.path.abspath(os.path.expanduser(cleaned)), exist_ok=True)
                    clean_overrides[key] = cleaned
            if clean_overrides:
                _upsert_settings(conn, clean_overrides)

        conn.commit()
    finally:
        conn.close()


def _upsert_settings(db, pairs):
    for key, value in pairs.items():
        db.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _safe_int(value, default, min_val, max_val):
    try:
        parsed = int(value)
        if min_val <= parsed <= max_val:
            return parsed
    except (TypeError, ValueError):
        pass
    return default


def _is_safe_redirect(target):
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/")


def _dir_size_bytes(path: str) -> int:
    expanded = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(expanded):
        return 0
    total = 0
    for root, _, files in os.walk(expanded):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                pass
    return total


def _disk_usage_summary(paths: list[str]) -> tuple[int, str]:
    probe = BASE_DIR
    for p in paths:
        expanded = os.path.abspath(os.path.expanduser(p))
        if os.path.exists(expanded):
            probe = expanded
            break
    try:
        usage = shutil.disk_usage(probe)
        used_gb = round(usage.used / (1024 ** 3), 1)
        total_gb = round(usage.total / (1024 ** 3), 1)
        pct = min(round((usage.used / usage.total) * 100), 100) if usage.total else 0
        return pct, f"{used_gb} / {total_gb} GB"
    except OSError:
        return 0, "Unavailable"


def _system_cpu_load_pct() -> int:
    try:
        load1 = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return min(max(round((load1 / cores) * 100), 1), 100)
    except (AttributeError, OSError):
        return 0


def _format_size(num_bytes: int) -> str:
    if not num_bytes:
        return "—"
    gb = num_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{num_bytes / (1024 ** 2):.1f} MB"


def _job_to_transfer_row(job: dict) -> dict:
    icon_map = {
        "movie": "fa-film",
        "tv": "fa-tv",
        "anime": "fa-wand-magic-sparkles",
    }
    raw_status = job.get("status", "")
    display_status = "active" if raw_status in ("resolving", "downloading") else raw_status
    total_or_dl = job.get("total_bytes") or job.get("downloaded_bytes") or 0
    return {
        "id": job["id"],
        "short_id": f"JOB-{job['id'][:6].upper()}",
        "name": job.get("filename") or job.get("title") or "Untitled",
        "source": job.get("media_type", "movie").upper(),
        "destination_dir": job.get("destination_dir", ""),
        "size": _format_size(total_or_dl),
        "speed": f"{job['speed_mbps']} MB/s" if job.get("speed_mbps") and display_status == "active" else "—",
        "progress": job.get("progress_pct", 0),
        "status": display_status,
        "time": job.get("created_at", ""),
        "error": job.get("error", ""),
        "icon": icon_map.get(job.get("media_type"), "fa-file"),
    }


def _build_chart_datasets(jobs: list[dict]) -> dict:
    today = datetime.now().date()
    day_counts = {}
    for job in jobs:
        raw_ts = (job.get("created_at") or "")[:10]
        if len(raw_ts) == 10:
            day_counts[raw_ts] = day_counts.get(raw_ts, 0) + 1

    # Last 7 calendar days
    days_7 = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    raw_7 = [(d.strftime("%a"), day_counts.get(d.isoformat(), 0)) for d in days_7]
    max_7 = max((c for _, c in raw_7), default=0)
    chart_7d = [
        {
            "label": label,
            "val": max(round((count / max_7) * 100), 14) if max_7 > 0 and count > 0 else 4,
            "count": str(count),
            "empty": count == 0,
        }
        for label, count in raw_7
    ]

    # Last 30 days grouped into 6 x 5-day buckets
    buckets_30 = []
    for bucket_idx in range(6):
        start_offset = 29 - bucket_idx * 5
        end_offset = max(start_offset - 4, 0)
        bucket_dates = [
            today - timedelta(days=off)
            for off in range(start_offset, end_offset - 1, -1)
        ]
        bucket_sum = sum(day_counts.get(d.isoformat(), 0) for d in bucket_dates)
        label = (
            "Now"
            if bucket_idx == 5
            else bucket_dates[0].strftime("%b %d")
        )
        buckets_30.append((label, bucket_sum))

    max_30 = max((c for _, c in buckets_30), default=0)
    chart_30d = [
        {
            "label": label,
            "val": max(round((count / max_30) * 100), 14) if max_30 > 0 and count > 0 else 4,
            "count": str(count),
            "empty": count == 0,
        }
        for label, count in buckets_30
    ]

    return {"7d": chart_7d, "30d": chart_30d}


def parse_cli_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the Origin Admin Flask web application."
    )
    parser.add_argument(
        "--movie-path",
        "--movies-path",
        dest="movies_download_path",
        help="Destination folder path for movie downloads.",
    )
    parser.add_argument(
        "--tv-path",
        dest="tv_download_path",
        help="Destination folder path for TV show downloads.",
    )
    parser.add_argument(
        "--anime-path",
        dest="anime_download_path",
        help="Destination folder path for anime downloads.",
    )
    parser.add_argument(
        "--create-dirs",
        action="store_true",
        help="Create the specified download directories on startup if they do not exist.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to listen on (default: 5000).",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Disable Flask debug mode.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_cli_args(argv)
    path_overrides = {
        key: getattr(args, key)
        for key in ("movies_download_path", "tv_download_path", "anime_download_path")
        if getattr(args, key) is not None
    }
    cli_app = create_app(
        path_overrides=path_overrides or None,
        create_dirs=args.create_dirs,
    )
    cli_app.run(debug=not args.no_debug, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
else:
    app = create_app()
