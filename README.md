# Dota 2 Ability Draft Console Command Generator

This is a small local Python project for building a custom Ability Draft console command with a clickable hero UI.

## What it does

- Enables cheats
- Clears the old custom AD setup
- Lets you choose the three draft timers in the UI
  - `pre time`
  - `per player time`
  - `pre round time`
- Lets you select up to 10 heroes by clicking
- Fills heroes in order: first 5 to Radiant, next 5 to Dire
- Clicking a selected hero again will unselect it
- Shows the main setup command and a separate clear-setup command
- Lets you copy either command
- Keeps icon loading offline for fast startup
- Shows an updater hero-count health check in the app

## Files

- `AD_console_command_generator.pyw` : start the UI
- `update_assets.py` : refresh hero names from Valve's official Dota 2 datafeed and download icons for offline use. Run this with python as admin.
- `hero_data.json` : display names, internal command names, aliases, and optional official site slugs
- `ad_ui/logic.py` : matching, ranking, and command generation
- `ad_ui/icons.py` : local icon loader (offline only)
- `ad_ui/app.py` : Tkinter UI
- `cache/icons/` : offline icon files downloaded from Valve's hero site/CDN
- `cache/update_status.json` : hero-count check status written by the updater

## First-time setup

Run the asset updater once (as admin) so the UI has local icons and updater status:

```bash
python update_assets.py
```

## Notes

- The main app does not download icons at startup.
- The updater stores one canonical icon file per hero and uses `cache/icons/aliases.json` so aliases such as `wraithking` and `skeleton_king` share the same local image.
- Search now ranks strong prefix matches highest while ignoring case, spaces, underscores, and symbols.
- If the hero-count check is red, rerun `update_assets.py`.

##

- This project is mostly coded by Chatgpt, prompted by FrEEz1ng.