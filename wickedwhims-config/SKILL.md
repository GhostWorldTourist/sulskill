---
name: wickedwhims-config
description: Read, search, and edit WickedWhims settings profiles for The Sims 4 from disk instead of the in-game settings menus. Use when the user wants to view, change, compare, back up, or copy WickedWhims settings between profiles.
---

# WickedWhims config

Edit WickedWhims settings from disk instead of walking its in-game menus.

## Ownership rule (important)

This skill **only writes to profiles it created itself**, marked with
`"_managed_by": "claude-wwskill"`. Profiles the user made in-game are read-only
here — `set` and `import` refuse them with an explanation. The user's own
settings can never be clobbered by this skill.

To start: `init` creates a managed profile (default `wwskill_1`), optionally
seeded from an existing profile so it starts equivalent rather than empty. Then
**tell the user to switch the active profile to it in WickedWhims' in-game
settings** — until they do, edits here have no effect.

Flag once, when creating: a hand-authored profile is not something WW writes
itself. Ask the user to confirm it appears in the in-game profile list before
relying on it.

## Not a mod

WW settings live under `saves\`, **outside** the Mods folder, so there is
nothing for Vortex to deploy. If the user asks for a WW settings pack
installable like a mod, say so plainly — `export`/`import` moves portable JSON
presets around instead. (This differs from `mccc-config`, which does ship a mod.)

## Paths and shape

Profiles: `Documents\Electronic Arts\The Sims 4\saves\WickedWhimsMod\settings_profiles\`

```
{ "name", "file_name", "identifier", "created_at", "mod_version",
  "version_control", "_managed_by",
  "data": { "nudity": {...}, "relationships": {...}, "sex": {...} } }
```

Settings are addressed `category.key` (e.g. `nudity.underwear_switch`). Values
are almost all **integer `0`/`1` flags, not booleans** — the script preserves the
integer type on write, since coercing `1` to `true` could break WW's parsing.
An empty `data` block means the profile inherits WW defaults.

## Usage

```bash
py scripts/ww.py profiles                          # lists, marking MANAGED vs yours
py scripts/ww.py init --name wwskill_1 --from LAmour4581
py scripts/ww.py categories
py scripts/ww.py search undress
py scripts/ww.py get nudity.underwear_switch
py scripts/ww.py set nudity.underwear_switch=0     # auto-targets managed profile
py scripts/ww.py diff LAmour4581 wwskill_1
py scripts/ww.py export preset.json
py scripts/ww.py import preset.json
```

`--dir` and `--profile` are global flags and must come **before** the
subcommand. Without `--profile`, commands prefer the managed profile.

`set` is type-checked and refuses unknown keys, since WW ignores unrecognized
settings silently. Every write leaves a timestamped `.bak`.

## Facts

- **Close the game before writing.** WW holds settings in memory and writes the
  whole profile on save, so it overwrites disk edits made while running. `set`
  and `import` now check for `TS4_x64.exe` and refuse; `--force` overrides.
  To wait for the user to quit, background an
  `until ! tasklist | grep -qi TS4_x64; do sleep 5; done` rather than asking
  them to ping you.
- Settings are **per profile**, and WW binds a profile to a save.
- Changes apply when the save is next loaded.

## Workflow

1. `profiles` — confirm which profile is active and whether a managed one exists.
2. `init` if needed, and tell the user to switch to it in-game.
3. Confirm the game is closed, then `set`; report before → after per key.
