---
name: sulskill-kuttoe
description: Read, explain, search, and edit the settings of Kuttoe's Sims 4 mods (Home Regions, Career Overhaul Suite, Spellcaster Tweaks, Potions Rework, Festival Notification Rework, Basic Burns, Enlist in War, the trait packs, and more) from disk instead of console commands or in-game menus. Use when the user asks what a Kuttoe mod can be configured to do, or wants to change, compare, or back up Kuttoe settings.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Kuttoe config

Kuttoe's mods share one settings framework. Every configurable mod keeps a flat
JSON file at `saves\Kuttoe\[Kuttoe] <Mod>_Settings.cfg`, and some also register
console commands under the `kuttoe.<ns>.` namespace.

Covered here: **13 mods, 265 settings, 76 console commands** — regenerate with
`py scripts/extract_kuttoe.py` after updating any Kuttoe mod.


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

## Two sources of truth, and which to trust

| | Source | Reliability |
|---|---|---|
| **Keys, types, console commands** | `reference/kuttoe_schema.json`, from the mods' bytecode + live config | **exact** |
| **What a setting means** | `reference/kuttoe_descriptions.json` | tagged per entry |

The itch.io pages describe *features*, not setting keys — the Home Regions page
explains Regional Filters, Soft Filters, World Exemptions, Venue Filters and
Career Filters without ever naming `bidirectional_toggle` or `spa_toggle`. So
the site alone is not enough to configure these mods, and neither is the config
file alone. The descriptions file bridges the two, and **every entry carries a
`source`**:

- `itch.io` — read off Kuttoe's own page. State as fact. `explain` prints
  `[DOCUMENTED]`.
- `inferred` — deduced from the key name, its stored value and its neighbours.
  `explain` prints `[INFERRED]`, and `list --describe` prefixes it with `~`.
  **Report these as inference, never as fact.**

Coverage is **256 of 265** settings (202 documented, 54 inferred). The remaining
9 are command stems with no stored key; `explain` labels them `[COMMAND ONLY]`.

Per-mod page URLs are in `reference/itch_urls.json` if a setting needs
first-hand checking.

## Where the settings live (and what that implies)

`saves\Kuttoe\` is **outside the Mods folder**, so:

- Vortex does not deploy or own these files — direct edits are durable and are
  never reverted by a redeploy.
- They are **not** removed by deleting save games. Deleting `.save` files leaves
  all 11 config files intact. (Deleting the whole `saves` folder would destroy
  them, along with WickedWhims' profiles — warn before anyone does that.)
- There is nothing to package as a mod; these are plain JSON presets.

## Never write while the game is running

The framework rewrites the entire settings file when a `kuttoe.*` console
command changes a value, so a disk edit made while TS4 is up can be silently
discarded. `set` checks for `TS4_x64.exe` and refuses; `--force` overrides.
Settings load at game start, so waiting costs nothing.

If the user wants a change *right now* mid-session, use the mod's console
command instead of editing the file — `explain` prints the command for any
setting that has one.

## The save profile — never hard-code a time factor

`saves\SulSkill\sims4_profile.json` holds facts about **this save** that any
mod-config skill may consult: the active lifespan preset, the user's custom
per-phase day counts, and the scaling factors. It sits beside `Kuttoe\` and
`WickedWhimsMod\` because it describes the game, not the tooling — `SulSkill` is
the user's own namespace for this tooling, mirroring how each mod author owns a
folder there.

**Whenever a setting needs a time-scaling factor, read it from here — do not
invent one inline and do not bake a computed number into a script.** The user
switches lifespan presets, and a hard-coded factor silently rots the moment they
do.

```bash
py scripts/kuttoe.py profile                          # show it
py scripts/kuttoe.py profile --lifespan custom_long   # switch preset; the scale re-derives
py scripts/kuttoe.py rescale --dry-run                # preview every scalable setting
py scripts/kuttoe.py rescale                          # write them
py scripts/kuttoe.py rescale --scale 3 --dry-run      # preview a what-if
```

**The scale is derived, never stored** — `active_days / reference_days`, read
from the profile at run time. Read both numbers; never hard-code the result.
Switching the lifespan preset is the only action required, which is the point: a
factor kept alongside it is one more thing to leave stale.

### Which settings move

Not everything time-shaped does, and a single global multiplier was the previous
design's mistake. One test decides it: **does the thing run out?**

A finite pursuit — a spellbook, a ladder, a collection — tuned to fill a vanilla
life will finish in the first tenth of a long one and leave the rest of that life
empty. Those scale. Everything else is the texture of play: it repeats forever,
the author tuned how it feels in an evening, and a longer lifespan does not make
it wrong. Scaling those only makes a trait look broken.

Each setting is tagged in `kuttoe_descriptions.json` under `scaling` with its
**mod-default `base`**, a `scale`, and a `why` in plain words:

| `scale` | effect | for |
|---|---|---|
| `up` | `base × scale` | finite pursuits that would otherwise be exhausted early |
| `down` | `base ÷ scale` | rates written as a percentage of normal, where a longer life wants a *smaller* number |
| `no` | untouched | repeats forever, or is not a time span at all |

`down` is not a different intention from `up`. It is the same one written against
an inverted encoding — the arithmetic flips, the reasoning does not.

`rescale` always computes from `base`, never from the current value, so running
it repeatedly is idempotent instead of compounding. Where a setting declares a
`min`/`max`, a result outside it is **clamped and reported** — a range that
cannot express the lifespan is a finding, not something to swallow silently, and
usually means a paired setting is the real dial.

### Pins beat the scale

`scaling.pins` in the profile holds values chosen by hand. `rescale` writes them
like any other value but never *computes* them — a pin is the setting, not a note
about it. Some settings simply are a preference (two that derive identically can
still want different values) and no factor can express that. Prefer a pin over
inventing a knob.

A pin is also how an author's deliberate ratio survives scaling. Kuttoe sets
`tome_cooldown` and `teachspell_cooldown` 15:1 on purpose; pinning one and
deriving the other would silently flatten that to 7:1, so both are pinned
(`672` / `10080`) and the ratio holds.

## Units are the other trap

**Cooldowns are stored in sim-minutes even where the mod's page documents them
in hours.** `SpellcasterTweaks.tome_cooldown` is documented as "4 hours" and
stored as `240`; `teachspell_cooldown` is documented as "60 hours" and stored as
`3600`. Writing `4` because the page said 4 hours gives a four-*minute*
cooldown. `LongerLastingNails.nail_duration` is likewise minutes (`4320` = 3
days). Keys ending `_days` really are days, and may be fractional (`1.5`).

`explain` prints a `unit` line wherever one is known. Always check it before
converting a number the user gives you in hours or days.

## Types are the trap

The config file cannot distinguish an int from a float that happens to hold a
whole number, and writing the wrong one is how a setting silently stops
applying. The framework validates with `validate_bool` / `validate_int` /
`validate_float`, and the schema records the declared type from two independent
signals:

- the **console command verb** — `toggle_x` is a bool, `set_x` is numeric
- the **live value's** concrete Python type

`set` coerces to the recorded type, so `tan_rate=0.5` stays a float and
`tome_cooldown=300` stays an int. Never hand-edit these files as raw JSON.

## Usage

```bash
py scripts/kuttoe.py mods                      # every configurable mod + counts
py scripts/kuttoe.py list HomeRegions           # all settings of one mod
py scripts/kuttoe.py list PotionsRework --describe   # ...with meanings (~ = inferred)
py scripts/kuttoe.py search toggle             # find settings by name or value
py scripts/kuttoe.py get spa_toggle
py scripts/kuttoe.py explain tome_cooldown     # type, console command, file
py scripts/kuttoe.py commands SpellcasterTweaks
py scripts/kuttoe.py set spa_toggle=true tome_cooldown=300
py scripts/kuttoe.py status                    # schema vs live drift
py scripts/extract_kuttoe.py                   # rebuild after a mod update
```

Settings are addressed `Mod.key`, or bare `key` when unique across mods — a
bare key that exists in several mods is rejected rather than guessed. One `set`
may span several mods; each file is written and backed up separately.

## Mod-specific notes

- **HomeRegions** is the big one: **220 settings**. Roughly 5 keys per world
  (`GraniteFalls_*`, `Windenburg_*`, …), plus global `*_toggle` venue and career
  filters, `Show*Notification` toggles, and `occult_*` / `additional_*` groups.
  Values are mixed — 95 bool, 47 list, 38 float, 28 dict. Its commands use the
  short `kuttoe.hr.*` namespace, and many are diagnostic
  (`kuttoe.hr.get_allowed_regions`, `kuttoe.hr.get_home_world_name`) rather than
  setters — useful for answering "why is this Sim here?"
- **CareerOverhaulSuite**, **BasicBurns**, **EnlistInWar**, **LongerLastingNails**
  and the three trait packs register **no console commands at all** — the config
  file is the only way to configure them, which is exactly where this skill earns
  its keep.
- **BasementalAddons** and **NewCivicPolicies** register a command but ship no
  config file.
- Config filenames don't always match script names (`CareerOverhaulSuite.ts4script`
  writes `[Kuttoe] CareerOverhaul_Settings.cfg`); the extractor matches on
  normalised prefix, and `status` reports any config it cannot pair.

## Workflow

1. `mods` / `list` / `search` to locate the setting; `explain` for its type and
   whether an in-game command exists.
2. Check the game is closed, then `set`; report before → after per key.
3. Changes apply on next game load. For a mid-session change, give the user the
   `kuttoe.*` console command instead.
