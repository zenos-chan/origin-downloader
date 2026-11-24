import importlib
import os
import subprocess
import time
from unittest.mock import Mock

from app import create_app
from tests.test_app import extract_csrf, login_as_admin

x1337_mod = importlib.import_module("extensions.1337x")
x1337_torrent_mod = importlib.import_module("extensions.1337x.torrent")
X1337Client = x1337_mod.X1337Client
X1337Error = x1337_mod.X1337Error
parse_1337x_popular = x1337_mod.parse_1337x_popular
parse_1337x_details = x1337_mod.parse_1337x_details

SAMPLE_1337X_POPULAR_HTML = """
<table class="table-list">
  <tbody>
    <tr>
      <td class="coll-1 name">
        <a href="/sub/54/0/"><i class="flaticon-hd"></i></a>
        <a href="/torrent/612345/Dune-Part-Two-2024-1080p-WEB-DL/">Dune Part Two (2024) 1080p WEB-DL x264</a>
      </td>
      <td class="coll-2 seeds">1,450</td>
      <td class="coll-3 leeches">230</td>
      <td class="coll-date">12 hours ago</td>
      <td class="coll-4 size mob-uploader">2.4 GB<span class="seeds">1450</span></td>
      <td class="coll-5 uploader"><a href="/user/YTS/">YTS</a></td>
    </tr>
  </tbody>
</table>
"""

SAMPLE_1337X_DETAIL_HTML = """
<div class="box-info-heading"><h1>Dune Part Two (2024) 1080p WEB-DL x264</h1></div>
<div class="torrent-detail-info">
  <ul class="list">
    <li><strong>Total size</strong><span>2.4 GB</span></li>
    <li><strong>Seeders</strong><span>1450</span></li>
    <li><strong>Leechers</strong><span>230</span></li>
  </ul>
</div>
<a href="magnet:?xt=urn:btih:0123456789ABCDEF&dn=Dune.Part.Two.2024">Magnet Download</a>
<a href="https://itorrents.org/torrent/0123456789ABCDEF.torrent">Torrent</a>
"""


def test_parse_1337x_popular_and_details():
    items = parse_1337x_popular(
        SAMPLE_1337X_POPULAR_HTML,
        category="movies",
        base_url="https://1337x.to",
    )
    assert len(items) == 1
    assert items[0]["title"] == "Dune Part Two (2024) 1080p WEB-DL x264"
    assert items[0]["url"] == "https://1337x.to/torrent/612345/Dune-Part-Two-2024-1080p-WEB-DL/"
    assert items[0]["seeders"] == 1450
    assert items[0]["leechers"] == 230
    assert items[0]["size"] == "2.4 GB"
    assert items[0]["media_type"] == "movie"
    assert items[0]["year"] == "2024"

    details = parse_1337x_details(
        SAMPLE_1337X_DETAIL_HTML,
        page_url=items[0]["url"],
        category="movies",
        base_url="https://1337x.to",
    )
    assert details["magnet"].startswith("magnet:?xt=urn:btih:0123456789ABCDEF")
    assert details["torrent_file_url"].endswith(".torrent")
    assert details["seeders"] == 1450


def test_1337x_detects_cloudflare_challenge(monkeypatch):
    client = X1337Client(base_url="https://1337x.st")

    class FakeChallengeResp:
        status_code = 403
        text = "<html><title>Just a moment...</title><script src='https://challenges.cloudflare.com/turnstile'></script></html>"

    monkeypatch.setattr(client.session, "get", lambda *a, **kw: FakeChallengeResp())
    try:
        client.fetch_popular("movies")
        assert False, "Expected X1337Error on Cloudflare challenge"
    except X1337Error as exc:
        assert "Cloudflare" in str(exc)


def test_settings_sources_base_urls_persistence(tmp_path):
    x1337_mock = Mock(spec=X1337Client)
    x1337_mock.base_url = "https://1337x.to"
    x1337_mock.fetch_popular.return_value = []

    app = create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(tmp_path / "sources_test.db"),
            "SECRET_KEY": "test-secret",
        },
        x1337_client=x1337_mock,
    )
    with app.test_client() as client:
        login_as_admin(client)
        page = client.get("/settings?tab=sources")
        html = page.data.decode()
        assert "Source &amp; Scraper Base URLs" in html
        token = extract_csrf(html)

        resp = client.post(
            "/settings?tab=sources",
            data={
                "csrf_token": token,
                "section": "sources",
                "hdhub4u_base_url": "https://hdhub4u.example.org/",
                "x1337_base_url": "https://1337x.example.org/",
            },
            follow_redirects=True,
        )
        body = resp.data.decode()
        assert resp.status_code == 200
        assert "Source base URLs saved successfully." in body
        assert "https://hdhub4u.example.org" in body
        assert "https://1337x.example.org" in body
        assert x1337_mock.base_url == "https://1337x.example.org"


def test_torrents_page_and_download_with_aria2c(tmp_path, monkeypatch):
    movies_dir = tmp_path / "movies"
    fake_1337 = Mock(spec=X1337Client)
    fake_1337.base_url = "https://1337x.to"
    fake_1337.fetch_popular.return_value = parse_1337x_popular(
        SAMPLE_1337X_POPULAR_HTML, category="movies"
    )
    fake_1337.fetch_torrent_details.return_value = parse_1337x_details(
        SAMPLE_1337X_DETAIL_HTML,
        page_url="https://1337x.to/torrent/612345/Dune-Part-Two-2024-1080p-WEB-DL/",
        category="movies",
    )

    monkeypatch.setattr(x1337_torrent_mod, "detect_torrent_engine", lambda: "aria2c")

    class FakeProc:
        stdout = iter(["[#abc 1.2GiB/2.4GiB(50%) CN:12 DL:15.5MiB]\n"])

        def poll(self):
            return 0

        def wait(self):
            return 0

        def terminate(self):
            pass

    called_cmds = []

    def fake_popen(cmd, **kwargs):
        called_cmds.append(cmd)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    app = create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(tmp_path / "torrents_test.db"),
            "SECRET_KEY": "test-secret",
        },
        path_overrides={"movies_download_path": str(movies_dir)},
        create_dirs=True,
        x1337_client=fake_1337,
    )

    with app.test_client() as client:
        login_as_admin(client)
        resp = client.get("/torrents?cat=movies")
        html = resp.data.decode()
        assert resp.status_code == 200
        assert "Dune Part Two (2024)" in html

        token = extract_csrf(html)
        dl_resp = client.post(
            "/api/1337x/download",
            json={
                "title": "Dune Part Two (2024) 1080p WEB-DL x264",
                "torrent_page_url": "https://1337x.to/torrent/612345/Dune-Part-Two-2024-1080p-WEB-DL/",
                "media_type": "movie",
                "category": "movies",
            },
            headers={"X-CSRF-Token": token},
        )
        assert dl_resp.status_code == 202
        job_id = dl_resp.get_json()["job"]["id"]

        for _ in range(30):
            jobs = client.get("/api/downloads").get_json()["jobs"]
            job = next((j for j in jobs if j["id"] == job_id), None)
            if job and job["status"] == "completed":
                break
            time.sleep(0.05)

        assert job["status"] == "completed"
        assert (movies_dir / "Dune Part Two (2024)").is_dir()
        assert called_cmds and os.path.basename(called_cmds[0][0]) == "aria2c"


def test_detect_torrent_engine_finds_installed_aria2c():
    assert x1337_torrent_mod.detect_torrent_engine() == "aria2c"
