import re
import pytest
from app import create_app, parse_cli_args


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test_admin.db"
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(db_path),
            "SECRET_KEY": "test-secret-key",
        }
    )
    with app.test_client() as test_client:
        yield test_client


def extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match is not None, "CSRF token not found in HTML"
    return match.group(1)


def login_as_admin(client, username="admin", password="admin123"):
    page = client.get("/login")
    token = extract_csrf(page.data.decode())
    return client.post(
        "/login",
        data={"csrf_token": token, "username": username, "password": password},
        follow_redirects=True,
    )


def test_unauthenticated_redirects_to_login(client):
    for path in ("/", "/dashboard", "/settings"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


def test_login_page_contains_tailwind_and_fontawesome(client):
    resp = client.get("/login")
    html = resp.data.decode()
    assert resp.status_code == 200
    assert "cdn.tailwindcss.com" in html
    assert "font-awesome" in html
    assert "Sign in to Console" in html


def test_invalid_login_rejected(client):
    page = client.get("/login")
    token = extract_csrf(page.data.decode())
    resp = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "wrong-password"},
        follow_redirects=True,
    )
    html = resp.data.decode()
    assert resp.status_code == 200
    assert "Invalid username/email or password." in html
    assert "animate-shake" in html

    dash = client.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 302
    assert "/login" in dash.headers["Location"]


def test_valid_login_and_dashboard_render(client):
    resp = login_as_admin(client)
    html = resp.data.decode()
    assert resp.status_code == 200
    assert "Dashboard Overview" in html
    assert "Total Downloads" in html
    assert "Recent Transfers" in html
    assert "No transfers recorded yet" in html
    assert "ubuntu-24.04.1-server-amd64.iso" not in html


def test_csrf_required_on_post(client):
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 400


def test_settings_general_persistence(client):
    login_as_admin(client)
    page = client.get("/settings")
    token = extract_csrf(page.data.decode())

    resp = client.post(
        "/settings?tab=general",
        data={
            "csrf_token": token,
            "section": "general",
            "site_name": "Origin Pro",
            "site_tagline": "High-Speed Mirror Hub",
            "support_email": "ops@origin.test",
            "max_concurrent_downloads": "24",
            "storage_quota_gb": "1024",
            "maintenance_mode": "on",
        },
        follow_redirects=True,
    )
    html = resp.data.decode()
    assert resp.status_code == 200
    assert "General settings saved successfully." in html
    assert "Origin Pro" in html
    assert "Maintenance Mode On" in html

    dash = client.get("/dashboard").data.decode()
    assert "Origin Pro Control Center" in dash
    assert "1024 GB" in dash


def test_settings_notifications_persistence(client):
    login_as_admin(client)
    page = client.get("/settings?tab=notifications")
    token = extract_csrf(page.data.decode())

    resp = client.post(
        "/settings?tab=notifications",
        data={
            "csrf_token": token,
            "section": "notifications",
            "email_alerts": "on",
            "daily_digest": "on",
            "webhook_url": "https://hooks.example.com/origin",
        },
        follow_redirects=True,
    )
    html = resp.data.decode()
    assert resp.status_code == 200
    assert "Notification preferences saved." in html
    assert "https://hooks.example.com/origin" in html


def test_settings_security_password_change_and_relogin(client):
    login_as_admin(client)
    page = client.get("/settings?tab=security")
    token = extract_csrf(page.data.decode())

    resp = client.post(
        "/settings?tab=security",
        data={
            "csrf_token": token,
            "section": "security",
            "display_name": "Jordan Lee",
            "email": "jordan@origin.test",
            "session_timeout_minutes": "120",
            "require_2fa": "on",
            "current_password": "admin123",
            "new_password": "NewStrongPassword!9",
            "confirm_password": "NewStrongPassword!9",
        },
        follow_redirects=True,
    )
    html = resp.data.decode()
    assert resp.status_code == 200
    assert "Security &amp; account settings updated." in html
    assert "Jordan Lee" in html

    # Logout and verify old password fails while new password succeeds
    token = extract_csrf(html)
    logout_resp = client.post("/logout", data={"csrf_token": token}, follow_redirects=True)
    assert "You have been signed out securely." in logout_resp.data.decode()

    failed_old = login_as_admin(client, password="admin123")
    assert "Invalid username/email or password." in failed_old.data.decode()

    ok_new = login_as_admin(client, password="NewStrongPassword!9")
    assert "Dashboard Overview" in ok_new.data.decode()


def test_settings_download_paths_persistence_and_creation(client, tmp_path):
    login_as_admin(client)
    page = client.get("/settings?tab=paths")
    html = page.data.decode()
    assert "Media Download Paths" in html
    token = extract_csrf(html)

    movies_dir = tmp_path / "media" / "Movies"
    tv_dir = tmp_path / "media" / "TV"
    anime_dir = tmp_path / "media" / "Anime"

    # Empty path should be rejected
    bad_resp = client.post(
        "/settings?tab=paths",
        data={
            "csrf_token": token,
            "section": "paths",
            "movies_download_path": "",
            "tv_download_path": str(tv_dir),
            "anime_download_path": str(anime_dir),
        },
        follow_redirects=True,
    )
    assert "Movies folder path must be a valid non-empty path." in bad_resp.data.decode()

    # Valid paths with auto-creation enabled
    token = extract_csrf(bad_resp.data.decode())
    resp = client.post(
        "/settings?tab=paths",
        data={
            "csrf_token": token,
            "section": "paths",
            "movies_download_path": str(movies_dir),
            "tv_download_path": str(tv_dir),
            "anime_download_path": str(anime_dir),
            "create_missing_dirs": "on",
        },
        follow_redirects=True,
    )
    body = resp.data.decode()
    assert resp.status_code == 200
    assert "Download folder paths saved successfully." in body
    assert str(movies_dir) in body
    assert str(tv_dir) in body
    assert str(anime_dir) in body
    assert "Directory ready" in body
    assert movies_dir.is_dir()
    assert tv_dir.is_dir()
    assert anime_dir.is_dir()


def test_cli_flags_override_download_paths_and_create_dirs(tmp_path):
    movies_dir = tmp_path / "cli_movies"
    tv_dir = tmp_path / "cli_tv"
    anime_dir = tmp_path / "cli_anime"

    args = parse_cli_args(
        [
            "--movie-path",
            str(movies_dir),
            "--tv-path",
            str(tv_dir),
            "--anime-path",
            str(anime_dir),
            "--create-dirs",
            "--port",
            "5055",
        ]
    )
    assert args.movies_download_path == str(movies_dir)
    assert args.tv_download_path == str(tv_dir)
    assert args.anime_download_path == str(anime_dir)
    assert args.create_dirs is True
    assert args.port == 5055

    app = create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(tmp_path / "cli_test.db"),
            "SECRET_KEY": "test-secret-key",
        },
        path_overrides={
            "movies_download_path": args.movies_download_path,
            "tv_download_path": args.tv_download_path,
            "anime_download_path": args.anime_download_path,
        },
        create_dirs=args.create_dirs,
    )

    assert movies_dir.is_dir()
    assert tv_dir.is_dir()
    assert anime_dir.is_dir()

    with app.test_client() as test_client:
        login_as_admin(test_client)
        body = test_client.get("/settings?tab=paths").data.decode()
        assert str(movies_dir) in body
        assert str(tv_dir) in body
        assert str(anime_dir) in body
        assert "Directory ready" in body


