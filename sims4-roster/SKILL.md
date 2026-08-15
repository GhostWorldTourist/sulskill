---
name: sims4-roster
description: Extract the roster of premade Sims and households shipped with The Sims 4 - names, ages, genders, traits, household bios, and which world each lives in - from the game's own packages. Use when the user asks who the premade Sims are, what a premade household's story or traits are, or wants a searchable list of the default population.
---

# Sims 4 premade roster

`scripts/roster.py` builds a searchable roster of the Sims EA ships.

```bash
py scripts/roster.py --rebuild            # full scan, a few minutes
py scripts/roster.py --search Goth
py scripts/roster.py --region "Willow Creek"
py scripts/roster.py --counts
py scripts/roster.py --unplaced           # templates with no lot
```

The result is cached to `reference/roster.json`, which is **gitignored** - it is
EA's game text, and it regenerates from a local install.

## Why the game files and not a save

Sim bios are not in a save at all. The only prose in a save's sim blob is the
world description. Save sim data also sits behind a container layer that does not
decode as protobuf from byte zero, and a played save carries the player's own
edits mixed in with the premades. Game data gives the pristine roster.

## The chain

Four resource types, one join each. `HOUSEHOLD_DESCRIPTION` is the hub:

```
HOUSEHOLD_DESCRIPTION 0x729F6C4F
  |- u32 STBL key -> household name
  |- u32 STBL key -> household BIO
  |- u64 -> LOT_DESCRIPTION 0x01942E2C
  |          |- u64 -> WORLD_DESCRIPTION 0xA680EA4B
  |                     |- u64 -> REGION_DESCRIPTION 0xD65DAFF9   (world name)
  |- u64 -> HOUSEHOLD_BINARY 0xB3C438F0    Sims, ages, genders, traits
```

`HOUSEHOLD_DESCRIPTION` is a fixed-size struct whose field offsets depend on a
per-version base: v7 -> 0x46, v10 -> 0x52, v11/v14/v18 -> 0x6A. From that base:
`+0x00 u64 lot`, `+0x08 u32 name key`, `+0x0C u32 bio key`, `+0x10 u64 household
binary`.

**The bio key is not in the household binary.** That record is name-literal
("Goth", "Mortimer"); the localized name and bio live only in the description.

## Four traps, each of which cost a debugging cycle

**Parse exactly the declared payload.** `HOUSEHOLD_BINARY` is `u32 version`, then
8 reserved bytes if version >= 2, then `u32 size`, then protobuf. The record
carries a trailing byte past that declared size. Slicing to the end of the blob
instead of to `size` makes the reader consume a zero key and raise "field 0",
which looks exactly like a corrupt record and is not.

**A Sim's name is stored one of two ways.** Either a literal string (fields 5/6)
or an STBL key (fields 55/56). Reading only the literals silently drops most of
the population - it produced 8 households with Sims instead of 171. Always try
both and resolve keys against the string table.

**Delta must win, and filename sort gets it backwards.** `ClientDeltaBuild0`
sorts before `ClientFullBuild0`, so a naive `sorted(os.walk(...))` leaves the
stale Full copy in place. Order Full first, then Delta, explicitly.

**Empty records exist.** Delta packages ship zero-length
`HOUSEHOLD_DESCRIPTION` entries as tombstones; guard on length.

## Field map for HOUSEHOLD_BINARY

```
top    1 = Household
Household   2 household_id   3 name   4 funds   6 repeated SimInfo
SimInfo     1 sim_id (fixed64)      4 family id (fixed64)
            5 first name (string)   55 first name STBL key
            6 last name  (string)   56 last name  STBL key
            7 gender  4096 Male 8192 Female
            8 age     1 Baby 2 Toddler 4 Child 8 Teen 16 YA 32 Adult 64 Elder
            12 CAS slider CSV
            30.10.1  packed varints = trait tuning ids
            30.13    repeated {1 skill_id, 2 f32 value}
            30.14    repeated {1 index, 2 sim_id}  = parent links
```

Age and walk-style are ordinary entries in the trait list; filter by name prefix
for personality traits only.

## Known limits

- **Some Sims within a household still drop.** The BFF household reports Travis
  but not Liberty or Summer. Household and bio extraction is sound; per-Sim
  coverage is not yet complete, so treat a household's Sim list as a floor.
- **Trait NAMES only cover the base game.** Just 3 Combined Tuning resources
  install-wide are XML; the other ~273 are EA's binary `DATA` container, giving
  166 named traits. Trait ids always extract - only the naming is short. Parsing
  the DATA container with `sims4-modbuild/scripts/simdata.py` is the way to widen
  this.
- Roughly 380 of 547 households have no Sim link; most are unplaced templates and
  gallery stock.

## Dead ends - do not retry

- `sim_template` / `template_chooser` tuning (`TunableSimTemplate`,
  `HouseholdTemplate` in `filters.household_template`) are **procedural townie
  generators**, not the named premades. Convincing and wrong.
- `SIMINFO 0x025ED6F4` is CAS appearance only - no names, traits, or household link.
- `0x3EAAA87C` contains the literal bytes "Goth" and "Willow" but is an animation
  clip bundle; coincidental matches in compressed data.
- `SimInfo.18.1` holds large 64-bit varints that look like a trait list. They are
  not - real traits are the small ids at `30.10.1`.
