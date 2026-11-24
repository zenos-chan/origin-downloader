import time
from unittest.mock import Mock

from app import create_app
from extensions.hdhub4u import (
    DownloadManager,
    HDHub4uClient,
    build_media_naming,
    parse_movie_details,
    parse_recent_items,
)
from tests.test_app import extract_csrf, login_as_admin


SAMPLE_LISTING_HTML = """
<ul class="recent-movies">
  <li class="thumb col-md-2">
    <figure>
      <a href="/delhi-2021-2026-hindi-webrip-full-movie/" aria-label="Delhi 2021 (2026) 4K 1080p WEB-DL | Full Movie">
        <img src="https://image.tmdb.org/t/p/w342/poster1.jpg" alt="Delhi 2021" />
      </a>
    </figure>
    <figcaption>
      <a href="/delhi-2021-2026-hindi-webrip-full-movie/">
        <p>Delhi 2021 (2026) DS4K WEB-DL [Hindi] 4K 1080p 720p | Full Movie</p>
      </a>
    </figcaption>
  </li>
  <li class="thumb col-md-2">
    <figure>
      <a href="/the-good-doctor-season-1-webrip-hindi-full-series/">
        <img src="https://image.tmdb.org/t/p/w342/poster2.jpg" alt="Good Doctor" />
      </a>
    </figure>
    <figcaption>
      <a href="/the-good-doctor-season-1-webrip-hindi-full-series/">
        <p>The Good Doctor (Season 1) WEB-DL 1080p | NF Series</p>
      </a>
    </figcaption>
  </li>
  <li class="thumb col-md-2">
    <figure>
      <a href="/solo-leveling-anime-season-2/">
        <img src="https://image.tmdb.org/t/p/w342/poster3.jpg" alt="Solo Leveling" />
      </a>
    </figure>
    <figcaption>
      <a href="/solo-leveling-anime-season-2/">
        <p>Solo Leveling Anime (Season 2) Crunchyroll 1080p</p>
      </a>
    </figcaption>
  </li>
</ul>
"""

SAMPLE_DETAIL_HTML = """
<div class="page-body">
  <h1 class="page-title">Delhi 2021 (2026) 4K WEB-DL | HDHub4u</h1>
  <img src="https://image.tmdb.org/t/p/w342/poster1.jpg" />
  <a href="/how-to-download/">How To Download</a>
  <a href="https://www.imdb.com/title/tt51547104/">7.8/10</a>
  <a href="https://catimages.org/image/shot1"></a>
  <a href="https://hubdrive.blog/file/1860119639">4K [2160p SDR WEB-DL – 3GB]</a>
  <a href="https://greenmotors.club/?id=abc">1080p WEB-DL [1.2GB]</a>
</div>
"""


def test_parse_recent_items_extracts_metadata_and_types():
    items = parse_recent_items(SAMPLE_LISTING_HTML, base_url="https://new16.hdhub4u.cl")
    assert len(items) == 3

    assert items[0]["title"].startswith("Delhi 2021 (2026)")
    assert items[0]["url"] == "https://new16.hdhub4u.cl/delhi-2021-2026-hindi-webrip-full-movie/"
    assert items[0]["media_type"] == "movie"
    assert items[0]["year"] == "2026"
    assert "4K" in items[0]["qualities"]

    assert items[1]["media_type"] == "tv"
    assert items[2]["media_type"] == "anime"


def test_parse_movie_details_extracts_options_and_filters_noise():
    details = parse_movie_details(
        SAMPLE_DETAIL_HTML,
        page_url="https://new16.hdhub4u.cl/delhi-2021-2026-hindi-webrip-full-movie/",
    )
    assert details["title"] == "Delhi 2021 (2026) 4K WEB-DL"
    assert details["imdb_rating"] == "7.8/10"
    assert len(details["download_options"]) == 2
    assert details["download_options"][0]["resolvable"] is True
    assert details["download_options"][1]["resolvable"] is False


def test_resolve_hubdrive_chain(monkeypatch):
    pages = {
        "https://hubdrive.blog/file/1860119639": '<a href="https://hubcloud.mov/drive/xyz">HubCloud</a>',
        "https://hubcloud.mov/drive/xyz": '<a id="download" href="https://gamerxyt.com/hubcloud.php?id=xyz">Generate</a>',
        "https://gamerxyt.com/hubcloud.php?id=xyz": (
            '<a id="fsl" href="https://pub.r2.cloudflarestorage.com/hax/file?response-content-disposition=attachment%3B%20filename%3D%22Delhi.2026.mkv%22">Download [FSL Server]</a>'
        ),
    }

    client = HDHub4uClient()
    monkeypatch.setattr(client, "_get_text", lambda url, referer="": pages[url])

    mirrors = client.resolve_download_links("https://hubdrive.blog/file/1860119639")
    assert len(mirrors) == 1
    assert mirrors[0]["server"] == "FSL Server"
    assert mirrors[0]["filename"] == "Delhi.2026.mkv"
    assert "r2.cloudflarestorage.com" in mirrors[0]["url"]


def test_build_media_naming_formats_folder_and_file():
    naming = build_media_naming(
        title="Ice Cream Man (2026) BluRay [Hindi & English] 4K 1080p",
        quality_label="1080p 10Bit HEVC [1.5GB]",
        original_filename="Ice.Cream.Man.2026.1080p.mp4",
    )
    assert naming["folder_name"] == "Ice Cream Man (2026)"
    assert naming["filename"] == "Ice-Cream-Man-1080p-2026.mp4"

    naming_4k = build_media_naming(
        title="Delhi 2021 (2026) DS4K WEB-DL [Hindi DD5.1] 4K 1080p | Full Movie",
        quality_label="4K [2160p SDR WEB-DL – 3GB]",
        original_filename="Delhi-2021.2026.4K.mkv",
        media_type="movie",
    )
    assert naming_4k["folder_name"] == "Delhi 2021 (2026)"
    assert naming_4k["filename"] == "Delhi-2021-4K-2026.mkv"

    tv_naming = build_media_naming(
        title="The Good Doctor (2017) (Season 1) WEB-DL 1080p | NF Series",
        quality_label="1080p EP – PACK",
        original_filename="The.Good.Doctor.S01E03.1080p.WEB-DL.mkv",
        media_type="tv",
    )
    assert tv_naming["folder_name"] == "The Good Doctor (2017)/Season 1"
    assert tv_naming["filename"] == "Episode-03-1080p.mkv"

    anime_with_season = build_media_naming(
        title="Solo Leveling (2025) (Season 2) Crunchyroll 1080p",
        quality_label="1080p",
        original_filename="Solo.Leveling.S02E05.1080p.mp4",
        media_type="anime",
    )
    assert anime_with_season["folder_name"] == "Solo Leveling (2025)/Season 2"
    assert anime_with_season["filename"] == "Episode-05.mp4"

    anime_direct = build_media_naming(
        title="One Piece (1999) Anime 1080p",
        quality_label="1080p",
        original_filename="One.Piece.EP1120.1080p.mkv",
        media_type="anime",
    )
    assert anime_direct["folder_name"] == "One Piece (1999)"
    assert anime_direct["filename"] == "Episode-1120.mkv"


def test_resolve_hubdrive_pack(monkeypatch):
    pack_html = """
    <div class="pack-clean-list">
      <div class="pack-clean-file">
        <div class="pack-clean-title">The.Good.Doctor.S01E01.480p.WEB-DL.mkv</div>
        <div class="pack-clean-size">171.23 MB | video/x-matroska</div>
        <a class="pack-clean-link" href="/file/1877363675"></a>
      </div>
      <div class="pack-clean-file">
        <div class="pack-clean-title">The.Good.Doctor.S01E02.480p.WEB-DL.mkv</div>
        <div class="pack-clean-size">180.10 MB | video/x-matroska</div>
        <a class="pack-clean-link" href="/file/1906117353"></a>
      </div>
    </div>
    """
    client = HDHub4uClient()
    monkeypatch.setattr(client, "_get_text", lambda url, referer="": pack_html)
    episodes = client.resolve_download_links("https://hubdrive.blog/packs/moeqjsrn")
    assert len(episodes) == 2
    assert episodes[0]["is_pack_item"] is True
    assert episodes[0]["server"] == "Episode 01 (171.23 MB)"
    assert episodes[0]["url"] == "https://hubdrive.blog/file/1877363675"
    assert episodes[1]["url"] == "https://hubdrive.blog/file/1906117353"


def test_movies_route_and_download_into_configured_folder(tmp_path, monkeypatch):
    movies_dir = tmp_path / "movies"
    tv_dir = tmp_path / "tv"
    anime_dir = tmp_path / "anime"

    fake_client = Mock(spec=HDHub4uClient)
    fake_client.fetch_recent.return_value = parse_recent_items(SAMPLE_LISTING_HTML)
    fake_client.fetch_movie_details.return_value = parse_movie_details(
        SAMPLE_DETAIL_HTML,
        "https://new16.hdhub4u.cl/delhi-2021-2026-hindi-webrip-full-movie/",
    )
    fake_client.resolve_download_links.return_value = [
        {
            "server": "FSL Server",
            "url": "https://cdn.example.com/Delhi.2026.mkv",
            "filename": "Delhi.2026.mkv",
        }
    ]

    # Mock streaming download HTTP response
    class FakeResp:
        headers = {"Content-Length": "11"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024):
            yield b"hello-movie"

    monkeypatch.setattr("extensions.hdhub4u.downloader.requests.get", lambda *a, **kw: FakeResp())

    db_path = tmp_path / "movies_test.db"
    dl_manager = DownloadManager(client=fake_client, db_path=str(db_path))
    app = create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(db_path),
            "SECRET_KEY": "test-secret",
        },
        path_overrides={
            "movies_download_path": str(movies_dir),
            "tv_download_path": str(tv_dir),
            "anime_download_path": str(anime_dir),
        },
        create_dirs=True,
        hdhub_client=fake_client,
        download_manager=dl_manager,
    )

    with app.test_client() as test_client:
        login_as_admin(test_client)

        page_resp = test_client.get("/movies")
        html = page_resp.data.decode()
        assert page_resp.status_code == 200
        assert "Delhi 2021 (2026)" in html
        assert str(movies_dir) in html

        token = extract_csrf(html)
        dl_resp = test_client.post(
            "/api/hdhub4u/download",
            json={
                "title": "Delhi 2021 (2026) DS4K WEB-DL [Hindi DD5.1] 4K 1080p | Full Movie",
                "quality_label": "4K [2160p SDR WEB-DL – 3GB]",
                "url": "https://hubdrive.blog/file/1860119639",
                "media_type": "movie",
            },
            headers={"X-CSRF-Token": token},
        )
        assert dl_resp.status_code == 202
        job_id = dl_resp.get_json()["job"]["id"]

        # Wait briefly for background thread to complete
        for _ in range(30):
            job = dl_manager.get_job(job_id)
            if job and job["status"] == "completed":
                break
            time.sleep(0.05)

        final_job = dl_manager.get_job(job_id)
        assert final_job["status"] == "completed"
        saved_file = movies_dir / "Delhi 2021 (2026)" / "Delhi-2021-4K-2026.mkv"
        assert saved_file.exists()
        assert saved_file.read_bytes() == b"hello-movie"

        # Dashboard reflects real transfer & KPI counts without dummy data
        dash_html = test_client.get("/dashboard").data.decode()
        assert "Delhi-2021-4K-2026.mkv" in dash_html
        assert "1 completed" in dash_html
        assert "ubuntu-24.04.1-server-amd64.iso" not in dash_html

        # Persists across DownloadManager restart
        restarted_manager = DownloadManager(client=fake_client, db_path=str(db_path))
        persisted = restarted_manager.get_job(job_id)
        assert persisted is not None
        assert persisted["status"] == "completed"
        assert persisted["filename"] == "Delhi-2021-4K-2026.mkv"
