---
name: sims4-worlds
description: Static reference for every Sims 4 world - where it sits on the world map, which landmass and neighbours it has, its pack and neighborhoods, its identifier in Kuttoe Home Regions, and whether Basemental Drugs can legalise cannabis or gambling there. Use when reasoning about world geography, travel, regional filters, per-world legality, or when any mod names a world differently from the game.
---

# Sims 4 worlds

`reference/worlds.json` is stable game knowledge, so it is **committed, not
generated**. Everything else in this repo ships extractors instead of extracts;
this one is the exception because it does not change unless a pack ships.

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

## Worldbuilding for this user

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
`sims4-modbuild/scripts/pyc37.py` — the enum member list is authoritative.
