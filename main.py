# main.py
import re
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from google_play_scraper import app as get_app_details
from google_play_scraper import search

import settings


PLAY_URL = "https://play.google.com/store/apps/details?id={app_id}"

# ---------------------------------------------------------------------------
# Stopwords (TASK 6)
# ---------------------------------------------------------------------------
# Significantly expanded. Keeps generic English fillers, app/store boilerplate
# ("free", "edition", "update", "experience"), generic gaming jargon
# ("level", "score", "gameplay"), and small/junk tokens out of the dynamic
# token pool so extracted queries actually carry signal.
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
# Query generation (TASKS 3 + 4)
# ---------------------------------------------------------------------------
# Replaces the prior random_query() that produced "letters/syllable/double_syllable".
# Now draws from the curated SEED_WORDS list — every query is at least a real
# word — and occasionally combines 2-3 tokens into a long-tail phrase to dodge
# popular single-word results that exceed MAX_INSTALLS.

# SEED_WORDS contains a few accidental repeats ("tower", "stack", "shoot", ...)
# which would make random.choice() favour them. Dedupe once at import, keeping
# the original order so the wordlist stays readable/editable in settings.py.
SEED_POOL: tuple[str, ...] = tuple(dict.fromkeys(settings.SEED_WORDS))


@contextmanager
def _pool(workers: int | None = None):
    """Thread pool that drops queued work on Ctrl+C instead of draining it.

    A plain `with ThreadPoolExecutor(...)` blocks on exit until every queued
    future has run, so interrupting a cycle with hundreds of pending requests
    could take minutes. Here only the in-flight requests finish.
    """
    executor = ThreadPoolExecutor(max_workers=workers or settings.WORKERS)
    try:
        yield executor
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


_progress_width = 0


def _progress(text: str, end: bool = False) -> None:
    """Single-line progress output, padded so shorter lines don't leave debris."""
    global _progress_width
    print(text.ljust(_progress_width), end="\n" if end else "\r", flush=True)
    _progress_width = 0 if end else max(_progress_width, len(text))


def _line(text: str) -> None:
    """Print a normal line, overwriting any progress line left hanging."""
    global _progress_width
    print(text.ljust(_progress_width))
    _progress_width = 0


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
# Network primitives — every call swallows exceptions and returns an empty /
# None result so a transient timeout or rate-limit never crashes the main loop.
# ---------------------------------------------------------------------------
def fetch_search(query: str, lang: str, country: str, limit: int) -> list:
    try:
        return search(query, lang=lang, country=country, n_hits=limit)
    except Exception:
        return []


def fetch_details(app_id: str, lang: str = "en", country: str = "us") -> dict | None:
    try:
        return get_app_details(app_id, lang=lang, country=country)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Token extraction (TASK 6)
# ---------------------------------------------------------------------------
# Stricter validation: alphabetic-only, 4-15 letters, lowercase, not in
# the (now much larger) stopword set. Numbers, punctuation, and very short
# or absurdly long strings never enter the pool.
_VALID_TOKEN = re.compile(r"^[a-z]{4,15}$")


def is_valid_token(word: str) -> bool:
    return bool(_VALID_TOKEN.match(word)) and word not in STOPWORDS


def tokens_of(details: dict) -> tuple[str, ...]:
    """Unique valid tokens from a listing's title + summary, in order."""
    text = (details.get("title") or "") + " " + (details.get("summary") or "")
    words = (w.lower() for w in re.findall(r"[A-Za-z]+", text))
    return tuple(dict.fromkeys(w for w in words if is_valid_token(w)))


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
            futures = {executor.submit(fetch_details, aid): aid for aid in missing}
            for future in as_completed(futures):
                details = future.result()
                token_cache[futures[future]] = tokens_of(details) if details else ()

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
    n_hits = limit or settings.SEARCH_LIMIT
    total = len(tasks)
    done = 0
    if label:
        _progress(f"  {label}: 0/{total}")

    ids: dict[str, None] = {}  # ordered set — dedupe as we go
    with _pool() as executor:
        futures = [
            executor.submit(fetch_search, q, lang, country, n_hits)
            for q, lang, country in tasks
        ]
        for future in as_completed(futures):
            for item in future.result():
                aid = item.get("appId")
                if aid and aid not in seen:
                    ids[aid] = None
            done += 1
            if label:
                _progress(f"  {label}: {done}/{total} (found: {len(ids)})", end=done == total)
    return list(ids)


# ---------------------------------------------------------------------------
# DISCOVERY ROUTINES (modular per requirements)
# ---------------------------------------------------------------------------

def discover_by_search(seen: set[str], token_pool: list[str]) -> list[str]:
    """Primary keyword-search discovery (TASKS 3 + 4 + 7).

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
    pool_queries = set(consumed)

    rand_queries = {random_query() for _ in range(settings.QUERIES_PER_RUN - len(pool_queries))}
    queries = pool_queries | rand_queries

    locales = random.sample(settings.SEARCH_LOCALES, k=min(4, len(settings.SEARCH_LOCALES)))
    tasks = [(q, lang, country) for q in queries for lang, country in locales]

    return _run_search_tasks(tasks, seen, label="search")


def _spider_locales() -> list[tuple[str, str]]:
    return random.sample(settings.SEARCH_LOCALES, k=min(2, len(settings.SEARCH_LOCALES)))


def developer_queries(app_details: dict) -> list[str]:
    """Queries for more-by-this-developer spidering (TASK 1).

    google-play-scraper has no first-class developer-listing endpoint, so we
    approximate: search the developer's name and verify each candidate's
    `developerId` afterwards (see discover_by_spider).
    """
    if not app_details.get("developer") or not app_details.get("developerId"):
        return []
    return [app_details["developer"]]


def similar_queries(app_details: dict) -> list[str]:
    """Queries for similar / related apps expansion (TASK 2).

    google-play-scraper does not expose a `similar(app_id)` endpoint either, so
    we approximate it: take the most distinctive non-stopword tokens from the
    matched game's title and pair them with its `genre`. Searching that
    combination tightly clusters games in the same niche.
    """
    title = app_details.get("title") or ""
    genre = (app_details.get("genre") or "").lower().strip()

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
            futures = {executor.submit(fetch_details, aid): aid for aid in dev_raw}
            for future in as_completed(futures):
                aid = futures[future]
                d = future.result()
                if d and d.get("developerId") in developer_ids:
                    candidates[aid] = None
                    prefetched[aid] = d

    # Wave 2 — similar-niche searches; no verification needed.
    for aid in _run_search_tasks(list(sim_tasks), seen, limit=settings.SPIDER_LIMIT):
        candidates[aid] = None

    return list(candidates), prefetched


def discover_by_category(seen: set[str]) -> list[str]:
    """Category / top-chart discovery (TASK 5).

    Iterates the GAME_* category map in settings, picks one (sometimes two)
    seed keyword per category, and runs them across multiple locales. Surfaces
    trending titles in each genre that single-token text search rarely hits.
    """
    queries: set[str] = set()
    for keywords in settings.CATEGORY_SEEDS.values():
        queries.add(random.choice(keywords))
    # Add a "new" suffix variant for a subset to bias toward fresh listings —
    # standing in for the missing top-new-free chart endpoint.
    sample_cats = random.sample(
        list(settings.CATEGORY_SEEDS.values()),
        k=min(5, len(settings.CATEGORY_SEEDS)),
    )
    for keywords in sample_cats:
        queries.add(f"{random.choice(keywords)} new")

    locales = random.sample(settings.SEARCH_LOCALES, k=min(4, len(settings.SEARCH_LOCALES)))
    tasks = [(q, lang, country) for q in queries for lang, country in locales]
    return _run_search_tasks(tasks, seen, label="category")


# ---------------------------------------------------------------------------
# Filter pipeline — yields (app_id, details) tuples so callers can spider
# without a second details fetch.
# ---------------------------------------------------------------------------
def is_wanted(details: dict) -> bool:
    genre = (details.get("genre") or "").lower()
    genre_id = (details.get("genreId") or "").upper()
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
    total = len(app_ids)
    done = len(prefetched.keys() & set(app_ids))
    found = 0
    _progress(f"  details: {done}/{total}")

    for app_id in app_ids:
        details = prefetched.get(app_id)
        if details and is_wanted(details):
            found += 1
            yield app_id, details

    pending = [aid for aid in app_ids if aid not in prefetched]
    with _pool() as executor:
        futures = {executor.submit(fetch_details, aid): aid for aid in pending}
        for future in as_completed(futures):
            app_id = futures[future]
            details = future.result()
            done += 1
            _progress(f"  details: {done}/{total} (matched: {found})")

            if details and is_wanted(details):
                found += 1
                yield app_id, details

    _progress(f"  details: {done}/{total} (matched: {found})", end=True)


# ---------------------------------------------------------------------------
# Persistence helpers (unchanged behavior)
# ---------------------------------------------------------------------------
_APP_ID = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")


def _app_id_from_url(value: str) -> str | None:
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
    valid_ids = [app_id for app_id in app_ids if _APP_ID.fullmatch(app_id)]
    if not valid_ids:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.writelines(PLAY_URL.format(app_id=app_id) + "\n" for app_id in valid_ids)


def init_sheet():
    if not (settings.GOOGLE_SHEET_ENABLED and settings.GOOGLE_SHEET_URL):
        return None
    try:
        from sheet import SheetWriter
        writer = SheetWriter(
            settings.GOOGLE_SHEET_URL,
            settings.SERVICE_ACCOUNT_FILE,
            settings.GOOGLE_SHEET_TAB,
        )
        print(f"Google Sheet: {len(writer.existing)} rows, next A{writer.next_row}")
        return writer
    except Exception as e:
        print(f"Google Sheet disabled (error): {e}")
        return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def main() -> None:
    output = Path(settings.OUTPUT_FILE)
    seen = load_existing(output)

    sheet = init_sheet()
    if sheet:
        for url in sheet.existing:
            app_id = _app_id_from_url(url)
            if app_id:
                seen.add(app_id)

    print(f"Already saved: {len(seen)}")
    print(f"Writing to {output}{' + Google Sheet' if sheet else ''}. Stop with Ctrl+C.\n")

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
        if not buffer:
            return
        append_links(output, buffer)
        msg = f"  + txt: {len(buffer)}"
        if sheet:
            # Carry links from an earlier failed write; sheet.append() dedupes,
            # so retrying can never duplicate a row.
            sheet_backlog.extend(PLAY_URL.format(app_id=aid) for aid in buffer)
            try:
                added = sheet.append(sheet_backlog)
                sheet_backlog.clear()
                msg += f", sheet: {added}"
            except Exception as e:
                msg += f", sheet error ({len(sheet_backlog)} queued for retry): {e}"
        total_saved += len(buffer)
        _line(msg + f" (session total: {total_saved})")
        buffer.clear()

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
        while True:
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
                except Exception as e:
                    # Never let one failed routine kill the loop.
                    print(f"  category discovery error: {e}")

            if not search_candidates:
                continue

            # 3. Filter primary candidates
            matched = process(search_candidates)

            # 4. Spider into developer + similar for each freshly matched game
            if settings.SPIDER_ENABLED and matched:
                try:
                    spider_pool, spider_details = discover_by_spider(matched, seen)
                except Exception as e:
                    # Never let one failed routine kill the loop.
                    print(f"  spider discovery error: {e}")
                    spider_pool, spider_details = [], {}

                if spider_pool:
                    print(f"  spider candidates: {len(spider_pool)}")
                    # depth=1 only — matches found via spidering are NOT spidered
                    # again this cycle, preventing runaway expansion.
                    process(spider_pool, spider_details)

    except KeyboardInterrupt:
        print("\nStopping...")
        flush()
        print(f"Done. Session total: {total_saved}.")


if __name__ == "__main__":
    main()
