from __future__ import annotations

"""Core non-UI logic for the Ability Draft command builder.

This module keeps the important data and transformations separate from Tkinter:
- loading hero metadata;
- normalizing and matching hero names;
- ranking search results;
- generating the final console command string.
"""

import difflib
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

# Default timer values shown in the UI and used by command generation.
DEFAULT_TIMERS = {
    "pre_time": 5,
    "per_player_time": 2,
    "pre_round_time": 1,
}

# Standalone command used to clear any manual Ability Draft setup.
CLEAR_AD_COMMAND = "dota_gamemode_ability_draft_set_draft_hero_and_team_clear;"

# Hero metadata is stored in a JSON file at the project root.
DATA_PATH = Path(__file__).resolve().parent.parent / "hero_data.json"
HERO_DATA: List[Dict[str, object]] = json.loads(DATA_PATH.read_text(encoding="utf-8"))


def normalize_key(text: str) -> str:
    """Normalize a hero-related string into a stable comparison key.

    This is used for matching display names, aliases, and internal names in a way
    that ignores case and most punctuation differences.
    """
    text = text.lower().strip()
    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9_ ]+", " ", text)
    text = " ".join(text.split())
    return text.replace(" ", "_")


def compact_key(text: str) -> str:
    """Remove all non-alphanumeric characters for loose prefix/substring matching."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def hero_site_slug(display_name: str) -> str:
    """Convert a display name into the compact slug style used by Valve's site."""
    text = display_name.lower().strip()
    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def get_site_slug(hero: Dict[str, object]) -> str:
    """Return the explicit site slug if present, otherwise infer one from display name."""
    site_slug = str(hero.get("site_slug", "")).strip()
    if site_slug:
        return site_slug
    return hero_site_slug(str(hero["display"]))


def hero_aliases(hero: Dict[str, object]) -> List[str]:
    """Return a de-duplicated list of all names that should match a hero.

    This includes the public display name, the internal command name, the site slug,
    and any manually curated aliases in hero_data.json.
    """
    display = str(hero["display"])
    internal = str(hero["internal"])
    site_slug = get_site_slug(hero)
    aliases = [str(a) for a in hero.get("aliases", []) if str(a).strip()]
    values: List[str] = []
    seen: set[str] = set()
    for value in [display, internal, site_slug, *aliases]:
        norm = normalize_key(value)
        if norm and norm not in seen:
            seen.add(norm)
            values.append(value)
    return values


def build_search_index(hero_data: List[Dict[str, object]]) -> Tuple[Dict[str, Dict[str, object]], Dict[str, str]]:
    """Build exact-match lookup tables used by the search and fuzzy matching code."""
    direct: Dict[str, Dict[str, object]] = {}
    labels: Dict[str, str] = {}

    for hero in hero_data:
        display = str(hero["display"])
        internal = str(hero["internal"])
        site_slug = get_site_slug(hero)
        aliases = [str(a) for a in hero.get("aliases", [])]

        # Store multiple exact-match keys for convenience.
        keys = {
            normalize_key(display),
            normalize_key(internal),
            normalize_key(site_slug),
            normalize_key(display.replace("-", " ")),
            normalize_key(display.replace("'", "")),
        }

        for alias in aliases:
            if alias.strip():
                keys.add(normalize_key(alias))

        # Also allow matching without underscores, since users often type that way.
        keys.add(normalize_key(display).replace("_", ""))
        keys.add(normalize_key(internal).replace("_", ""))
        keys.add(normalize_key(site_slug).replace("_", ""))

        for key in keys:
            if not key:
                continue
            direct.setdefault(key, hero)
            labels[key] = display

    return direct, labels


SEARCH_INDEX, SEARCH_LABELS = build_search_index(HERO_DATA)
HERO_BY_INTERNAL = {str(hero["internal"]): hero for hero in HERO_DATA}


def resolve_hero_name(user_input: str) -> Tuple[Dict[str, object] | None, List[Dict[str, object]]]:
    """Resolve a hero name either exactly or by fuzzy suggestions.

    Returns:
    - (hero, []) if there is an exact match;
    - (None, [suggestions...]) if only fuzzy candidates were found.
    """
    key = normalize_key(user_input)
    if not key:
        return None, []

    if key in SEARCH_INDEX:
        return SEARCH_INDEX[key], []

    candidates = difflib.get_close_matches(key, SEARCH_LABELS.keys(), n=8, cutoff=0.5)
    seen = set()
    heroes = []
    for candidate in candidates:
        hero = SEARCH_INDEX[candidate]
        internal = str(hero["internal"])
        if internal not in seen:
            seen.add(internal)
            heroes.append(hero)
    return None, heroes


def score_hero_match(hero: Dict[str, object], query: str) -> tuple[int, bool]:
    """Score one hero against a search query.

    The boolean result marks a very relevant match. In this project that means
    a strong prefix-style match after removing case/punctuation/spaces.
    """
    compact_query = compact_key(query)
    if not compact_query:
        return (0, False)

    very_relevant = False
    best_score = -1
    display = str(hero["display"])

    for alias in hero_aliases(hero):
        alias_compact = compact_key(alias)
        if not alias_compact:
            continue
        score = -1
        if alias_compact == compact_query:
            score = 400
            very_relevant = True
        elif alias_compact.startswith(compact_query):
            score = 300 - max(0, len(alias_compact) - len(compact_query))
            very_relevant = True
        else:
            alias_norm = normalize_key(alias)
            query_norm = normalize_key(query)
            if alias_norm == query_norm:
                score = 260
            elif alias_norm.startswith(query_norm):
                score = 220 - max(0, len(alias_norm) - len(query_norm))
            elif query_norm in alias_norm:
                score = 160 - alias_norm.index(query_norm)
            elif compact_query in alias_compact:
                score = 120 - alias_compact.index(compact_query)
        best_score = max(best_score, score)

    # Fall back to difflib-based fuzzy suggestions if exact/prefix logic failed.
    if best_score < 0:
        resolved, suggestions = resolve_hero_name(query)
        internal = str(hero["internal"])
        if resolved and str(resolved["internal"]) == internal:
            best_score = 80
        elif any(str(s["internal"]) == internal for s in suggestions):
            rank = [str(s["internal"]) for s in suggestions].index(internal)
            best_score = 60 - rank

    # Give the display name itself a modest boost if it contains the normalized query.
    if normalize_key(query) in normalize_key(display):
        best_score = max(best_score, 180)

    return best_score, very_relevant


def ranked_search_results(query: str) -> List[tuple[Dict[str, object], int, bool]]:
    """Return all matching heroes sorted from strongest match to weakest."""
    scored: List[tuple[Dict[str, object], int, bool]] = []
    for hero in HERO_DATA:
        score, very_relevant = score_hero_match(hero, query)
        if score > 0:
            scored.append((hero, score, very_relevant))
    scored.sort(key=lambda item: (-item[1], str(item[0]["display"]).lower()))
    return scored


def sanitize_timer_value(value: object, default: int) -> int:
    """Convert a timer input into a non-negative integer, or fall back to default."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(0, number)


def build_ad_command(
    chosen_heroes: List[Dict[str, object]],
    *,
    pre_time: int = DEFAULT_TIMERS["pre_time"],
    per_player_time: int = DEFAULT_TIMERS["per_player_time"],
    pre_round_time: int = DEFAULT_TIMERS["pre_round_time"],
) -> str:
    """Build the final semicolon-separated console command string.

    The sequence is:
    1. enable cheats,
    2. clear any previous AD setup,
    3. apply the three draft timer settings,
    4. place selected heroes into Radiant, Dire, then Extra order,
    5. print the current roster as a sanity check.
    """
    if len(chosen_heroes) > 12:
        raise ValueError("You can choose at most 12 heroes.")

    pre_time = sanitize_timer_value(pre_time, DEFAULT_TIMERS["pre_time"])
    per_player_time = sanitize_timer_value(per_player_time, DEFAULT_TIMERS["per_player_time"])
    pre_round_time = sanitize_timer_value(pre_round_time, DEFAULT_TIMERS["pre_round_time"])

    commands = [
        "sv_cheats 1",
        "dota_gamemode_ability_draft_set_draft_hero_and_team_clear",
        f"dota_gamemode_ability_draft_per_player_time {per_player_time}",
        f"dota_gamemode_ability_draft_pre_round_time {pre_round_time}",
        f"dota_gamemode_ability_draft_pre_time {pre_time}",
    ]
    for i, hero in enumerate(chosen_heroes):
        if i < 5:
            side = "radiant"
        elif i < 10:
            side = "dire"
        else:
            side = "extra"
        internal = str(hero["internal"])
        commands.append(f"dota_gamemode_ability_draft_set_draft_hero_and_team {internal} {side}")

    commands.append("dota_gamemode_ability_draft_set_draft_hero_and_team")
    return ";".join(commands) + ";"
