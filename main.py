import argparse
import random
import re
import sys
import threading
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Iterator, TypeVar
from urllib.parse import parse_qs, urlsplit

import settings


_T = TypeVar("_T")
_R = TypeVar("_R")
_NETWORK_FAILURES: Counter[str] = Counter()
_NETWORK_FAILURES_LOCK = threading.Lock()


PLAY_URL = "https://play.google.com/store/apps/details?id={app_id}"

# ---------------------------------------------------------------------------
# Query token filtering
# ---------------------------------------------------------------------------
# Exclude common filler and store terminology from dynamically generated queries.
STOPWORDS = {
    # Articles, pronouns, conjunctions, prepositions
    "the", "and", "for", "with", "your", "from", "this", "that", "they",
    "them", "their", "there", "these", "those", "what", "when", "where",
    "while", "which", "will", "would", "could", "should", "been", "being",
    "more", "most", "some", "such", "into", "onto", "over", "under", "than",
    "then", "also", "even", "just", "only", "very", "much", "many", "each",
    "every", "both", "either", "neither", "another", "other", "about",
    "after", "before", "between", "through", "without", "within", "across",
    "around", "behind", "beyond", "during", "against",
    # Auxiliary verbs / common verbs
    "are", "was", "were", "have", "has", "had", "its", "you", "yours",
    "all", "any", "can", "may", "must", "shall", "did", "does", "doing",
    "make", "made", "take", "took", "come", "came", "give", "gave", "get",
    "got", "see", "saw", "say", "said", "use", "used", "try", "tried",
    "want", "need", "know", "feel", "look", "find", "show", "help",
    # App / store boilerplate
    "new", "free", "game", "games", "play", "playing", "edition", "version",
    "lite", "pro", "plus", "vip", "mod", "offline", "online", "premium",
    "deluxe", "ultimate", "official", "original", "classic",
    "app", "apps", "top", "best", "fun", "real", "world", "super",
    "download", "install", "update", "feature", "features", "store",
    "experience", "enjoy", "discover", "everyone", "anyone", "anywhere",
    "anytime", "available", "exclusive", "limited", "special",
    # Gaming jargon that doesn't carve out useful niches on its own
    "tap", "click", "swipe", "drag", "drop", "level", "levels", "score",
    "scores", "high", "easy", "hard", "simple", "amazing", "awesome",
    "exciting", "addictive", "challenging", "endless", "epic", "ultimate",
    "gameplay", "graphics", "controls", "modes", "mode", "stage", "stages",
    "mission", "missions", "achievements", "rewards", "bonus", "daily",
    "weekly", "event", "events", "season", "ranked", "rank",
    # Generic adjectives
    "good", "great", "nice", "fine", "cool", "neat", "clean", "smooth",
    "perfect", "incredible", "fantastic", "wonderful", "beautiful",
    "stunning", "gorgeous",
    # Numbers spelled out / ordinals
    "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "first", "second", "third", "next", "last", "final",
    # Time
    "now", "today", "tomorrow", "year", "years", "month", "week", "day",
    "hour", "minute", "second", "moment",
    # Misc filler
    "please", "thanks", "welcome", "hello", "ready", "start", "begin",
    "play", "pause", "stop", "exit", "menu", "screen", "page",
}

# How many cycles before resetting seen_tokens to allow re-extraction
# of words from games found in earlier rounds.
TOKEN_RESET_EVERY = 15


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------
# Build broad and long-tail searches from the curated seed vocabulary.
# Preserve source order while removing duplicate terms from configuration.
SEED_POOL: tuple[str, ...] = tuple(dict.fromkeys(settings.SEED_WORDS))


@contextmanager
def _pool(workers: int | None = None):
    """Cancel queued work on interruption without waiting for network calls."""
    executor = ThreadPoolExecutor(max_workers=workers or settings.WORKERS)
    try:
        yield executor
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _completed_futures(
    executor: ThreadPoolExecutor,
    function: Callable[[_T], _R],
    items: Iterable[_T],
) -> Iterator[tuple[_T, Future[_R]]]:
    """Yield results as they finish while keeping the number of queued tasks bounded."""
    iterator = iter(items)
    pending: dict[Future[_R], _T] = {}
    limit = max(1, settings.WORKERS) * 2

    def submit_next() -> bool:
        try:
            item = next(iterator)
        except StopIteration:
            return False
        pending[executor.submit(function, item)] = item
        return True

    for _ in range(limit):
        if not submit_next():
            break

    while pending:
        completed, _ = wait(pending, return_when=FIRST_COMPLETED)
        for future in completed:
            item = pending.pop(future)
            yield item, future
            submit_next()


_progress_width = 0
_progress_enabled = getattr(sys.stdout, "isatty", lambda: False)()


def _progress(text: str, end: bool = False) -> None:
    """Render an in-place progress line in terminals and concise lines in logs."""
    global _progress_width
    if _progress_enabled:
        print(text.ljust(_progress_width), end="\n" if end else "\r", flush=True)
        _progress_width = 0 if end else max(_progress_width, len(text))
    elif end:
        print(text, flush=True)


def _line(text: str) -> None:
    """Print a normal line, clearing any in-place progress display first."""
    global _progress_width
    if _progress_enabled:
        print(text.ljust(_progress_width))
    else:
        print(text)
    _progress_width = 0


def _record_network_failure(operation: str, error: Exception) -> None:
    key = f"{operation}/{type(error).__name__}"
    with _NETWORK_FAILURES_LOCK:
        _NETWORK_FAILURES[key] += 1


def _report_network_failures() -> None:
    with _NETWORK_FAILURES_LOCK:
        failures = dict(_NETWORK_FAILURES)
        _NETWORK_FAILURES.clear()
    if failures:
        summary = ", ".join(f"{name}: {count}" for name, count in sorted(failures.items()))
        _line(f"  Network failures this cycle: {summary}")


def random_query() -> str:
    pool = SEED_POOL
    # Distribution: heavy on single words for breadth, but ~half the queries are
    # 2-3 word combos that target the long tail.
    style = random.choices(
        ["single", "double", "triple"],
        weights=[5, 3, 2],
        k=1,
    )[0]
    if style == "single":
        return random.choice(pool)
    if style == "double":
        return f"{random.choice(pool)} {random.choice(pool)}"
    return f"{random.choice(pool)} {random.choice(pool)} {random.choice(pool)}"


def parse_installs(value) -> int:
    if not value:
        return 0
    try:
        return int(str(value).replace(",", "").replace("+", "").strip())
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Network access
# ---------------------------------------------------------------------------
# Keep individual request failures isolated and report aggregate counts per cycle.
def fetch_search(query: str, lang: str, country: str, limit: int) -> list:
    try:
        from google_play_scraper import search

        return search(query, lang=lang, country=country, n_hits=limit)
    except Exception as error:
        _record_network_failure("search", error)
        return []


def fetch_details(app_id: str, lang: str = "en", country: str = "us") -> dict | None:
    try:
        from google_play_scraper import app as get_app_details

        return get_app_details(app_id, lang=lang, country=country)
    except Exception as error:
        _record_network_failure("details", error)
        return None


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------
# Restrict search tokens to useful alphabetic terms and exclude stopwords.
_VALID_TOKEN = re.compile(r"^[a-z]{4,15}$")


def is_valid_token(word: str) -> bool:
    return bool(_VALID_TOKEN.match(word)) and word not in STOPWORDS


def tokens_of(details: dict) -> tuple[str, ...]:
    """Return unique valid tokens from a listing's title and summary."""
    title = details.get("title")
    summary = details.get("summary")
    text = f"{title if isinstance(title, str) else ''} {summary if isinstance(summary, str) else ''}"
    words = (word.lower() for word in re.findall(r"[A-Za-z]+", text))
    return tuple(dict.fromkeys(word for word in words if is_valid_token(word)))


def extract_tokens(
    app_ids: list[str],
    seen_tokens: set[str],
    token_cache: dict[str, tuple[str, ...]],
) -> list[str]:
    """Sample known app IDs and harvest tokens not yet in the pool.

    Every game we match already had its details fetched by iter_games, so its
    tokens are cached; only IDs carried over from a previous run (loaded from
    games.txt / the sheet) need a network round trip. That makes the periodic
    re-extraction after a token-filter reset essentially free.
    """
    if not app_ids:
        return []

    sample = random.sample(app_ids, min(50, len(app_ids)))
    missing = [aid for aid in sample if aid not in token_cache]

    if missing:
        with _pool() as executor:
            for app_id, future in _completed_futures(executor, fetch_details, missing):
                details = future.result()
                token_cache[app_id] = tokens_of(details) if details else ()

    new_tokens: list[str] = []
    for aid in sample:
        for w in token_cache.get(aid, ()):
            if w in seen_tokens:
                continue
            seen_tokens.add(w)
            new_tokens.append(w)
    return new_tokens


# ---------------------------------------------------------------------------
# Shared search-task runner — every discovery routine funnels through here so
# concurrency, error handling, and progress reporting are uniform.
# ---------------------------------------------------------------------------
def _run_search_tasks(
    tasks: list[tuple[str, str, str]],
    seen: set[str],
    label: str | None = None,
    limit: int | None = None,
) -> list[str]:
    if not tasks:
        return []
    n_hits = settings.SEARCH_LIMIT if limit is None else limit
    if n_hits < 1:
        return []
    total = len(tasks)
    done = 0
    if label:
        _progress(f"  {label}: 0/{total}")

    ids: dict[str, None] = {}

    def search_task(task: tuple[str, str, str]) -> list:
        return fetch_search(task[0], task[1], task[2], n_hits)

    with _pool() as executor:
        for _task, future in _completed_futures(executor, search_task, tasks):
            for item in future.result():
                if not isinstance(item, dict):
                    continue
                aid = item.get("appId")
                if isinstance(aid, str) and _APP_ID.fullmatch(aid) and aid not in seen:
                    ids[aid] = None
            done += 1
            if label:
                _progress(f"  {label}: {done}/{total} (found: {len(ids)})", end=done == total)
    return list(ids)


# ---------------------------------------------------------------------------
# Discovery routines
# ---------------------------------------------------------------------------

def discover_by_search(seen: set[str], token_pool: list[str]) -> list[str]:
    """Discover candidates through randomized keyword searches.

    Builds queries from a 50/50 mix of (a) dynamic tokens harvested from
    titles/summaries of already-found games and (b) random_query() draws from
    the curated SEED_WORDS list (single + long-tail combos). Each query runs
    against a random subset of the broad SEARCH_LOCALES so soft-launched
    titles in Tier-2/3 markets get surfaced.
    """
    half = max(1, settings.QUERIES_PER_RUN // 2)

    # Drain the token pool — keeps it shrinking so extract_tokens runs again.
    consumed: list[str] = []
    while token_pool and len(consumed) < half:
        consumed.append(token_pool.pop())
    queries = list(dict.fromkeys(consumed))
    query_set = set(queries)
    target = max(0, settings.QUERIES_PER_RUN)
    attempts = 0
    max_attempts = max(100, target * 10)
    while len(queries) < target and attempts < max_attempts:
        attempts += 1
        query = random_query()
        if query not in query_set:
            query_set.add(query)
            queries.append(query)

    locales = random.sample(settings.SEARCH_LOCALES, k=min(4, len(settings.SEARCH_LOCALES)))
    tasks = [(query, lang, country) for query in queries for lang, country in locales]

    return _run_search_tasks(tasks, seen, label="search")


def _spider_locales() -> list[tuple[str, str]]:
    return random.sample(settings.SEARCH_LOCALES, k=min(2, len(settings.SEARCH_LOCALES)))


def developer_queries(app_details: dict) -> list[str]:
    """Return the query used to find other listings from the same developer.

    google-play-scraper has no first-class developer-listing endpoint, so we
    approximate: search the developer's name and verify each candidate's
    `developerId` afterwards (see discover_by_spider).
    """
    developer = app_details.get("developer")
    developer_id = app_details.get("developerId")
    if (
        not isinstance(developer, str)
        or not developer.strip()
        or not isinstance(developer_id, str)
        or not developer_id
    ):
        return []
    return [developer.strip()]


def similar_queries(app_details: dict) -> list[str]:
    """Build search queries for listings in the same genre and title niche.

    google-play-scraper does not expose a `similar(app_id)` endpoint either, so
    we approximate it: take the most distinctive non-stopword tokens from the
    matched game's title and pair them with its `genre`. Searching that
    combination tightly clusters games in the same niche.
    """
    title_value = app_details.get("title")
    genre_value = app_details.get("genre")
    title = title_value if isinstance(title_value, str) else ""
    genre = genre_value.lower().strip() if isinstance(genre_value, str) else ""

    title_tokens = [
        t.lower()
        for t in re.findall(r"[A-Za-z]{4,15}", title)
        if t.lower() not in STOPWORDS
    ]

    queries: dict[str, None] = {}
    for tok in title_tokens[:3]:
        queries[f"{tok} {genre}" if genre else tok] = None
        queries[tok] = None
    return list(queries)


def discover_by_spider(matched: list[tuple[str, dict]], seen: set[str]) -> tuple[list[str], dict[str, dict]]:
    """Depth-1 spider over every freshly matched game, in two batched waves.

    Fanning out per game meant one thread pool (and one serialized round trip)
    per match; here all developer queries run in a single wave and all
    similar-niche queries in another, so a cycle with 30 matches costs two waves
    instead of sixty. Returns the candidate IDs plus any details already
    fetched during developer verification, so the filter pass can reuse them.
    """
    dev_tasks: dict[tuple[str, str, str], None] = {}
    sim_tasks: dict[tuple[str, str, str], None] = {}
    developer_ids: set[str] = set()

    for _aid, details in matched:
        locales = _spider_locales()
        for q in developer_queries(details):
            developer_ids.add(details["developerId"])
            for lang, country in locales:
                dev_tasks[(q, lang, country)] = None
        for q in similar_queries(details):
            for lang, country in locales:
                sim_tasks[(q, lang, country)] = None

    candidates: dict[str, None] = {}
    prefetched: dict[str, dict] = {}

    # Wave 1 — developer names, then verify developerId on each candidate.
    dev_raw = _run_search_tasks(list(dev_tasks), seen, limit=settings.SPIDER_LIMIT)
    # Same bound as before the batching: at most SPIDER_LIMIT verifications per match.
    dev_raw = dev_raw[: settings.SPIDER_LIMIT * max(1, len(matched))]
    if dev_raw:
        with _pool() as executor:
            for aid, future in _completed_futures(executor, fetch_details, dev_raw):
                details = future.result()
                if details and details.get("developerId") in developer_ids:
                    candidates[aid] = None
                    prefetched[aid] = details

    # Wave 2 — similar-niche searches; no verification needed.
    for aid in _run_search_tasks(list(sim_tasks), seen, limit=settings.SPIDER_LIMIT):
        candidates[aid] = None

    return list(candidates), prefetched


def discover_by_category(seen: set[str]) -> list[str]:
    """Discover candidates through game-category seed searches.

    Iterates the GAME_* category map in settings, picks one (sometimes two)
    seed keyword per category, and runs them across multiple locales. Surfaces
    trending titles in each genre that single-token text search rarely hits.
    """
    queries: dict[str, None] = {}
    for keywords in settings.CATEGORY_SEEDS.values():
        queries.setdefault(random.choice(keywords), None)
    # Add a "new" suffix variant for a subset to bias toward fresh listings —
    # standing in for the missing top-new-free chart endpoint.
    sample_cats = random.sample(
        list(settings.CATEGORY_SEEDS.values()),
        k=min(5, len(settings.CATEGORY_SEEDS)),
    )
    for keywords in sample_cats:
        queries.setdefault(f"{random.choice(keywords)} new", None)

    locales = random.sample(settings.SEARCH_LOCALES, k=min(4, len(settings.SEARCH_LOCALES)))
    tasks = [(query, lang, country) for query in queries for lang, country in locales]
    return _run_search_tasks(tasks, seen, label="category")


# ---------------------------------------------------------------------------
# Filter pipeline — yields (app_id, details) tuples so callers can spider
# without a second details fetch.
# ---------------------------------------------------------------------------
def is_wanted(details: dict) -> bool:
    genre_value = details.get("genre")
    genre_id_value = details.get("genreId")
    genre = genre_value.lower() if isinstance(genre_value, str) else ""
    genre_id = genre_id_value.upper() if isinstance(genre_id_value, str) else ""
    if "game" not in genre and not genre_id.startswith("GAME"):
        return False

    installs = parse_installs(details.get("installs"))
    if installs < settings.MIN_INSTALLS:
        return False
    if settings.MAX_INSTALLS and installs > settings.MAX_INSTALLS:
        return False
    return True


def iter_games(app_ids: list[str], prefetched: dict[str, dict] | None = None):
    """Yield (app_id, details) for candidates that pass the filters.

    `prefetched` lets callers hand over details they already fetched (the
    developer spider verifies `developerId`, which needs the full listing
    anyway) so the same page isn't downloaded twice in one cycle.
    """
    prefetched = prefetched or {}
    app_ids = list(dict.fromkeys(app_ids))
    total = len(app_ids)
    done = 0
    found = 0
    _progress(f"  details: 0/{total}")

    for app_id in app_ids:
        details = prefetched.get(app_id)
        if details is not None:
            done += 1
            if is_wanted(details):
                found += 1
                yield app_id, details

    pending = [app_id for app_id in app_ids if app_id not in prefetched]
    with _pool() as executor:
        for app_id, future in _completed_futures(executor, fetch_details, pending):
            details = future.result()
            done += 1
            _progress(f"  details: {done}/{total} (matched: {found})")

            if details and is_wanted(details):
                found += 1
                yield app_id, details

    _progress(f"  details: {done}/{total} (matched: {found})", end=True)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
_APP_ID = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")


def _app_id_from_url(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.lower() != "play.google.com":
        return None
    app_id = parse_qs(parsed.query).get("id", [None])[0]
    return app_id if app_id and _APP_ID.fullmatch(app_id) else None


def load_existing(path: Path) -> set[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return set()
    return {app_id for line in lines if (app_id := _app_id_from_url(line))}


def append_links(path: Path, app_ids: list[str]) -> None:
    valid_ids = list(dict.fromkeys(
        app_id for app_id in app_ids
        if isinstance(app_id, str) and _APP_ID.fullmatch(app_id)
    ))
    if not valid_ids:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.writelines(PLAY_URL.format(app_id=app_id) + "\n" for app_id in valid_ids)


def init_sheet(enabled: bool = True):
    if not (enabled and settings.GOOGLE_SHEET_ENABLED and settings.GOOGLE_SHEET_URL):
        return None
    try:
        from sheet import SheetWriter

        writer = SheetWriter(
            settings.GOOGLE_SHEET_URL,
            settings.SERVICE_ACCOUNT_FILE,
            settings.GOOGLE_SHEET_TAB,
        )
        print(f"Google Sheet: {len(writer.existing)} existing values, next row {writer.next_row}")
        return writer
    except Exception as error:
        print(f"Google Sheets integration unavailable ({type(error).__name__}). Local output remains enabled.")
        return None


def _validate_settings() -> None:
    if settings.WORKERS < 1:
        raise ValueError("WORKERS must be greater than zero.")
    if settings.BATCH_SIZE < 1:
        raise ValueError("BATCH_SIZE must be greater than zero.")
    if settings.QUERIES_PER_RUN < 0 or settings.SEARCH_LIMIT < 1:
        raise ValueError("Query count must be non-negative and search limit must be positive.")
    if settings.MIN_INSTALLS < 0 or settings.MAX_INSTALLS < 0:
        raise ValueError("Install thresholds cannot be negative.")
    if settings.MAX_INSTALLS and settings.MAX_INSTALLS < settings.MIN_INSTALLS:
        raise ValueError("MAX_INSTALLS must be zero or greater than or equal to MIN_INSTALLS.")
    if settings.CATEGORY_INTERVAL < 0:
        raise ValueError("CATEGORY_INTERVAL cannot be negative.")
    if settings.SPIDER_ENABLED and settings.SPIDER_LIMIT < 1:
        raise ValueError("SPIDER_LIMIT must be greater than zero when spidering is enabled.")
    if settings.QUERIES_PER_RUN and (not SEED_POOL or not settings.SEARCH_LOCALES):
        raise ValueError("Seed words and search locales are required when searching is enabled.")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def main(max_cycles: int | None = None, use_sheets: bool = True) -> None:
    _validate_settings()
    if max_cycles is not None and max_cycles < 1:
        raise ValueError("max_cycles must be greater than zero when provided.")

    output = Path(settings.OUTPUT_FILE)
    seen = load_existing(output)

    sheet = init_sheet(enabled=use_sheets)
    if sheet:
        sheet_ids = {
            app_id for url in sheet.existing
            if (app_id := _app_id_from_url(url))
        }
        seen.update(sheet_ids)

        local_links = [PLAY_URL.format(app_id=app_id) for app_id in load_existing(output)]
        missing_links = [link for link in local_links if link not in sheet.existing]
        for offset in range(0, len(missing_links), 500):
            try:
                sheet.append(missing_links[offset:offset + 500])
            except Exception as error:
                print(f"Google Sheets recovery sync failed ({type(error).__name__}); it will retry on a later run.")
                break
        else:
            if missing_links:
                print(f"Google Sheets recovery sync: {len(missing_links)} local links checked.")

    print(f"Already saved: {len(seen)}")
    print(f"Writing to {output}{' + Google Sheets' if sheet else ''}. Stop with Ctrl+C.\n")

    token_pool: list[str] = []
    seen_tokens: set[str] = set(STOPWORDS)
    known_ids: list[str] = list(seen)
    token_cache: dict[str, tuple[str, ...]] = {}

    buffer: list[str] = []
    sheet_backlog: list[str] = []  # links a failed sheet write still owes
    total_saved = 0
    cycle = 0

    def flush() -> None:
        nonlocal total_saved
        buffered_count = len(buffer)
        if buffered_count:
            append_links(output, buffer)
            if sheet:
                sheet_backlog.extend(PLAY_URL.format(app_id=app_id) for app_id in buffer)
            total_saved += buffered_count
            buffer.clear()

        if not buffered_count and not (sheet and sheet_backlog):
            return

        message = f"  + txt: {buffered_count}"
        if sheet and sheet_backlog:
            try:
                added = sheet.append(sheet_backlog)
                sheet_backlog.clear()
                message += f", sheet: {added}"
            except Exception as error:
                message += f", sheet retry pending ({len(sheet_backlog)} links; {type(error).__name__})"
        _line(f"{message} (session total: {total_saved})")

    def process(candidates: list[str], prefetched: dict[str, dict] | None = None) -> list[tuple[str, dict]]:
        """Run candidates through filtering, save matches, return matched details."""
        matched: list[tuple[str, dict]] = []
        if not candidates:
            return matched
        for aid, details in iter_games(candidates, prefetched):
            if aid in seen:
                continue
            seen.add(aid)
            known_ids.append(aid)
            token_cache[aid] = tokens_of(details)  # details are in hand — reuse later
            buffer.append(aid)
            matched.append((aid, details))
            if len(buffer) >= settings.BATCH_SIZE:
                flush()
        return matched

    try:
        while max_cycles is None or cycle < max_cycles:
            cycle += 1

            # Periodic token-filter reset so games found earlier can re-contribute
            # tokens (their titles may yield new words after the pool turned over).
            if cycle % TOKEN_RESET_EVERY == 0:
                seen_tokens.clear()
                seen_tokens.update(STOPWORDS)
                print(f"  [cycle {cycle}] token filter reset — ready for re-extraction")

            if len(token_pool) < settings.QUERIES_PER_RUN and known_ids:
                print(f"  [cycle {cycle}] extracting tokens from {min(50, len(known_ids))} known games...")
                new_tokens = extract_tokens(known_ids, seen_tokens, token_cache)
                token_pool.extend(new_tokens)
                print(f"  token pool: {len(token_pool)} (+{len(new_tokens)} new)")

            print(f"[Cycle {cycle}] discovery (pool: {len(token_pool)}, seen: {len(seen)})")

            # 1. Primary keyword search
            search_candidates = discover_by_search(seen, token_pool)
            print(f"  search candidates: {len(search_candidates)}")

            # 2. Periodic category sweep — runs alongside search every Nth cycle
            if settings.CATEGORY_INTERVAL and cycle % settings.CATEGORY_INTERVAL == 0:
                try:
                    cat_candidates = discover_by_category(seen)
                    print(f"  category candidates: {len(cat_candidates)}")
                    merged = dict.fromkeys(search_candidates)
                    merged.update(dict.fromkeys(cat_candidates))
                    search_candidates = list(merged)
                except Exception as error:
                    print(f"  Category discovery failed ({type(error).__name__}); continuing.")

            if not search_candidates:
                _report_network_failures()
                continue

            # 3. Filter primary candidates
            matched = process(search_candidates)

            # 4. Spider into developer + similar for each freshly matched game
            if settings.SPIDER_ENABLED and matched:
                try:
                    spider_pool, spider_details = discover_by_spider(matched, seen)
                except Exception as error:
                    print(f"  Spider discovery failed ({type(error).__name__}); continuing.")
                    spider_pool, spider_details = [], {}

                if spider_pool:
                    print(f"  spider candidates: {len(spider_pool)}")
                    # Spider-discovered matches are not expanded again during the same cycle.
                    process(spider_pool, spider_details)

            _report_network_failures()

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        flush()
        print(f"Done. Session total: {total_saved}.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover and save Google Play games.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single discovery cycle and exit.",
    )
    parser.add_argument(
        "--no-sheets",
        action="store_true",
        help="Skip Google Sheets authentication and synchronization.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    main(max_cycles=1 if arguments.once else None, use_sheets=not arguments.no_sheets)
