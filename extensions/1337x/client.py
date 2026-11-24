import re
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from extensions.hdhub4u.client import (
    DEFAULT_HEADERS,
    _extract_year,
    _is_http_url,
    extract_qualities,
)

DEFAULT_1337X_BASE_URL = "https://1337x.to"

CATEGORY_POPULAR_PATHS = {
    "movies": "/popular-movies",
    "tv": "/popular-tv",
    "anime": "/popular-anime",
}

CATEGORY_MEDIA_TYPE = {
    "movies": "movie",
    "tv": "tv",
    "anime": "anime",
}


class X1337Error(Exception):
    """Raised when scraping 1337x fails or is blocked by an anti-bot challenge."""


def _is_cloudflare_challenge(html: str, status_code: int = 200) -> bool:
    lower = (html or "").lower()
    if "challenges.cloudflare.com" in lower or "_cf_chl_opt" in lower:
        return True
    if status_code == 403 and ("just a moment" in lower or "cf-browser-verification" in lower):
        return True
    return False


def _parse_int(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def parse_1337x_popular(
    html: str,
    category: str = "movies",
    base_url: str = DEFAULT_1337X_BASE_URL,
) -> list[dict]:
    """Parse popular/trending or search torrent rows from a 1337x listing page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_urls = set()
    media_type = CATEGORY_MEDIA_TYPE.get(category, "movie")

    for row in soup.select("table.table-list tbody tr"):
        name_cell = row.select_one("td.coll-1.name") or row.select_one("td.name")
        if not name_cell:
            continue

        link_el = name_cell.select_one('a[href*="/torrent/"]') or name_cell.select("a[href]")[-1]
        if not link_el:
            continue

        href = (link_el.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url.rstrip("/") + "/", href)
        if not _is_http_url(full_url) or full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = link_el.get_text(" ", strip=True)
        seeds_el = row.select_one("td.coll-2.seeds") or row.select_one("td.seeds")
        leeches_el = row.select_one("td.coll-3.leeches") or row.select_one("td.leeches")
        date_el = row.select_one("td.coll-date")
        size_el = row.select_one("td.coll-4.size") or row.select_one("td.size")
        uploader_el = row.select_one("td.coll-5")

        size_text = ""
        if size_el:
            # Remove nested span.seeds if present inside size cell
            size_clone = BeautifulSoup(str(size_el), "html.parser")
            for nested in size_clone.select("span"):
                nested.decompose()
            size_text = size_clone.get_text(" ", strip=True)

        items.append(
            {
                "title": title,
                "url": full_url,
                "category": category,
                "media_type": media_type,
                "seeders": _parse_int(seeds_el.get_text(strip=True) if seeds_el else "0"),
                "leechers": _parse_int(leeches_el.get_text(strip=True) if leeches_el else "0"),
                "size": size_text or "—",
                "uploaded": date_el.get_text(" ", strip=True) if date_el else "24h",
                "uploader": uploader_el.get_text(" ", strip=True) if uploader_el else "",
                "qualities": extract_qualities(title),
                "year": _extract_year(title),
            }
        )

    return items


def parse_1337x_details(
    html: str,
    page_url: str,
    category: str = "movies",
    base_url: str = DEFAULT_1337X_BASE_URL,
) -> dict:
    """Parse magnet URI, .torrent links, size, and seeders from a 1337x torrent page."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".box-info-heading h1") or soup.select_one("h1")
    title = title_el.get_text(" ", strip=True) if title_el else "Torrent Release"

    magnet_el = soup.select_one('a[href^="magnet:?"]')
    magnet_url = (magnet_el.get("href") or "").strip() if magnet_el else ""

    torrent_file_url = ""
    for link in soup.select("a[href]"):
        href = (link.get("href") or "").strip()
        if href.endswith(".torrent") or "itorrents.org" in href.lower():
            torrent_file_url = urljoin(page_url, href)
            break

    poster = ""
    poster_el = soup.select_one(".torrent-image img, .torrent-detail-info img")
    if poster_el and poster_el.get("src"):
        poster = urljoin(base_url.rstrip("/") + "/", poster_el["src"].strip())

    seeders = 0
    leechers = 0
    size = ""
    for li in soup.select(".torrent-detail-info ul.list li, ul.list li"):
        label = (li.select_one("strong").get_text(" ", strip=True).lower() if li.select_one("strong") else "")
        val = li.select_one("span").get_text(" ", strip=True) if li.select_one("span") else ""
        if "seeders" in label:
            seeders = _parse_int(val)
        elif "leechers" in label:
            leechers = _parse_int(val)
        elif "total size" in label:
            size = val

    return {
        "title": title,
        "url": page_url,
        "magnet": magnet_url,
        "torrent_file_url": torrent_file_url,
        "poster": poster,
        "seeders": seeders,
        "leechers": leechers,
        "size": size or "—",
        "media_type": CATEGORY_MEDIA_TYPE.get(category, "movie"),
        "qualities": extract_qualities(title),
    }


class X1337Client:
    """HTTP scraper for 1337x popular (24h) movies, TV, and anime torrents."""

    def __init__(self, base_url: str = DEFAULT_1337X_BASE_URL, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _get_text(self, url: str) -> str:
        if not _is_http_url(url):
            raise X1337Error("Invalid 1337x URL.")
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise X1337Error(
                f"Could not reach {self.base_url} ({exc}). Update the 1337x Base URL in Admin Settings if your network blocks this domain."
            ) from exc

        if _is_cloudflare_challenge(resp.text, resp.status_code):
            raise X1337Error(
                f"{urlparse(url).netloc} is gated by a Cloudflare anti-bot challenge (HTTP {resp.status_code}). "
                "Update the 1337x Base URL in Admin Settings or open the site directly in your browser."
            )

        if resp.status_code >= 400:
            raise X1337Error(f"1337x returned HTTP {resp.status_code} for {url}.")
        return resp.text

    def fetch_popular(self, category: str = "movies", search: str = "") -> list[dict]:
        cat = category if category in CATEGORY_POPULAR_PATHS else "movies"
        search = (search or "").strip()
        if search:
            cat_map = {"movies": "Movies", "tv": "TV", "anime": "Anime"}
            target_url = f"{self.base_url}/category-search/{quote(search)}/{cat_map[cat]}/1/"
        else:
            target_url = f"{self.base_url}{CATEGORY_POPULAR_PATHS[cat]}"
        html = self._get_text(target_url)
        return parse_1337x_popular(html, category=cat, base_url=self.base_url)

    def fetch_torrent_details(self, torrent_url: str, category: str = "movies") -> dict:
        html = self._get_text(torrent_url)
        return parse_1337x_details(
            html, page_url=torrent_url, category=category, base_url=self.base_url
        )
