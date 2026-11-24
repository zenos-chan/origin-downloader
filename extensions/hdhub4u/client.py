import os
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://new16.hdhub4u.cl"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

QUALITY_PATTERNS = [
    ("4K", re.compile(r"\b(?:4k|2160p)\b", re.IGNORECASE)),
    ("1080p", re.compile(r"\b1080p\b", re.IGNORECASE)),
    ("720p", re.compile(r"\b720p\b", re.IGNORECASE)),
    ("480p", re.compile(r"\b480p\b", re.IGNORECASE)),
    ("HEVC", re.compile(r"\b(?:hevc|x265|10bit)\b", re.IGNORECASE)),
    ("WEB-DL", re.compile(r"\b(?:web-dl|webrip|ds4k)\b", re.IGNORECASE)),
    ("BluRay", re.compile(r"\bbluray\b", re.IGNORECASE)),
]

RESOLVABLE_HOST_KEYWORDS = ("hubdrive", "hubcloud", "gamerxyt")
IGNORED_LINK_DOMAINS = (
    "imdb.com",
    "catimages.org",
    "t.me",
    "telegram.",
    "tinyurl.com",
    "one.one.one.one",
    "google.com",
    "winexch.com",
    "snvhost.com",
)


class HDHub4uError(Exception):
    """Raised when fetching or parsing HDHub4u pages fails."""


def classify_media_type(title: str, url: str = "") -> str:
    """Infer whether a release is anime, tv, or movie from its title and URL."""
    haystack = f"{title} {url}".lower()
    if any(tok in haystack for tok in ("anime", "crunchyroll", "ova", "donghua")):
        return "anime"
    if any(
        tok in haystack
        for tok in (
            "season ",
            "s01",
            "s02",
            "s03",
            "series",
            "ep-",
            "ep ",
            "episode",
            "full-series",
            "all episodes",
        )
    ):
        return "tv"
    return "movie"


def extract_qualities(text: str) -> list[str]:
    found = []
    for label, pattern in QUALITY_PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found[:4]


def _extract_year(text: str) -> str:
    paren_match = re.search(r"\((19\d{2}|20\d{2})\)", text)
    if paren_match:
        return paren_match.group(1)
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return match.group(1) if match else ""


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_resolvable_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(keyword in host for keyword in RESOLVABLE_HOST_KEYWORDS)


def _is_direct_media_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(
        ext in path
        for ext in (".mkv", ".mp4", ".avi", ".zip", ".rar", ".m4v", ".mov", ".srt")
    ):
        return True
    if "r2.cloudflarestorage.com" in host or "gpdl.hubcloud" in host or "pixeldrain" in host:
        return True
    qs = parse_qs(parsed.query)
    if "response-content-disposition" in qs:
        return True
    return False


def _guess_filename_from_url(url: str, fallback_title: str = "download") -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    disp_values = qs.get("response-content-disposition") or []
    for val in disp_values:
        decoded = unquote(val)
        match = re.search(r'filename="?([^";]+)"?', decoded, re.IGNORECASE)
        if match:
            return _sanitize_filename(match.group(1))

    basename = unquote(parsed.path.rstrip("/").split("/")[-1])
    if "." in basename and len(basename) > 4:
        return _sanitize_filename(basename)

    slug = re.sub(r"[^A-Za-z0-9._-]+", ".", fallback_title).strip(".")
    return f"{slug or 'video'}.mkv"


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return cleaned or "download.mkv"


def _extract_quality_token(text: str) -> str:
    if not text:
        return ""
    if re.search(r"\b(?:4k|2160p)\b", text, re.IGNORECASE):
        return "4K"
    for res in ("1080p", "720p", "480p"):
        if re.search(rf"\b{res}\b", text, re.IGNORECASE):
            return res
    return ""


def _extract_season_number(text: str) -> str:
    if not text:
        return ""
    patterns = (
        r"\bS(\d{1,2})E\d{1,3}\b",
        r"\(?\bSeason[\s._-]*(\d{1,2})\b\)?",
        r"\bS(\d{1,2})\b",
    )
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return str(int(match.group(1)))
    return ""


def _extract_episode_number(text: str) -> str:
    if not text:
        return ""
    patterns = (
        r"\bS\d{1,2}E(\d{1,4})\b",
        r"\bEP(?:ISODE)?[\s._–-]*(\d{1,4})\b",
        r"\bE(\d{1,4})\b",
    )
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            return f"{num:02d}"
    return ""


def build_media_naming(
    title: str,
    quality_label: str = "",
    original_filename: str = "",
    media_type: str = "movie",
) -> dict:
    """Build media-specific folder structure and filename for movie, tv, and anime."""
    raw_title = (title or "").strip()
    kind = (media_type or "movie").strip().lower()

    # Extract release year from (YYYY) first, avoiding season parentheses
    paren_year = re.search(r"\((19\d{2}|20\d{2})\)", raw_title)
    if paren_year:
        year = paren_year.group(1)
    else:
        year = _extract_year(raw_title) or _extract_year(original_filename)

    # Extract clean title by stripping year, season, brackets, and release tags
    name_part = raw_title.split("|")[0]
    if paren_year:
        name_part = name_part[: paren_year.start()].strip()
    name_part = re.sub(r"\(\s*Season\s*\d{1,2}\s*\)", " ", name_part, flags=re.IGNORECASE)
    name_part = re.sub(r"\bSeason\s*\d{1,2}\b", " ", name_part, flags=re.IGNORECASE)
    name_part = re.sub(r"\[[^\]]*\]", " ", name_part)
    name_part = re.sub(
        r"\b(?:DS4K|WEB-?DL|WEBRip|BluRay|HDTC|HQ-HDTC|UNCUT|4K|2160p|1080p|720p|480p|HEVC|x264|x265|10Bit|Crunchyroll|Dual Audio)\b.*",
        "",
        name_part,
        flags=re.IGNORECASE,
    ).strip()
    if year:
        name_part = re.sub(rf"\b{year}\b\s*$", "", name_part).strip()

    clean_name = name_part.replace(":", " -")
    clean_name = re.sub(r'[\\/*?"<>|]+', " ", clean_name)
    clean_name = re.sub(r"\s+", " ", clean_name).strip(" -._")
    if not clean_name:
        clean_name = {"tv": "TV Show", "anime": "Anime"}.get(kind, "Movie")

    quality = (
        _extract_quality_token(quality_label)
        or _extract_quality_token(original_filename)
        or _extract_quality_token(raw_title)
        or "HD"
    )

    ext = ".mkv"
    if original_filename:
        _, parsed_ext = os.path.splitext(original_filename.strip())
        if re.match(r"^\.[A-Za-z0-9]{2,5}$", parsed_ext):
            ext = parsed_ext.lower()

    season_num = (
        _extract_season_number(original_filename)
        or _extract_season_number(quality_label)
        or _extract_season_number(raw_title)
    )
    episode_num = (
        _extract_episode_number(original_filename)
        or _extract_episode_number(quality_label)
        or _extract_episode_number(raw_title)
    )

    base_folder = f"{clean_name} ({year})" if year else clean_name
    hyphen_name = re.sub(r"[^A-Za-z0-9]+", "-", clean_name).strip("-") or "Media"

    if kind == "tv":
        effective_season = season_num or "1"
        folder_name = os.path.join(base_folder, f"Season {effective_season}")
        if episode_num:
            formatted_filename = f"Episode-{episode_num}-{quality}{ext}"
        else:
            season_pad = f"{int(effective_season):02d}"
            formatted_filename = f"Season-{season_pad}-Pack-{quality}{ext}"
    elif kind == "anime":
        folder_name = (
            os.path.join(base_folder, f"Season {season_num}")
            if season_num
            else base_folder
        )
        if episode_num:
            formatted_filename = f"Episode-{episode_num}{ext}"
        else:
            formatted_filename = (
                f"{hyphen_name}-{year}{ext}" if year else f"{hyphen_name}{ext}"
            )
    else:
        folder_name = base_folder
        filename_parts = [hyphen_name, quality]
        if year:
            filename_parts.append(year)
        formatted_filename = f"{'-'.join(filename_parts)}{ext}"

    return {
        "movie_name": clean_name,
        "year": year,
        "quality": quality,
        "season": season_num,
        "episode": episode_num,
        "ext": ext,
        "folder_name": folder_name,
        "filename": formatted_filename,
    }


def parse_recent_items(html: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    """Parse recent movie/series cards from an HDHub4u listing page."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_urls = set()

    for li in soup.select("ul.recent-movies li.thumb"):
        link_tag = li.select_one("figcaption a[href]") or li.select_one("figure a[href]")
        if not link_tag:
            continue

        href = (link_tag.get("href") or "").strip()
        if not href:
            continue

        full_url = urljoin(base_url.rstrip("/") + "/", href)
        if full_url in seen_urls or not _is_http_url(full_url):
            continue
        seen_urls.add(full_url)

        title_el = li.select_one("figcaption p")
        img_el = li.select_one("figure img")
        raw_title = (
            (title_el.get_text(" ", strip=True) if title_el else "")
            or (link_tag.get("aria-label") or "")
            or (img_el.get("alt") if img_el else "")
            or "Untitled Release"
        ).strip()

        poster = ""
        if img_el:
            poster = (
                img_el.get("src")
                or img_el.get("data-src")
                or img_el.get("data-lazy-src")
                or ""
            ).strip()
            if poster:
                poster = urljoin(base_url.rstrip("/") + "/", poster)

        items.append(
            {
                "title": raw_title,
                "url": full_url,
                "poster": poster,
                "media_type": classify_media_type(raw_title, full_url),
                "qualities": extract_qualities(raw_title),
                "year": _extract_year(raw_title),
            }
        )

    return items


def parse_movie_details(
    html: str, page_url: str, base_url: str = DEFAULT_BASE_URL
) -> dict:
    """Parse title, poster, IMDb info, and download links from a movie detail page."""
    soup = BeautifulSoup(html, "html.parser")
    page_body = soup.select_one(".page-body") or soup.select_one("main") or soup

    title_el = (
        page_body.select_one("h1.page-title")
        or page_body.select_one("h1")
        or soup.select_one("title")
    )
    title = title_el.get_text(" ", strip=True) if title_el else "Unknown Title"
    title = re.sub(r"\s*[-–|]\s*HDHub4u.*$", "", title, flags=re.IGNORECASE).strip()

    poster = ""
    poster_img = page_body.select_one(
        'img[src*="tmdb"], img[src*="poster"], img.wp-post-image, main img'
    )
    if poster_img:
        poster = (poster_img.get("src") or poster_img.get("data-src") or "").strip()
        if poster:
            poster = urljoin(base_url.rstrip("/") + "/", poster)

    imdb_url = ""
    imdb_rating = ""
    imdb_link = page_body.select_one('a[href*="imdb.com/title/"]')
    if imdb_link:
        imdb_url = (imdb_link.get("href") or "").strip()
        rating_text = imdb_link.get_text(" ", strip=True)
        if rating_text and not rating_text.lower().startswith("x/"):
            imdb_rating = rating_text

    download_options = []
    seen_links = set()

    # Remove nested recent-movies carousel inside page-body if present
    for link in page_body.select("a[href]"):
        if link.find_parent(class_="recent-movies"):
            continue

        href = (link.get("href") or "").strip()
        label = link.get_text(" ", strip=True)
        if not href or not label:
            continue

        full_href = urljoin(page_url, href)
        if not _is_http_url(full_href):
            continue

        parsed_href = urlparse(full_href)
        parsed_base = urlparse(base_url)
        host = parsed_href.netloc.lower()

        # Skip internal site navigation links and unrelated external sites
        if host == parsed_base.netloc.lower():
            continue
        if any(ignored in host for ignored in IGNORED_LINK_DOMAINS):
            continue
        if any(skip in label.lower() for skip in ("watch-", "player-", "how to download", "4k | sdr")):
            continue

        if full_href in seen_links:
            continue
        seen_links.add(full_href)

        is_download_candidate = (
            _is_resolvable_host(full_href)
            or _is_direct_media_url(full_href)
            or bool(
                re.search(
                    r"\b(480p|720p|1080p|2160p|4k|hevc|web-dl|bluray|zip|episode|ep)\b",
                    label,
                    re.IGNORECASE,
                )
            )
            or "greenmotors" in host
            or "hblinks" in host
            or "hubcdn" in host
        )
        if not is_download_candidate:
            continue

        download_options.append(
            {
                "label": label,
                "url": full_href,
                "host": host,
                "resolvable": _is_resolvable_host(full_href) or _is_direct_media_url(full_href),
                "qualities": extract_qualities(label),
            }
        )

    return {
        "title": title,
        "url": page_url,
        "poster": poster,
        "imdb_url": imdb_url,
        "imdb_rating": imdb_rating,
        "media_type": classify_media_type(title, page_url),
        "download_options": download_options,
    }


class HDHub4uClient:
    """HTTP client for browsing HDHub4u and resolving direct file mirrors."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def _get_text(self, url: str, referer: str = "") -> str:
        if not _is_http_url(url):
            raise HDHub4uError("Invalid URL scheme.")
        headers = {"Referer": referer} if referer else {}
        try:
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            raise HDHub4uError(f"Failed to fetch {url}: {exc}") from exc

    def fetch_recent(self, page: int = 1, search: str = "") -> list[dict]:
        page = max(1, int(page))
        search = (search or "").strip()
        if search:
            target_url = (
                f"{self.base_url}/page/{page}/" if page > 1 else f"{self.base_url}/"
            )
            try:
                resp = self.session.get(
                    target_url, params={"s": search}, timeout=self.timeout
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise HDHub4uError(f"Search failed: {exc}") from exc
            return parse_recent_items(resp.text, base_url=self.base_url)

        target_url = (
            f"{self.base_url}/page/{page}/" if page > 1 else f"{self.base_url}/"
        )
        html = self._get_text(target_url)
        return parse_recent_items(html, base_url=self.base_url)

    def fetch_movie_details(self, movie_url: str) -> dict:
        html = self._get_text(movie_url, referer=self.base_url + "/")
        return parse_movie_details(html, page_url=movie_url, base_url=self.base_url)

    def resolve_download_links(self, source_url: str, fallback_title: str = "video") -> list[dict]:
        """Resolve HubDrive -> HubCloud -> GamerXYT direct download mirrors."""
        if not _is_http_url(source_url):
            raise HDHub4uError("Invalid download link URL.")

        if _is_direct_media_url(source_url):
            return [
                {
                    "server": "Direct Link",
                    "url": source_url,
                    "filename": _guess_filename_from_url(source_url, fallback_title),
                }
            ]

        current_url = source_url
        host = urlparse(current_url).netloc.lower()

        # Step 1: HubDrive pack or single file -> extract episode list or HubCloud link
        if "hubdrive" in host:
            html = self._get_text(current_url, referer=self.base_url + "/")
            soup = BeautifulSoup(html, "html.parser")
            if "/packs/" in urlparse(current_url).path.lower():
                pack_items = self._extract_pack_items(soup, current_url, fallback_title)
                if not pack_items:
                    raise HDHub4uError("No episode links found in this HubDrive pack.")
                return pack_items

            hubcloud_link = soup.select_one('a[href*="hubcloud"]')
            if not hubcloud_link:
                raise HDHub4uError(
                    "Could not find a HubCloud mirror on this HubDrive page."
                )
            current_url = urljoin(current_url, hubcloud_link["href"].strip())
            host = urlparse(current_url).netloc.lower()

        # Step 2: HubCloud -> extract GamerXYT / generator link or direct mirrors
        if "hubcloud" in host and "hubcloud.php" not in current_url:
            html = self._get_text(current_url, referer=source_url)
            soup = BeautifulSoup(html, "html.parser")
            direct_mirrors = self._extract_final_mirrors(soup, current_url, fallback_title)
            if direct_mirrors:
                return direct_mirrors

            gen_link = soup.select_one('a#download[href], a[href*="hubcloud.php"]')
            next_url = ""
            if gen_link and gen_link.get("href"):
                next_url = urljoin(current_url, gen_link["href"].strip())
            else:
                js_match = re.search(
                    r"var\s+url\s*=\s*['\"](https?://[^'\"]+)['\"]", html
                )
                if js_match:
                    next_url = js_match.group(1)

            if not next_url:
                raise HDHub4uError(
                    "Could not locate the download generator link on HubCloud."
                )
            current_url = next_url
            host = urlparse(current_url).netloc.lower()

        # Step 3: GamerXYT / HubCloud generator page -> final direct download links
        if "gamerxyt" in host or "hubcloud.php" in current_url:
            html = self._get_text(current_url, referer=source_url)
            soup = BeautifulSoup(html, "html.parser")
            mirrors = self._extract_final_mirrors(soup, current_url, fallback_title)
            if mirrors:
                return mirrors
            raise HDHub4uError(
                "No direct download mirrors were found on the generated page."
            )

        raise HDHub4uError(
            f"Unsupported redirect host ({host}). Open this source link directly in your browser."
        )

    def _extract_final_mirrors(
        self, soup: BeautifulSoup, page_url: str, fallback_title: str
    ) -> list[dict]:
        mirrors = []
        seen = set()

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            text = anchor.get_text(" ", strip=True)
            if not href:
                continue

            full_url = urljoin(page_url, href)
            if not _is_http_url(full_url):
                continue

            host = urlparse(full_url).netloc.lower()
            if any(ignored in host for ignored in IGNORED_LINK_DOMAINS):
                continue
            if any(skip in full_url.lower() for skip in ("hbplay.pages.dev", "/drive/admin")):
                continue

            if _is_direct_media_url(full_url) or anchor.get("id") == "fsl":
                if full_url in seen:
                    continue
                seen.add(full_url)
                label = re.sub(r"^Download\s*", "", text, flags=re.IGNORECASE).strip(" []")
                mirrors.append(
                    {
                        "server": label or host,
                        "url": full_url,
                        "filename": _guess_filename_from_url(full_url, fallback_title),
                    }
                )

        return mirrors

    def _extract_pack_items(
        self, soup: BeautifulSoup, page_url: str, fallback_title: str
    ) -> list[dict]:
        episodes = []
        seen = set()
        for idx, card in enumerate(soup.select(".pack-clean-file"), start=1):
            link = card.select_one("a.pack-clean-link[href], a[href*='/file/']")
            if not link:
                continue
            href = urljoin(page_url, (link.get("href") or "").strip())
            if not _is_http_url(href) or href in seen:
                continue
            seen.add(href)

            title_el = card.select_one(".pack-clean-title")
            size_el = card.select_one(".pack-clean-size")
            ep_filename = (
                title_el.get_text(" ", strip=True)
                if title_el
                else f"{fallback_title}-E{idx:02d}.mkv"
            )
            ep_num = _extract_episode_number(ep_filename) or f"{idx:02d}"
            size_text = size_el.get_text(" ", strip=True).split("|")[0].strip() if size_el else ""
            server_label = f"Episode {ep_num}" + (f" ({size_text})" if size_text else "")

            episodes.append(
                {
                    "server": server_label,
                    "url": href,
                    "filename": _sanitize_filename(ep_filename),
                    "is_pack_item": True,
                }
            )
        return episodes
