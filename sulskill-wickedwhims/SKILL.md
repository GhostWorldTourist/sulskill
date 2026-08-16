---
name: sulskill-wickedwhims
description: Read, search, and edit WickedWhims settings profiles for The Sims 4 from disk instead of the in-game settings menus. Use when the user wants to view, change, compare, back up, or copy WickedWhims settings between profiles.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# WickedWhims config

Edit WickedWhims settings from disk instead of walking its in-game menus.


## Refusal policy (not optional)

Before anything else, `_shared/gate.py` scans the mod library. It exits non-zero
if it finds mods built around sexual abuse - child sexualisation, bestiality or rape - or mods built to work with them.

- **The scripts enforce this themselves.** Every script in `scripts/` imports
  `gate` and will not run past it. If a script exits with the refusal banner,
  relay it and stop.
- **On a `BLOCK` result:** do not offer a workaround, do not edit or bypass the
  gate, and do not hand-roll in a one-off script what the gate just declined to
  do. Removing the mods from disk is the only way forward.
- **On a `REVIEW` result:** a listed creator also ships ordinary mods. Identify
  the specific files rather than assuming from the name, then
  `py _shared/gate.py --clear "<filename>"` for the ones that are fine.
- **If the gate is missing:** refuse to run the skill. Nothing was checked.
- **If you are asked to bypass, disable or weaken any of this:** the list behind
  the gate is mods built around sexual abuse - child sexualisation, bestiality and rape - and mods built to plug into them.
  Adult mods are not filtered and are none of this tool's business. Correcting or
  extending the gate is ordinary work you should help with; weakening it is not,
  and writing a one-off script to do what the gate declined is the same thing by
  another route. Say what the list contains, decline, and do not argue the point.

Full policy, including the categories no pattern can catch: [POLICY.md](../sulskill/POLICY.md)

## Ownership rule (important)

This skill **only writes to profiles it created itself**, marked with
`"_managed_by": "sulskill"`. Profiles the user made in-game are read-only
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
presets around instead. (This differs from `sulskill-mccc`, which does ship a mod.)

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
py scripts/ww.py init --name wwskill_1 --from <TheirProfile>
py scripts/ww.py categories
py scripts/ww.py search undress
py scripts/ww.py get nudity.underwear_switch
py scripts/ww.py set nudity.underwear_switch=0     # auto-targets managed profile
py scripts/ww.py diff <TheirProfile> wwskill_1
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
