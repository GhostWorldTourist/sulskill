---
name: sulskill-mccc
description: Read, explain, search, and edit MC Command Center settings for The Sims 4 without using the in-game pie menus. Works with a mod manager or a manual install. Use when the user asks what MCCC settings exist or do, what is possible to configure, or wants to change, compare, back up, or ship MCCC settings (mc_settings.cfg / mc_dresser.cfg).
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# MCCC config

Answer questions about MCCC settings and change them from disk instead of
walking MCCC's nested pie menus.


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

## How edits are delivered

**Edit the live file directly. This is the default and the right choice here.**

`mc_settings.cfg` is **not a Vortex-managed file** — it is absent from
`vortex.deployment.json`, and the MCCC archive ships no config files at all
(MCCC creates it at runtime). So Vortex does not own it, and direct edits are
**not reverted by a redeploy**. No install step, no two-writer conflict with
MCCC.

This is the opposite of `mc_dresser.cfg`. That file is not written by MCCC:
it ships *inside* whichever CC mod provides the dresser presets, so it
arrives with that mod and a manager will overwrite any edit on the next
deploy. Fix it at the source the mod came from, not in place. Don't
generalize one to the other.

### The `--managed` path (optional)

`--managed` switches to a packaged Vortex mod at
`%APPDATA%\Vortex\thesims4\mods\sulskill-mccc-settings\`, seeded from live on first
use (all 440 settings, so it is a complete template, never a partial overlay),
rebuilding `sulskill-mccc-settings.zip` on each write.

Use it only for a **portable, versioned preset** — reinstallable, or moved to
another machine. It costs an install step and creates a two-writer situation
with MCCC, so run `sync` (pulls live → managed) after changing settings in-game
and before the next deploy, or those in-game changes get discarded on redeploy.

If packaging: `mc_settings.cfg` must sit at the **archive root**, because MCCC
only reads its config from the folder its own scripts live in. `managed_dir()`
auto-detects Vortex's own staging folder (installing the zip creates one with an
id suffix, separate from the hand-made folder).

## Two sources of truth, and which to trust

A setting has two halves, and they have very different reliability:

| | Source | Reliability |
|---|---|---|
| **Contract** — type, default, range, legal values | `reference/mccc_schema.json`, extracted from MCCC's bytecode | **exact** |
| **Description** — what it means | `reference/mccc_help.json` tooltips | exact for 41 settings, guesswork for the rest |

Reach for the schema first. It covers **376 of 444** settings with a type, 83 with
a numeric range, and 41 with an enumerated list of legal values — none of it
inferred. Regenerate with `py scripts/extract_schema.py` after an MCCC update.

### Why this matters: MCCC does not reject bad values

It matches the value against known branches, and an unrecognized one matches
nothing — so the feature silently disappears with no error in any log. Setting
`Show_Computer_Menu_Type=S` (legal for the *sim* menu, meaningless for the
computer menu) made the MCCC menu vanish from computers entirely. `set` now
refuses values the schema rejects; `--force` overrides.

Two guards keep the extractor honest, because a wrong "legal values" list would
reject *correct* input:
- a one-element set is a stray constant, not an enumeration → discarded
- if the value in the live config is absent from the scraped set, the set is
  provably incomplete → recorded but marked `codes_reliable: false`, warn-only

### Recovering a format MCCC doesn't document

When a value's encoding is unknown, **read it out of the bytecode rather than
experimenting in-game.** TS4 runs Python 3.7; `scripts/pyc37.py` unmarshals it
from a modern interpreter. Guessing formats was the repeated failure mode this
tooling exists to end.

- **Legal codes** live in the `*_choices_dialog` function that writes the
  setting, as string constants beside the setting name.
- **Type/default/range** come from the `_get_setting_value(...)` call in each
  getter. Read them by **disassembling**, never off `co_consts` positionally:
  CPython de-duplicates equal constants, so a setting whose default and minimum
  are both `0` collapses two arguments into one and shifts the rest. Note the two
  call shapes — plain `CALL_FUNCTION`/`CALL_METHOD`, and `CALL_FUNCTION_KW` where
  the bounds are keywords and the final const is a tuple of keyword *names*.
  Handling only the first shape drops every ranged setting.
- The host's `dis.opname` is **wrong** for this bytecode — 3.11 renumbered the
  opcode table. Map 3.7 opcodes explicitly.

## Traps: legal values that don't mean what they read like

- `Relationship_BreakupMoveoutSim` is **not a percentage** — it picks *who*
  moves out: `0` None, `1` Male (the default, so by default the man always
  leaves), `2` Female, `3` Random.
- **Progression percentages are per-pass rolls, not population fractions.**
  `Relationship_MoveinPercent=33` is not "a third of couples move in" — each
  eligible couple rolls 33% *every* story-progression pass, so it compounds
  toward certainty. This is why these settings need to be tuned far lower than
  they read.
- **`*_DaysToRun` creates a cadence mismatch.** Only pregnancy and marriage have
  one. Breakups, divorces, and move-ins roll every pass regardless, so giving
  marriage a single day while divorce runs unrestricted inverts their stated
  ratio. Either clear the day restriction or scale the percentage to compensate.
- **`*_Difficulty_Adjustment` has a cliff.** `0` means *disabled*, not neutral —
  `1` is neutral. `-1..-9` is linear (`-4`→0.6×, `-5`→0.5×), but `-10` and below
  switches to reciprocal (`-10`→0.1×, `-50`→0.02×). Anything past `-9` is
  effectively off. `explain` prints this curve automatically.
- `Decay_Ratio_*` is percent-of-normal and entirely separate from the gain
  multipliers. Slowing gains without touching decay compounds harder than
  intended.

## Never write while the game is running

MCCC holds its whole config in memory and flushes **all** of it to
`mc_settings.cfg` whenever any setting is changed in-game, so a write made while
TS4 is up can be silently discarded. `set` checks for `TS4_x64.exe` and refuses.
Settings only load at game start, so waiting costs nothing.

To wait for the user to quit, use a backgrounded `until ! tasklist | grep -qi
TS4_x64; do sleep 5; done` rather than asking them to ping you.

## Answering "what does this setting do?"

MCCC ships its own menu text: **1,561 tooltip strings** extracted to
`reference/mccc_help.json`. That file has two parts, and the distinction matters:

- `verified` — **41 settings** whose description was recovered by strict
  adjacency between the key name and its string hash in MCCC's `.pyc`. These are
  safe to state as fact.
- `all_strings` — the full tooltip corpus. For the other ~400 settings there is
  **no reliable key→description mapping**. A proximity heuristic was tried and
  rejected: at a wider window it confidently mapped `Population_PercentMale` to
  *"...will be an Elder rather than a Young Adult"*, which is a different
  setting's tooltip.

So: `explain` prints `[VERIFIED]` only for the 41, and otherwise prints
`[UNVERIFIED - candidate tooltips]` for judgment. **Never assert an unverified
mapping as fact.** Read the candidates, use the setting's name and current
value, and say plainly when you are inferring. For authoritative answers point
at <https://deaderpool-mccc.com/> — its docs are the same text as these tooltips.

Note the names are highly regular and self-describing
(`Pregnancy_OffspringGenderPercents`, `Population_PercentMale`), so `search` on
the live config often answers a question outright.

## Usage

All commands default to the **live** config; add `--managed` for the mod path.

```bash
py scripts/mccc.py status                     # live vs managed, redeploy pending?
py scripts/mccc.py modules                    # all settings grouped by module
py scripts/mccc.py search gender              # find settings by name or value
py scripts/mccc.py schema                     # every setting with enumerated legal values
py scripts/mccc.py schema Show_Sim_Menu_Type  # exact type/default/range/codes
py scripts/extract_schema.py                  # rebuild the schema after an MCCC update
py scripts/mccc.py explain Population_PercentMale
py scripts/mccc.py helpsearch offspring       # search MCCC's tooltip text
py scripts/mccc.py get  Pregnancy_AllowMalePregnancy
py scripts/mccc.py set  'Pregnancy_OffspringGenderPercents={"F":0,"M":100}'
py scripts/mccc.py diff                       # managed vs live
py scripts/mccc.py sync                       # pull live -> managed after in-game edits
py scripts/mccc.py package --name MyPreset    # standalone zip (portable preset)
py scripts/mccc.py dresser                    # summarize mc_dresser.cfg (CSV)
```

`set` refuses (a) unknown keys, (b) values the schema rejects, and (c) any write
while the game is running — all three because MCCC fails silently rather than
complaining. `--allow-new` and `--force` override. Every write leaves a
timestamped `.bak`.

## Facts about this setup

- Vortex uses **hardlink deployment**; editing the deployed file is reverted on
  redeploy. That is why writes go to staging.
- **MCCC is also a writer** — it rewrites `mc_settings.cfg` when settings change
  in-game, so Vortex will sometimes report the file as externally modified. Expected.
- Settings load at **game start**; changes apply on next load.
- `mc_dresser.cfg` is **CSV, not JSON**.

## Workflow

1. Answer questions from `schema` first (exact), then `search` / `explain` /
   `helpsearch` for meaning — flagging inference.
2. `set` the change; report before → after per key.
3. For live edits, that's it — they apply on next game load. For `--managed`,
   tell the user to redeploy in Vortex first.

After a batch, **re-read the file and check the settings actually cohere**. The
recurring class of bug here is not a bad write but a dead one: a setting whose
precondition is never met. Real examples — a move-out percentage that can never
fire because no breakups are generated; an affair notification enabled while the
affair rate is `0`; a menu hidden because its code was legal for a sibling
setting. Grep the batch for each new value's dependencies before reporting done.
