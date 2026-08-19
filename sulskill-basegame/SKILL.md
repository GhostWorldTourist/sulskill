---
name: sulskill-basegame
description: Build and query a full index of The Sims 4 base game — every package, tuning instance, string table and the game's own compiled Python — so a claim about a mod can be checked against what vanilla actually is. Use when you need to know what an instance id is, whether a mod overrides EA tuning or invents its own, what a buff shows the player, which pack shipped something, or the signature of a game method.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Base game index

Reads the installed game and builds a queryable index of it. What that buys is
the difference between "this mod overrides something" and "this mod overrides
`buff_Hungry` and here is what EA's version does".

The findings that came out of building it — format rules, load order, hashing,
and the baselines a claim about a mod should be read against — are in
[BASEGAME.md](../sulskill/BASEGAME.md). **Read that before concluding that two
resources conflict, that a hash does not match, or that a value read out of
SimData means what it appears to.**

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

## Build it once

```bash
py scripts/index.py            # build whatever is missing
py scripts/index.py --list     # the stages and what each produces
py scripts/index.py --force    # rebuild from scratch
```

Every stage is deterministic Python. **No network, no model, nothing to
install** — it costs CPU minutes and nothing else. Stages already built are
skipped, so a failed run is resumed by running it again.

The index lands under `gate.out_dir()`, like every other generated thing here.
It is a few hundred megabytes; if `SULSKILL_OUT` points somewhere the game or a
backup tool reads — the saves folder, for instance — move it first.

**The index is not shipped and never will be.** It is derived from EA's game
files, and it differs with which packs are owned, so a committed copy would
under-report for most people while looking authoritative. Building locally from
the player's own install avoids both problems.

## Query it — this is the part used day to day

```bash
py scripts/q.py schema              # what tables and columns exist. START HERE
py scripts/q.py id 14965            # what is this instance? decimal or hex
py scripts/q.py name commodity      # tuning whose name contains this
py scripts/q.py find fish bowl      # full-text over tuning names
py scripts/q.py text stuck flirty   # full-text over player-visible strings
py scripts/q.py sig protocol_list   # Python signatures with this name
py scripts/q.py cls InstanceManager # a class, its methods, where it lives
py scripts/q.py pkg SimulationDelta # packages matching a name
py scripts/q.py sql "SELECT ..."    # anything else
```

**Run `schema` before writing a query, and pass ids to `id` rather than matching
them yourself.** Both exist because of the same failure: a lookup of instance
14965 against the raw JSONL returned zero hits, because the field is `id` and
not `instance`, and because ids are stored as strings so the ones above 2^63
survive. A wrong field name and a wrong type both look exactly like "not
present". `q.py` normalises anything id-shaped into both spellings, and `schema`
means nothing has to be guessed.

Ids are TEXT in the database deliberately — SQLite's INTEGER is signed 64-bit
and the largest instance ids overflow it into negatives.

## What the index answers

| question | how |
| --- | --- |
| what is instance `0x…`? | `q.py id <n>` — name, type, class, module, which package |
| does this mod override vanilla, or invent content? | is its id in `instances`? |
| what does this buff show the player? | `display_names`, or `q.py text <words>` |
| what fields may this tuning type have? | `tuning_schema.md`, with EA's own descriptions |
| which pack shipped this? | the combined-tuning group id is the pack enum value |
| what is the signature of this game method? | `q.py sig <name>` / `q.py cls <name>` |
| which package wins for a key? | `packages.jsonl` — mount, priority, tombstones |

## Facts worth knowing before you trust a result

- **Two resource trees, not one.** Client and Simulation mount separate
  managers. The same key in both is **not** a conflict.
- **Mods load at priority 500** and beat every game resource. Every game
  priority is negative. Mod-versus-mod order at equal priority is not
  determined by any of this.
- **The XML copies are stale.** Only three of 276 combined-tuning resources are
  text XML; sampling those and generalising produces confident wrong answers
  about the other 273. The readers here use the binary form.
- **Some tuning is client-side and invisible to Python.** Cameras, CAS lighting,
  thumbnails and video playlists are consumed by the C++ client and never
  registered in `sims4.resources.Types` — cameras ship as SimData, not tuning.
  Looking for one through the Python side concludes it does not exist.

The rest, including the measurement traps, is in
[BASEGAME.md](../sulskill/BASEGAME.md).
