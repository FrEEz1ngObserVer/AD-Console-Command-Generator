from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_PATH = PROJECT_ROOT / "hero_data.json"
ICON_DIR = PROJECT_ROOT / "cache" / "icons"
ICON_ALIAS_PATH = ICON_DIR / "aliases.json"
UPDATE_STATUS_PATH = PROJECT_ROOT / "cache" / "update_status.json"
HEROLIST_URL = "https://www.dota2.com/datafeed/herolist?language=english"
ICON_URL_PATTERNS = [
    "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{slug}.png",
    "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/heroes/{slug}_sb.png",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


def normalize_name(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def hero_site_slug(display_name: str) -> str:
    return normalize_name(display_name).replace(" ", "")


def slug_to_title(slug: str) -> str:
    return re.sub(r"\s+", " ", slug.replace("_", " ").replace("-", " ")).title().strip()


def make_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def fetch_json(url: str, timeout: float = 20.0) -> Any:
    with urllib.request.urlopen(make_request(url), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def load_hero_data() -> List[Dict[str, object]]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def save_hero_data(data: List[Dict[str, object]]) -> None:
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_update_status(
    *,
    passed: bool,
    official_count: int | None = None,
    local_count: int | None = None,
    icon_count: int | None = None,
    expected_icon_count: int | None = None,
    message: str = "",
) -> None:
    UPDATE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "passed": passed,
        "official_count": official_count,
        "local_count": local_count,
        "icon_count": icon_count,
        "expected_icon_count": expected_icon_count,
        "message": message,
    }
    UPDATE_STATUS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_int_like(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value.isdigit():
            return int(value)
    return None


def looks_like_slug(value: str) -> bool:
    if not value:
        return False
    candidate = value.strip().lower()
    if candidate.startswith("npc_dota_hero_"):
        return True
    if candidate.startswith("/hero/"):
        return True
    return bool(re.fullmatch(r"[a-z0-9_\-/]+", candidate))


def clean_slug(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    slug = value.strip().lower()
    if not slug:
        return ""
    slug = slug.rsplit("/", 1)[-1]
    slug = slug.rsplit(".", 1)[0]
    if slug.startswith("npc_dota_hero_"):
        slug = slug[len("npc_dota_hero_"):]
    slug = slug.strip("-_ ")
    if not re.fullmatch(r"[a-z0-9_-]+", slug):
        return ""
    return slug


def pick_slug(candidate: Dict[str, Any]) -> str:
    slug_keys = (
        "slug",
        "short_name",
        "shortName",
        "name",
        "hero_name",
        "heroName",
        "npc_name",
        "npcName",
        "internal_name",
        "internalName",
    )
    for key in slug_keys:
        raw = candidate.get(key)
        if not isinstance(raw, str):
            continue
        if not looks_like_slug(raw):
            continue
        slug = clean_slug(raw)
        if slug:
            return slug
    return ""


def pick_display_name(candidate: Dict[str, Any], slug: str) -> str:
    display_keys = (
        "name_loc",
        "localized_name",
        "localizedName",
        "display_name",
        "displayName",
        "pretty_name",
        "prettyName",
        "name_english",
        "nameEnglish",
        "hero_title",
        "heroTitle",
    )
    for key in display_keys:
        raw = candidate.get(key)
        if isinstance(raw, str) and raw.strip():
            return re.sub(r"\s+", " ", raw).strip()

    raw_name = candidate.get("name")
    if isinstance(raw_name, str) and raw_name.strip() and not looks_like_slug(raw_name):
        return re.sub(r"\s+", " ", raw_name).strip()

    if slug:
        return slug_to_title(slug)
    return ""


def pick_hero_id(candidate: Dict[str, Any]) -> int | None:
    for key in ("id", "hero_id", "heroId"):
        hero_id = parse_int_like(candidate.get(key))
        if hero_id is not None:
            return hero_id
    return None


def iter_dicts(obj: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item)


def extract_hero_entries(payload: Any) -> List[Dict[str, object]]:
    found: List[Dict[str, object]] = []
    seen: set[tuple[Any, str, str]] = set()

    for candidate in iter_dicts(payload):
        hero_id = pick_hero_id(candidate)
        slug = pick_slug(candidate)
        display = pick_display_name(candidate, slug)
        score = int(hero_id is not None) + int(bool(slug)) + int(bool(display))
        if score < 2:
            continue

        key = (hero_id, slug, normalize_name(display))
        if key in seen:
            continue
        seen.add(key)

        entry: Dict[str, object] = {"display": display}
        if hero_id is not None:
            entry["hero_id"] = hero_id
        if slug:
            entry["site_slug"] = slug
        found.append(entry)

    by_best_key: Dict[str, Dict[str, object]] = {}
    for entry in found:
        dedupe_key = str(entry.get("hero_id") or entry.get("site_slug") or normalize_name(str(entry["display"])))
        old = by_best_key.get(dedupe_key)
        if old is None:
            by_best_key[dedupe_key] = entry
            continue
        old_score = int("hero_id" in old) + int(bool(old.get("site_slug")))
        new_score = int("hero_id" in entry) + int(bool(entry.get("site_slug")))
        if new_score > old_score:
            by_best_key[dedupe_key] = entry

    result = list(by_best_key.values())
    result.sort(key=lambda hero: (str(hero.get("display", "")).lower(), str(hero.get("site_slug", ""))))
    return result


def build_match_indexes(hero_data: List[Dict[str, object]]) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Dict[str, object]]]:
    by_internal: Dict[str, Dict[str, object]] = {}
    by_name: Dict[str, Dict[str, object]] = {}
    for hero in hero_data:
        internal = str(hero.get("internal", "")).strip().lower()
        display = str(hero.get("display", "")).strip()
        aliases = [str(a) for a in hero.get("aliases", [])]
        site_slug = str(hero.get("site_slug", "")).strip().lower()
        if internal:
            by_internal[internal] = hero
        names = {display, site_slug, hero_site_slug(display)}
        names.update(aliases)
        for name in names:
            key = normalize_name(name)
            if key:
                by_name[key] = hero
    return by_internal, by_name


def merge_official_heroes(local_data: List[Dict[str, object]], official: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    by_internal, by_name = build_match_indexes(local_data)
    added: List[Dict[str, object]] = []

    for official_hero in official:
        slug = str(official_hero.get("site_slug", "")).strip().lower()
        display = str(official_hero.get("display", "")).strip()
        hero_id = official_hero.get("hero_id")

        matched = None
        if slug and slug in by_internal:
            matched = by_internal[slug]
        else:
            for key in [normalize_name(display), normalize_name(slug), normalize_name(hero_site_slug(display))]:
                if key in by_name:
                    matched = by_name[key]
                    break

        if matched is not None:
            if slug:
                matched["site_slug"] = slug
            if display:
                matched["display"] = display
            if hero_id is not None:
                matched["hero_id"] = hero_id
            aliases = [str(a) for a in matched.get("aliases", [])]
            for alias in (display, slug):
                if alias and alias != str(matched.get("display", "")):
                    aliases.append(alias)
            matched["aliases"] = sorted({a for a in aliases if a})
        else:
            new_hero: Dict[str, object] = {
                "display": display or slug_to_title(slug),
                "internal": slug or hero_site_slug(display),
                "site_slug": slug or hero_site_slug(display),
                "aliases": [value for value in [display, slug] if value],
            }
            if hero_id is not None:
                new_hero["hero_id"] = hero_id
            local_data.append(new_hero)
            added.append(new_hero)
            if new_hero["internal"]:
                by_internal[str(new_hero["internal"]).lower()] = new_hero
            for key in [
                normalize_name(str(new_hero["display"])),
                normalize_name(str(new_hero["internal"])),
                normalize_name(str(new_hero.get("site_slug", ""))),
            ]:
                if key:
                    by_name[key] = new_hero

    local_data.sort(key=lambda hero: str(hero.get("display", "")).lower())
    return local_data, added


def candidate_icon_keys(hero: Dict[str, object]) -> List[str]:
    keys: List[str] = []
    for value in (hero.get("site_slug"), hero.get("internal"), hero_site_slug(str(hero.get("display", "")))):
        key = clean_slug(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def choose_primary_icon_key(hero: Dict[str, object]) -> str:
    for value in (hero.get("site_slug"), hero.get("internal"), hero_site_slug(str(hero.get("display", "")))):
        key = clean_slug(value)
        if key:
            return key
    raise RuntimeError(f"Could not determine a primary icon key for hero: {hero}")


def build_icon_alias_map(hero_data: List[Dict[str, object]]) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for hero in hero_data:
        primary = choose_primary_icon_key(hero)
        for key in candidate_icon_keys(hero):
            alias_map[key] = primary
    return alias_map


def save_icon_alias_map(alias_map: Dict[str, str]) -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    ICON_ALIAS_PATH.write_text(
        json.dumps(dict(sorted(alias_map.items())), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def remove_stale_alias_icon_files(alias_map: Dict[str, str]) -> int:
    removed = 0
    for path in ICON_DIR.glob("*.png"):
        key = path.stem.lower()
        primary = alias_map.get(key, key)
        if primary != key:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def count_local_icon_files() -> int:
    return sum(1 for path in ICON_DIR.glob("*.png") if path.is_file())


def download_bytes(url: str, timeout: float = 20.0) -> bytes:
    with urllib.request.urlopen(make_request(url), timeout=timeout) as response:
        return response.read()


def download_icon_file(icon_key: str, *, overwrite: bool = False) -> bool:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    path = ICON_DIR / f"{icon_key}.png"
    if path.exists() and not overwrite:
        return False

    last_error: Exception | None = None
    for template in ICON_URL_PATTERNS:
        url = template.format(slug=icon_key)
        try:
            path.write_bytes(download_bytes(url))
            return True
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if last_error is None:
        raise RuntimeError(f"No icon URL templates were available for {icon_key}")
    raise last_error


def fetch_official_hero_list() -> List[Dict[str, object]]:
    payload = fetch_json(HEROLIST_URL)
    heroes = extract_hero_entries(payload)
    if not heroes:
        top_level = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        raise RuntimeError(
            "Official herolist JSON was fetched, but no hero records could be parsed. "
            f"Top-level structure: {top_level}"
        )
    return heroes


def main() -> int:
    print("Refreshing hero data from Valve's official datafeed and updating offline icons...")
    suggestion = "Please run update_assets.py with admin permission."

    try:
        local_data = load_hero_data()
        official = fetch_official_hero_list()
        merged, added = merge_official_heroes(local_data, official)
        save_hero_data(merged)
    except Exception as exc:  # noqa: BLE001
        save_update_status(
            passed=False,
            message=f"Hero refresh failed: {exc}\n{suggestion}",
        )
        print(f"Failed while refreshing hero list: {exc}")
        return 1

    print(f"Official heroes found: {len(official)}")
    if added:
        print("New heroes added locally:")
        for hero in added:
            print(f"  - {hero['display']} ({hero['internal']})")
    else:
        print("No new heroes needed to be added.")

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    alias_map = build_icon_alias_map(merged)
    save_icon_alias_map(alias_map)

    downloaded = 0
    failed: List[str] = []
    for hero in merged:
        primary_key = choose_primary_icon_key(hero)
        try:
            changed = download_icon_file(primary_key)
            downloaded += int(changed)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            hero_keys = candidate_icon_keys(hero)
            failed.append(f"{hero['display']} [{', '.join(hero_keys)}] ({exc})")

    removed_alias_files = remove_stale_alias_icon_files(alias_map)
    icon_count = count_local_icon_files()
    expected_icon_count = len(merged)
    hero_count_passed = len(merged) == len(official)
    icon_count_passed = icon_count == expected_icon_count
    passed = hero_count_passed and icon_count_passed and not failed

    status_lines = []
    if hero_count_passed:
        status_lines.append(f"Hero count check passed: local {len(merged)}, official {len(official)}.")
    else:
        status_lines.append(f"Hero count check failed: local {len(merged)}, official {len(official)}.")

    if icon_count_passed:
        status_lines.append(f"Icon count check passed: stored {icon_count}, expected {expected_icon_count}.")
    else:
        status_lines.append(f"Icon count check failed: stored {icon_count}, expected {expected_icon_count}.")

    if failed:
        status_lines.append(f"Missing or failed icon downloads: {len(failed)}.")

    if not passed:
        status_lines.append(suggestion)

    save_update_status(
        passed=passed,
        official_count=len(official),
        local_count=len(merged),
        icon_count=icon_count,
        expected_icon_count=expected_icon_count,
        message="\n".join(status_lines),
    )

    print(f"Icons downloaded this run: {downloaded}")
    print(f"Duplicate alias icon files removed: {removed_alias_files}")
    if failed:
        print("Icons that failed:")
        for item in failed:
            print(f"  - {item}")
        print("The app will still work and show text buttons for any missing icons.")
    else:
        print("All icons are available offline.")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
