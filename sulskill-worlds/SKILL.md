---
name: sulskill-worlds
description: Static reference for every Sims 4 world - where it sits on the world map, which landmass and neighbours it has, its pack and neighborhoods, its identifier in Kuttoe Home Regions, and whether Basemental Drugs can legalise cannabis or gambling there. Use when reasoning about world geography, travel, regional filters, per-world legality, or when any mod names a world differently from the game.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Sims 4 worlds

`reference/worlds.json` is stable game knowledge, so it is **committed, not
generated**. Everything else in this repo ships extractors instead of extracts;
this one is the exception because it does not change unless a pack ships.


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

## What it answers

**Identity across mods.** The same world has three names, and they do not match:

| System | Willow Creek | Henford-on-Bagley | Ciudad Enamorada |
|---|---|---|---|
| Home Regions code | `WILLOW_CREEK` | `HENFORD_ON_BAGLEY` | `CIUDAD_ENAMORADA` |
| Basemental **trait** | `LEG_WILLOWCREEK` | `LEG_COTTAGEWORLD` | `LEG_LOVESTRUCKWORLD` |
| Basemental **buff** | `WILLOW_CREEK` | `COTTAGE_WORLD` | `CIUDAD_ENAMORADA` |
| Config key prefix | `WillowCreek` | `HenfordOnBagley` | `CiudadEnamorada` |

Basemental names worlds after their **pack**, not the place — and it uses **two
schemes that disagree with each other**. The `LEG_*` trait is always pack-named;
the `Legalization` buff is sometimes place-named. They diverge on four worlds:
`VAMPWORLD`/`VAMPIRE_WORLD`, `EVERGREEN`/`EVERGREEN_HARBOR`,
`MAGNOLIA`/`MAGNOLIA_PROMENADE`, `LOVESTRUCKWORLD`/`CIUDAD_ENAMORADA`.

Pack-named codes still map unambiguously, because **every pack that ships a
world ships exactly one** — `CITYLIFE` can only be San Myshuno, `PET_WORLD` only
Brindleton Bay. Deduction, not guesswork. But never translate by eye:

- `EVERGREEN_HARBOUR` (Home Regions, British) vs `EVERGREEN_HARBOR`
  (Basemental, American) — a silent copy-paste failure waiting to happen
- `STRANGETOWN` is the **Sims 2** world name, used for TS4's StrangerVille
- `LEG_GAMBLING_*` mirrors all 27, carrying the same divergences

**Geography.** Positions come from the in-game map as laid out by
**Simmatically's Immersive World Map**, which renders all worlds as one connected
geography instead of unrelated tiles. Three landmasses:

- **North continent (8)** — Innisgreen, Britechester, Henford-on-Bagley,
  Nordhaven, Windenburg, Forgotten Hollow, Ravenwood, Tartosa
- **East islands (5)** — Mt. Komorebi, Tomarang, Sulani, Gibbi Point, Ondarion
- **West continent (17)** — Glimmerbrook, Evergreen Harbor, Moonwood Mill,
  Granite Falls, Copperdale, Brindleton Bay, Newcrest, San Myshuno, Willow Creek,
  Magnolia Promenade, StrangerVille, Oasis Springs, Del Sol Valley, San Sequoia,
  Chestnut Ridge, Ciudad Enamorada, Selvadorada

**Batuu is on no landmass** — it appears on the travel map as a portal off to the
side, so it is unreachable by any land route and should never be grouped with a
continent.

Per-world adjacency is in each landmass's `adjacency_notes`.

## Basemental legality is PER WORLD

`BmdBuffs.Legalization` carries **27 world members** — one flag per world for
cannabis, and a parallel `GamblingLegalization` for gambling. There is **no
sub-world scope**: a world's neighborhoods cannot differ. Do not design around
Nordhaven's Iverstad and Gammelvik disagreeing, or Tomarang's Morensong and Koh
Sahpa — the mod cannot express it.

**Ten worlds have no legalization flag at all**: Britechester, Granite Falls,
Selvadorada, Batuu, and the six hidden/rabbit-hole areas. Note Selvadorada is
absent from legalization yet ships a `SELVADORADA_DEALER` trait — Basemental
models it as a *supply source*, not a jurisdiction.

Legality has teeth: `MISDEMEANOR` / `FELONY` / `HARD_FELONY`, `PRISON_OG`,
`LAW_FIRM_BEST|MED|BAD`, `GET_OUT_OF_JAIL_FREECARD`, and police intensity via
`POLICE_EASY` / `POLICE_HARD` / `POLICE_NOBUSTS`. Getting this wrong gets Sims
arrested, so it is not decoration.

## Worldbuilding: reason from Maxis lore first

**Maxis lore outranks real-world analogue.** Reason from what the game
establishes — premade families, pack themes, existing mechanics — before
reaching for what a place resembles on Earth. Chestnut Ridge celebrates
**nectar making** and Glimmerbrook sells **potions** openly, so both already have
sanctioned intoxicant economies; that beats "Texas ranch country is
conservative." Evergreen Harbor is where Maxis put civic voting, so it is the
natural home of a legalization ballot regardless of any real city.

## Usage

```python
import json, os
W = json.load(open(os.path.join(os.path.dirname(__file__),
                                '..', 'reference', 'worlds.json')))
W['worlds']['Tomarang']['basemental_legalization']   # 'MULTIUNIT_WORLD'
W['landmasses']['east_islands']['worlds']            # travel/adjacency group
W['basemental_not_legalizable']                      # worlds with no flag
```

## Maintenance

Add a world when a pack ships. Re-check `basemental_legalization` after a
Basemental update by reading `Basemental/enums/main.pyc` with
`sulskill-modbuild/scripts/pyc37.py` — the enum member list is authoritative.
