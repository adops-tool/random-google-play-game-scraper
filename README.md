<div align="center">

<pre>
       d8888                          8888888888 d8b               888                  
      d88888                          888        Y8P               888                  
     d88P888                          888                          888                  
    d88P 888 88888b.  88888b.         8888888    888 88888b.   .d88888  .d88b.  888d888 
   d88P  888 888 "88b 888 "88b        888        888 888 "88b d88" 888 d8P  Y8b 888P"   
  d88P   888 888  888 888  888 888888 888        888 888  888 888  888 88888888 888     
 d8888888888 888 d88P 888 d88P        888        888 888  888 Y88b 888 Y8b.     888     
d88P     888 88888P"  88888P"         888        888 888  888  "Y88888  "Y8888  888     
             888      888                                                               
             888      888                                                               
             888      888                                                               
</pre>

</div>

A high-throughput Python game discovery utility that continuously scrapes Google Play search results, filters by install-range heuristics, and persists deduplicated URLs to local storage and Google Sheets.

[![Gist](https://img.shields.io/badge/gist.github-version_of_this_repository-DCDCDC?style=for-the-badge&logo=github)](https://gist.github.com/OstinUA/4eec53453506f4a9f81d763fc61ddeb5)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Build](https://img.shields.io/badge/Build-Manual%20Validation-6c757d?style=for-the-badge)](#testing)
[![Coverage](https://img.shields.io/badge/Coverage-Not%20Configured-lightgrey?style=for-the-badge)](#testing)

> [!NOTE]
> The original project name is `App-Finder`, but operationally this repository behaves like a lightweight data collection pipeline for Google Play game URLs.

## Table of Contents

- [Features](#features)
- [Tech Stack & Architecture](#tech-stack--architecture)
- [Getting Started](#getting-started)
- [Testing](#testing)
- [Deployment](#deployment)
- [Usage](#usage)
- [Configuration](#configuration)
- [License](#license)
- [Support the Project](#support-the-project)

## Features

- Continuous discovery loop with randomized query generation to increase search-space coverage.
- Concurrent Google Play search and details-fetch stages powered by `ThreadPoolExecutor`.
- Install-count gatekeeping via configurable `MIN_INSTALLS` / `MAX_INSTALLS` thresholds.
- Genre filtering to keep only game-related listings (`genre` or `genreId` validation).
- Batch-oriented persistence pipeline for lower I/O overhead.
- Deduplication across sessions by loading previously collected app IDs from output artifacts.
- Dual-sink output model:
  - Local text sink (`games.txt` by default).
  - Optional Google Sheets sink (column `A`, append-only semantics, deduplicated against existing values).
- Locale diversification support via configurable `(language, country)` pairs.
- Graceful shutdown behavior (`Ctrl+C`) that flushes buffered links before exiting.

> [!TIP]
> Increasing `QUERIES_PER_RUN`, `SEARCH_LIMIT`, and `WORKERS` improves throughput, but may increase request failures and API throttling risk.

## Tech Stack & Architecture

### Core Stack

- **Language:** Python 3
- **Primary scraper dependency:** `google-play-scraper`
- **Sheets integration:** `gspread`, `google-auth`
- **Concurrency model:** Native thread pool (`concurrent.futures.ThreadPoolExecutor`)
- **Configuration style:** Static Python module (`settings.py`)

### Project Structure

```text
.
├── LICENSE
├── README.md
├── main.py                # Scraping loop, filtering, batching, and orchestration
├── settings.py            # Runtime and output configuration
├── sheet.py               # Google Sheets adapter and deduplicated appender
├── tests/                 # Offline unit tests
├── requirements.txt       # Bounded dependency versions
├── games.txt              # Local output file (generated/updated at runtime)
└── service_account.json   # Optional, locally supplied credentials (not committed)
```

### Key Design Decisions

- **Continuous by default:** supports supervised long-running collection and a `--once` mode for bounded runs.
- **Two-phase retrieval:** first collect candidate app IDs from search, then hydrate metadata per app ID for accurate filtering.
- **Buffered writes:** accumulate `BATCH_SIZE` app IDs before persistence to reduce file and network write churn.
- **Deduplication-first mindset:** previously seen IDs are loaded from local output and Google Sheets before each run.
- **Fail-soft network strategy:** API exceptions are swallowed per task to keep the pipeline progressing.

> [!IMPORTANT]
> Individual request errors do not stop collection; failures are summarized by operation and exception type at the end of each cycle.

### Pipeline Diagram

```mermaid
flowchart TD
    A[Start process] --> B[Load seen app IDs from games.txt]
    B --> C{Google Sheets enabled?}
    C -- Yes --> D[Load existing URLs from column A]
    C -- No --> E[Generate randomized queries]
    D --> E
    E --> F[Run search queries across locales in parallel]
    F --> G[Collect candidate app IDs]
    G --> H[Fetch app details in parallel]
    H --> I{Is game and within install range?}
    I -- No --> J[Discard]
    I -- Yes --> K[Append to in-memory buffer]
    K --> L{Buffer >= BATCH_SIZE?}
    L -- No --> M[Continue loop]
    L -- Yes --> N[Write URLs to games.txt]
    N --> O{Google Sheets writer active?}
    O -- Yes --> P[Append deduplicated URLs to column A]
    O -- No --> M
    P --> M
    M --> E
```

## Getting Started

### Prerequisites

- Python `3.10+` (recommended: latest stable Python 3.x)
- Internet connectivity for Google Play scraping endpoints
- (Optional) Google Cloud service account JSON with Sheets API access
- (Optional) A Google Sheet shared with the service account email

### Installation

```bash
git clone https://github.com/OstinUA/random-google-play-game-scraper.git
cd random-google-play-game-scraper
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

> [!WARNING]
> Do not commit `service_account.json` with real credentials into public repositories.

## Testing

Run the unit tests and syntax checks with:

```bash
python -m unittest discover -s tests -v
python -m compileall main.py settings.py sheet.py tests
```

Use a single discovery cycle for a bounded runtime check:

```bash
python main.py --once --no-sheets
```

The default invocation runs continuously. Use `--no-sheets` to skip Google Sheets authentication.

## Deployment

### Production Execution Guidance

- Run the process in a supervised environment (`systemd`, Docker, or process manager).
- Mount a persistent volume for `games.txt` to preserve deduplication state.
- Provide `service_account.json` as a mounted secret where possible.
- Tune concurrency (`WORKERS`) based on outbound network limits and host CPU capacity.

### Example systemd Unit

```ini
[Unit]
Description=App-Finder Google Play Game Scraper
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/random-google-play-game-scraper
ExecStart=/opt/random-google-play-game-scraper/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Containerization Notes

A minimal container strategy:

1. Build from a slim Python base image.
2. Install `requirements.txt`.
3. Copy project files.
4. Set command to `python main.py`.
5. Mount credentials and output volume at runtime.

> [!CAUTION]
> High worker counts can trigger transient request failures or remote throttling; scale conservatively in production.

## Usage

### Basic Run

```bash
python main.py
```

Run one cycle and exit, or disable Sheets integration:

```bash
python main.py --once
python main.py --no-sheets
```

### Programmatic Example

```python
from pathlib import Path

import settings
from main import append_links, discover_by_search, iter_games, load_existing

output = Path(settings.OUTPUT_FILE)
seen = load_existing(output)
candidates = discover_by_search(seen, token_pool=[])
selected_ids = [app_id for app_id, _details in iter_games(candidates) if app_id not in seen]
append_links(output, selected_ids)

print(f"Saved {len(selected_ids)} URLs")
```

### Graceful Shutdown

- Press `Ctrl+C` to stop.
- The process catches `KeyboardInterrupt` and flushes the buffered URLs before exiting.

## Configuration

Configuration is centralized in `settings.py`.

### Core Filters

- `MIN_INSTALLS`: lower install threshold (inclusive).
- `MAX_INSTALLS`: upper install threshold (inclusive). Set to `0` to disable the cap.

### Output and Batching

- `OUTPUT_FILE`: path to local URL output file.
- `BATCH_SIZE`: number of app IDs buffered before a write flush.

### Search Throughput

- `QUERIES_PER_RUN`: randomized query count per cycle.
- `SEARCH_LIMIT`: max results requested per search query.
- `WORKERS`: parallel worker count for search/details phases.
- `SEARCH_LOCALES`: list of `(lang, country)` tuples for international query coverage.

### Google Sheets Integration

- `GOOGLE_SHEET_ENABLED`: master flag for Sheets sync.
- `GOOGLE_SHEET_URL`: sheet URL or raw spreadsheet ID.
- `GOOGLE_SHEET_TAB`: worksheet index (0-based).
- `SERVICE_ACCOUNT_FILE`: path to service account JSON key file.

### Example `settings.py`

```python
MIN_INSTALLS = 10_000
MAX_INSTALLS = 100_000
OUTPUT_FILE = "games.txt"
BATCH_SIZE = 10
QUERIES_PER_RUN = 20
SEARCH_LIMIT = 60
WORKERS = 20

GOOGLE_SHEET_ENABLED = True
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit"
GOOGLE_SHEET_TAB = 0
SERVICE_ACCOUNT_FILE = "service_account.json"

SEARCH_LOCALES = [
    ("en", "us"),
    ("en", "gb"),
    ("de", "de"),
]
```

## License

This project is distributed under the **MIT License**. See [`LICENSE`](LICENSE) for full legal terms.

## Support the Project

[![Patreon](https://img.shields.io/badge/Patreon-OstinFCT-f96854?style=flat-square&logo=patreon)](https://www.patreon.com/OstinFCT)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-fctostin-29abe0?style=flat-square&logo=ko-fi)](https://ko-fi.com/fctostin)
[![Boosty](https://img.shields.io/badge/Boosty-Support-f15f2c?style=flat-square)](https://boosty.to/ostinfct)
[![YouTube](https://img.shields.io/badge/YouTube-FCT--Ostin-red?style=flat-square&logo=youtube)](https://www.youtube.com/@FCT-Ostin)
[![Telegram](https://img.shields.io/badge/Telegram-FCTostin-2ca5e0?style=flat-square&logo=telegram)](https://t.me/FCTostin)

If you find this tool useful, consider leaving a star on GitHub or supporting the author directly.
