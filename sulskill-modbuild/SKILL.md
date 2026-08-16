---
name: sulskill-modbuild
description: Author Sims 4 mods from scratch - write .package (DBPF) files, generate SimData resources, and compute tuning instance ids, without copying resources from other creators' mods. Use when building or repairing a Sims 4 tuning mod, adding a custom trait/buff/loot, or when a mod needs a SimData resource.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Sims 4 mod building

Write `.package` files whose every resource is generated, so nothing of another
creator's is redistributed.


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

## Why SimData is the hard part

A custom Trait or Buff needs a matching **SimData** resource (type
`0x545AC67A`). Measured across a 2328-package sample:

| | with SimData | without |
|---|---:|---:|
| Trait | 781 | 3 |
| Buff | 3115 | 19 |

Under 1% ship bare, so treat it as mandatory. The tempting shortcut is to copy a
SimData blob out of another mod — **don't**. Those blobs carry the original
author's identifying strings (`PECO:trait_isCindyRotique`,
`Andirz_RandomSim_Buff_Hidden_MakePansexual`) and shipping them redistributes
their work. `scripts/simdata.py` builds the bytes instead.

## SimData format — the parts that cost time

Established by round-tripping real resources, not from documentation:

- **Every offset is relative to the field that holds it.** A pointer at absolute
  position `P` holding `V` points at `P + V`. Writing therefore needs two passes:
  lay out the bytes, then back-fill each pointer once its own address is known.
- **Name hashes are FNV-1 over the LOWERCASED name.** Not FNV-1a, and not the
  original casing. Verified: `fnv1(lower("PECO:trait_isCindyRotique")) ==
  0xD736EE1D`, matching the stored value; FNV-1a and as-is casing both differ.
  Note this is a *different* hash from the 64-bit tuning instance id, which is
  FNV-1a with the high bit set.
- **A schema's `name_hash` is not a string hash** — it is the tuning **type id**
  (Trait `0xCB5FDDC7`, Buff `0x6017E896`).
- **`schema_hash` identifies the column layout and changes between patches.**
  EA's current Buff schema is 12 columns / 96-byte rows; older mods carry a
  10-column / 80-byte version. Re-run `extract_ea_schema.py` after a game patch.
- Table `data_type` is `0x0D` for these single-object tables.
- Column offsets are **not** sequential or alphabetical. They are EA's layout and
  must be reproduced exactly or the loader misreads the row.

## Where the schema comes from, and why that matters

`reference/simdata_schema.json` is extracted by `scripts/extract_ea_schema.py`
from **EA's own packages** (`Data/Client/*.package`), not from any modder's file.
Two reasons, and both matter:

1. **Correctness** — the column names, types and offsets describe how the game's
   binary loader reads a Trait or Buff. Anything else misreads it.
2. **Provenance** — it is the platform vendor's interface, the thing we must
   match to interoperate, rather than a peer creator's authored content.

Regenerate it after a patch; it needs the game installed.

## The audit gate

`dbpf.audit(path, forbidden)` scans every decompressed resource for byte-strings
that must never ship. Wire it into each mod's build as `--audit` and run it in
CI, so a package can never quietly regain a foreign identifier.

## Usage

```bash
py scripts/simdata.py                    # self-test: build + reparse Trait and Buff
py scripts/simdata.py some.simdata       # dump a real resource's structure
py scripts/extract_ea_schema.py          # regenerate the schema after a patch
py scripts/stbl.py --search "aristocratic"   # find game text and its key hash
py scripts/stbl.py --key 0x43CAAED5          # resolve one key hash to its text
```

`scripts/stbl.py` turns the game's English string table into `{key_hash: str}`,
which is how a tuning key hash becomes readable text. It decompresses with
RefPack, not zlib - `dbpf.read()` knows zlib only and returns EA's resources
still compressed, with no error raised.

```python
import dbpf, simdata
inst = simdata.fnv64("abc:trait_MyMarker")   # abc = your namespace prefix
dbpf.write("Mod.package", [
    (dbpf.T_TRAIT,   0, inst, trait_xml.encode()),
    (dbpf.T_SIMDATA, dbpf.SIMDATA_GROUP[dbpf.T_TRAIT], inst,
     simdata.build_trait("abc:trait_MyMarker")),
])
```

## Naming conventions

Pick a short namespace prefix for the author and use it everywhere — tuning
names, `creator_name`, package filenames. Ask them what to use; do not invent
one, and do not reach for their system account name, which is rarely the name
they publish under.

- **Tuning namespace**: `<prefix>:trait_Whatever`. It only has to be unique
  across installed mods, so a personal prefix is enough. Feeding the whole
  namespaced string to `fnv64` is what keeps two creators' identically-named
  traits from colliding.
- **Package filenames**: prefix them too. It is how a player identifies the
  source of a conflicting file months later, and how they find every file of
  yours to remove it.
- The `.package` is a build artifact: gitignored, built by CI, attached to
  releases. Never committed, so the download always matches its source.

## Known limits

- Generated rows are **zero-filled**. For a hidden trait/buff every field is
  either unset or carried by the XML tuning, and SimData only has to present a
  correctly shaped schema. This is the part that warrants an in-game check —
  a malformed SimData fails silently rather than erroring.
- Only Trait and Buff schemas are extracted so far. Other tuning classes need
  `extract_ea_schema.py` widened.
