# ---------------------------------------------------------------------------
# Install-count filters
# ---------------------------------------------------------------------------
# Persist listings whose install count falls within the configured range.
MIN_INSTALLS = 500_000
MAX_INSTALLS = 999_000_000

OUTPUT_FILE = "games.txt"

BATCH_SIZE = 10

QUERIES_PER_RUN = 20
SEARCH_LIMIT = 60
WORKERS = 20

# ---------------------------------------------------------------------------
# Discovery cadence
# ---------------------------------------------------------------------------
# Run the category sweep every N main cycles (set to 0 to disable).
CATEGORY_INTERVAL = 3

# Spider into developer + similar-apps every cycle for newly matched games.
SPIDER_ENABLED = True

# Maximum candidates to harvest per developer/similar pass per matched game.
SPIDER_LIMIT = 30

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
GOOGLE_SHEET_ENABLED = True
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1e4DgVOmWKHEVG0YlqmkYn5g2Yl6QxmggXa_ruGAtaMA/edit?gid=0#gid=0"
GOOGLE_SHEET_TAB = 0
SERVICE_ACCOUNT_FILE = "service_account.json"

# ---------------------------------------------------------------------------
# Search locales
# ---------------------------------------------------------------------------
# Include major markets and regional launch territories to broaden coverage.
SEARCH_LOCALES = [
    # English-speaking core + soft-launch markets
    ("en", "us"), ("en", "gb"), ("en", "ca"), ("en", "au"), ("en", "nz"),
    ("en", "ie"), ("en", "ph"), ("en", "in"), ("en", "sg"), ("en", "my"),
    ("en", "za"), ("en", "ng"), ("en", "ke"),
    # Slavic
    ("uk", "ua"), ("pl", "pl"),
    # Western Europe
    ("de", "de"), ("fr", "fr"), ("nl", "nl"), ("it", "it"),
    # Latin America / Iberia
    ("es", "es"), ("es", "mx"), ("es", "ar"), ("es", "co"), ("es", "cl"),
    ("pt", "br"), ("pt", "pt"),
    # Nordics
    ("sv", "se"), ("nb", "no"), ("fi", "fi"), ("da", "dk"),
    # MENA / Turkey
    ("tr", "tr"), ("ar", "sa"), ("ar", "ae"), ("ar", "eg"),
    # Asia-Pacific
    ("ja", "jp"), ("ko", "kr"), ("zh", "tw"), ("zh", "hk"),
    ("vi", "vn"), ("th", "th"), ("id", "id"), ("hi", "in"),
]

# ---------------------------------------------------------------------------
# Search seed vocabulary
# ---------------------------------------------------------------------------
# Combine genre terms, common title words, and thematic vocabulary for broad
# and long-tail query generation.
SEED_WORDS = [
    # --- Gaming genres / mechanics ---
    "idle", "tycoon", "merge", "craft", "rpg", "mmo", "moba", "shooter",
    "rogue", "soulslike", "metroidvania", "puzzle", "match", "tower",
    "defense", "battle", "royale", "survival", "horror", "stealth",
    "racing", "drift", "arcade", "platformer", "sandbox", "simulator",
    "farm", "city", "build", "builder", "empire", "kingdom", "castle",
    "dungeon", "quest", "saga", "hero", "warrior", "knight", "mage",
    "wizard", "ninja", "samurai", "pirate", "viking", "zombie", "alien",
    "robot", "monster", "dragon", "beast", "demon", "ghost", "vampire",
    "wolf", "soccer", "basketball", "football", "tennis", "golf", "cricket",
    "skate", "snowboard", "fishing", "hunting", "bowling", "boxing",
    "wrestling", "tactics", "strategy", "deck", "card", "solitaire",
    "chess", "checkers", "trivia", "quiz", "word", "crossword", "sudoku",

    # --- Combat / loot vocabulary ---
    "war", "fight", "shoot", "gun", "rifle", "sniper", "sword", "blade",
    "axe", "bow", "arrow", "shield", "armor", "magic", "spell", "potion",
    "treasure", "gold", "coin", "gem", "crystal", "diamond", "loot",
    "raid", "pvp", "pve", "boss", "arena", "stadium", "track", "circuit",

    # --- Themes / settings ---
    "space", "galaxy", "planet", "star", "cosmic", "nebula", "asteroid",
    "ocean", "island", "tropical", "desert", "forest", "jungle", "mountain",
    "arctic", "frozen", "fire", "thunder", "storm", "shadow", "neon",
    "cyber", "punk", "retro", "pixel", "voxel", "medieval", "ancient",
    "modern", "future", "vintage", "royal", "mystic", "epic", "legendary",
    "haunted", "cursed", "magical", "sacred", "forbidden",

    # --- Casual / hyper-casual verbs ---
    "color", "paint", "draw", "trace", "swipe", "pop", "smash", "blast",
    "boom", "crush", "slice", "chop", "fold", "twist", "spin", "flip",
    "jump", "race", "fly", "fall", "climb", "stack", "balance", "roll",
    "drop", "shoot", "throw", "catch", "dodge", "escape", "sneak",

    # --- Common nouns ---
    "car", "truck", "bike", "plane", "ship", "boat", "train", "rocket",
    "house", "home", "shop", "factory", "garden", "park", "school",
    "hospital", "office", "kitchen", "restaurant", "bakery", "salon",
    "animal", "cat", "dog", "horse", "tiger", "lion", "bear", "fox",
    "fish", "bird", "snake", "spider", "frog", "rabbit", "panda", "unicorn",
    "story", "tale", "legend", "myth", "chronicle", "diary", "secret",
    "doll", "pet", "baby", "princess", "prince", "queen", "emperor",
    "mafia", "thief", "spy", "detective", "agent", "soldier", "pilot",
    "chef", "doctor", "nurse", "farmer", "miner", "trucker", "trader",

    # --- Adjectives / scale ---
    "happy", "lucky", "tiny", "giant", "huge", "wild", "crazy", "silly",
    "smart", "clever", "brave", "lost", "deep", "high", "fast", "slow",
    "sweet", "rich", "bright", "shiny", "rare", "lethal", "deadly",
    "supreme", "hidden",

    # --- Activities / hobbies ---
    "cook", "bake", "fish", "hunt", "explore", "mine", "drill", "drive",
    "ride", "sail", "surf", "ski", "dance", "sing", "music", "drum",
    "piano", "guitar", "rhythm", "beat", "knit", "sew", "weave",

    # --- Numbers / shapes ---
    "tower", "stack", "pile", "chain", "line", "circle", "square", "cube",
    "ball", "block", "brick", "tile", "dot",
]

# ---------------------------------------------------------------------------
# Category search seeds
# ---------------------------------------------------------------------------
# google-play-scraper does not expose a top-charts-by-category endpoint, so
# we approximate it: each Google Play game category maps to a handful of
# seed keywords that, when searched, surface the freshly trending titles in
# that category. The orchestrator runs this every CATEGORY_INTERVAL cycles.
CATEGORY_SEEDS = {
    "GAME_ACTION":       ["action", "shooter", "combat", "war", "battle"],
    "GAME_ADVENTURE":    ["adventure", "quest", "explore", "journey"],
    "GAME_ARCADE":       ["arcade", "retro", "8bit", "classic arcade"],
    "GAME_BOARD":        ["chess", "checkers", "ludo", "monopoly", "board"],
    "GAME_CARD":         ["solitaire", "poker", "rummy", "card game"],
    "GAME_CASINO":       ["slots", "blackjack", "roulette", "vegas"],
    "GAME_CASUAL":       ["casual", "relax", "zen", "chill"],
    "GAME_EDUCATIONAL":  ["learn", "kids", "math", "alphabet", "spelling"],
    "GAME_MUSIC":        ["rhythm", "drum", "piano tap", "music game"],
    "GAME_PUZZLE":       ["puzzle", "match", "merge", "jigsaw", "brain"],
    "GAME_RACING":       ["racing", "drift", "rally", "kart", "drag race"],
    "GAME_ROLE_PLAYING": ["rpg", "knight", "mage", "dungeon", "hero"],
    "GAME_SIMULATION":   ["simulator", "tycoon", "farm", "city builder"],
    "GAME_SPORTS":       ["soccer", "basketball", "tennis", "golf", "cricket"],
    "GAME_STRATEGY":     ["strategy", "tower defense", "kingdom", "empire"],
    "GAME_TRIVIA":       ["trivia", "quiz", "iq test", "guess"],
    "GAME_WORD":         ["word", "anagram", "crossword", "spelling bee"],
}
