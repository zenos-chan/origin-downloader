<div align="center">

# ⚡ Origin Downloader

**A modern, responsive Flask admin console for media discovery, automated folder organization, and live transfer management.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.x-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![Font Awesome](https://img.shields.io/badge/Font_Awesome-6.5-528DD7?style=for-the-badge&logo=fontawesome&logoColor=white)](https://fontawesome.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-10B981?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-21_Passing-22C55E?style=for-the-badge&logo=pytest&logoColor=white)](tests/)

</div>

---

## ✨ Features

- **Admin Authentication & Security**
  - Session-based admin login (`/login`) with `werkzeug.security` password hashing, CSRF protection on forms and JSON APIs, configurable session timeouts, and password strength feedback.
- **Real-Time Admin Dashboard** (`/dashboard`)
  - Live KPI cards (total downloads, active transfers, media folder storage used, and completion rate), 7-day / 30-day throughput chart backed by SQLite history, host disk & CPU telemetry, and a searchable/filterable live transfer queue.
- **HDHub4u Browser & HTTP Downloader** (`/movies` · `extensions/hdhub4u`)
  - Scrapes recent releases and search queries, extracts quality options (`4K`, `1080p`, `720p`, `480p`), resolves multi-hop mirrors (`HubDrive` → `HubCloud` → `GamerXYT` & `/packs/` episode packs), and streams files directly to disk with live progress polling.
- **1337x Popular (24h) & Torrent Engine** (`/torrents` · `extensions/1337x`)
  - Scrapes 24h popular Movies, TV Shows, and Anime, extracts `magnet:` URIs and torrent metadata, and dispatches downloads via `aria2c` or `transmission-cli` (with one-click magnet links in the modal).
- **Smart Media Folder Organization**
  - **Movies:** `<movies_path>/Movie Name (Year)/Movie-Name-Quality-Year.ext`
  - **TV Shows:** `<tv_path>/Tv Name (Year)/Season <N>/Episode-<NN>-<Quality>.ext`
  - **Anime:** `<anime_path>/Anime Name (Year)/Season <N>/Episode-<NN>.ext` (or directly `Anime Name (Year)/Episode-<NN>.ext` when no season is present)
- **Comprehensive Admin Settings** (`/settings`)
  - Tabbed responsive settings for **General**, **Download Paths** (Movie, TV, Anime with auto-creation toggle), **Source URLs** (editable base URLs for HDHub4u and 1337x), **Security & Account**, and **Notifications**.

---

## 🚀 Quick Start

### 1. Clone & Create a Virtual Environment

```bash
git clone https://github.com/zenos-chan/origin-downloader.git
cd origin-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Optional: Install a CLI Torrent Engine

For direct torrent downloads from `/torrents`, install `aria2` or `transmission-cli`:

```bash
# macOS (Homebrew)
brew install aria2

# Ubuntu / Debian
sudo apt install aria2
```

### 3. Run the Application

```bash
python app.py
```

Or specify your **Movie**, **TV**, and **Anime** download directories at startup via CLI flags:

```bash
python app.py \
  --movie-path ~/Downloads/Origin/Movies \
  --tv-path ~/Downloads/Origin/TV \
  --anime-path ~/Downloads/Origin/Anime \
  --create-dirs
```

Open **`http://127.0.0.1:5000`** in your browser and sign in with the default admin credentials:

- **Username:** `admin`
- **Password:** `admin123` *(change this immediately in **Admin Settings → Security & Account**)*

---

## ⚙️ CLI Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--movie-path`, `--movies-path` | Destination folder for Movie downloads | `./downloads/movies` |
| `--tv-path` | Destination folder for TV Show downloads | `./downloads/tv` |
| `--anime-path` | Destination folder for Anime downloads | `./downloads/anime` |
| `--create-dirs` | Create configured download folders on startup | `False` |
| `--host` | Host interface to bind | `127.0.0.1` |
| `--port` | Port to listen on | `5000` |
| `--no-debug` | Disable Flask debug reloader | `False` |

---

## 📁 Project Structure

```text
origin-downloader/
├── app.py                      # Flask app factory, routes, CLI flags & SQLite schema
├── requirements.txt            # Python dependencies
├── pytest.ini                  # Pytest configuration
├── extensions/
│   ├── hdhub4u/                # HDHub4u scraper, mirror/pack resolver & HTTP downloader
│   └── 1337x/                  # 1337x 24h popular scraper & aria2c/transmission-cli runner
├── static/
│   ├── css/custom.css          # Custom keyframe animations & micro-interactions
│   └── js/app.js               # Responsive UI, live queue polling, modals & chart switcher
├── templates/
│   ├── base.html               # Tailwind CSS, Font Awesome & toast notifications
│   ├── admin_layout.html       # Responsive sidebar drawer & top navbar
│   ├── login.html              # Animated admin login page
│   ├── dashboard.html          # Real-time KPIs, throughput chart & transfer queue
│   ├── movies.html             # HDHub4u browser & quality/pack modal
│   ├── torrents.html           # 1337x 24h popular browser & magnet modal
│   └── settings.html           # Tabbed admin configuration
└── tests/
    ├── test_app.py             # Auth, CSRF, settings & CLI flag tests
    ├── test_hdhub4u.py         # Parser, resolver, naming & download tests
    └── test_1337x.py           # 1337x parser, source URL & aria2c integration tests
```

---

## 🧪 Running Tests

```bash
pip install pytest
python -m pytest -v
```

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
