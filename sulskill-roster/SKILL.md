---
name: sulskill-roster
description: Read the population of The Sims 4 - the premade Sims and households shipped with the game (names, ages, genders, traits, bios, which world each lives in) from the game's own packages, and who actually lives in a player's own save, as a searchable HTML page covering life stages, household funds and which neighbourhoods filled up. Use when the user asks who the premade Sims are, what a premade household's story or traits are, wants a searchable list of the default population, or asks what is in their save file, who lives in their world, how many Sims they have, or wants a report about their save.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Sims 4 premade roster

`scripts/roster.py` builds a searchable roster of the Sims EA ships.
`scripts/save_report.py` does the other half: who lives in the player's own
world, as a page.

```bash
py scripts/roster.py --rebuild            # full scan, a few minutes
py scripts/roster.py --search Goth
py scripts/roster.py --region "Willow Creek"
py scripts/roster.py --counts
py scripts/roster.py --unplaced           # templates with no lot

py scripts/save_report.py --list          # the saves on this machine
py scripts/save_report.py --out ~/Downloads/save.html
```

Supporting modules: `savegame.py` reads a `.save`; `s4io.py`, `idx.py`, `pb.py`
and `s4types.py` are the DBPF, index, protobuf and resource-type helpers both
commands sit on.

The result is cached to `reference/roster.json`, which is **gitignored** - it is
EA's game text, and it regenerates from a local install.


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

## Two different questions, two different sources

**"Who are the premades?"** — the game files, via `roster.py`. A played save has
the player's own edits mixed in, and **Sim bios are not in a save at all**; the
only prose beside a save's Sims is the world description. Game data gives the
pristine roster.

**"Who lives in *my* world?"** — the save, via `save_report.py`. That is a
different question and the save is the only place that answers it.

An earlier note here said save Sim data "does not decode as protobuf from byte
zero". That is true of most resources in a `.save` and false of the one that
matters. Corrected, because it is the sentence that would stop somebody looking:

| resource | protobuf? |
| --- | --- |
| `0x0000000D` — the simulated world, one big message | **yes**, from byte zero after RefPack |
| `0x00000006` — 393 of them, the bulk of the file | no |
| `0x0000000F`, `0x00000010`, `0x00000014`, `0xE88DB35F` | no |

## Your save, as a page

```bash
py scripts/save_report.py --list                    # which saves exist
py scripts/save_report.py --out ~/Downloads/save.html
py scripts/save_report.py --slot Slot_00000002.save --out ~/Downloads/s2.html
```

Population by life stage and gender, household funds, which neighbourhoods
filled up and which nobody ever moved into, every household searchable. `--out`
is required: the page is about one person's world and does not belong next to
the code.

`savegame.py` is the reader. There is **no published schema**, so nothing in its
field map is quoted from one and nothing is guessed either — each field was
fixed by reading real saves and then checked in a way that could fail:

```
top-level      4 worlds   5 households   6 Sims   7 lots
world          1 id    3 name     10 description
household      2 id    3 name      4 lot id    5 funds   21 creator
sim            4 household id      5 first     6 last    7 gender  8 age  22 surname
lot            1 id    2 name     10 world id  14 description
```

- `sim.household` was confirmed by **joining it**: 386 of 386 Sims joined, and
  the join was checked against something it does not control — **family
  coherence**. In a household of two or more, does a majority share one last
  name? Real saves score 0.74–0.77; the same saves with members shuffled
  between households score 0.00–0.01. The check fails below 0.40.

  It deliberately does **not** compare a Sim's surname to their household's
  *name*. Players rename households, marry Sims across them, take in roommates
  and delete the premades outright — every one of those makes the two differ
  while the join stays perfectly correct, and one renamed household makes all
  of its members disagree at once. No threshold on that separates an edited
  save from a broken reader. Coherence does.
- `household.lot` joins only *some* households on purpose. The rest are the
  game's unhoused pool, and reporting that as a failure would call a normal save
  corrupt.
- **Life stage and gender names are read out of the installed game**, from
  `sims/sim_info_types.pyc`, not remembered. That is where `INFANT = 128` comes
  from. A patch that adds a life stage is picked up rather than mislabelled.
- **Nothing about pets, traits, skills or relationships is claimed.** No field
  in the sample took species-shaped values, and a guess about somebody's game is
  worse than a gap.

`Save.verify()` re-runs every one of those checks against the save in front of
it and the page prints the result either way. A renumbered field should make it
say so, loudly, rather than quietly relabelling somebody's family.

**This reports the save as it stands, not the population EA ships.** Premades
the player deleted are absent; ones they renamed, aged up, moved or married off
appear as they were left; Sims they made themselves are counted alongside. No
Sim is labelled premade or player-made, because the save does not say. Use
`roster.py` for the pristine roster and this for the lived-in one.

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
  the DATA container with `sulskill-modbuild/scripts/simdata.py` is the way to widen
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
- **Telling which households in a save are EA's.** People assume this is
  possible and it is not, so do not build a "premade / player-made" label and do
  not accept a request to add one without reading this first.

  Tested rather than assumed. Every household id in a real save was checked
  against the game's shipped household data two ways: against the resource
  instance ids, and against **every u64 at every byte offset** inside 755
  `HOUSEHOLD_DESCRIPTION` and `HOUSEHOLD_BINARY` payloads — 590,620 distinct
  values. Overlap: **0 of 181.** Household ids are minted when the world is
  created; the link to the template a household came from is not carried into
  the save.

  Matching on *name* is the tempting fallback and is exactly the unreliable
  thing: a player can name a household "Goth", and a player can rename the real
  Goths. It produces a confident answer that is wrong in both directions.

  And the concept does not survive contact even given a perfect origin marker.
  "EA-made" would mean *started from an EA template* — not *is as EA made it*.
  A premade the player has renamed, remade, aged up and married off would still
  be flagged EA's, which is not what anyone asking the question means.
