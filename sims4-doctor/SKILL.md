---
name: sims4-doctor
description: Diagnose The Sims 4 mod problems and audit a mod library — find conflicts, crash risks, duplicates, broken script mods, and read the game's exception logs. Use when the game crashes, hangs, misbehaves after adding mods, when a feature silently stops working, or when the user wants a health check of their mods.
---

# Sims 4 doctor

Forensic tooling for a large modded install. Reads DBPF packages directly rather
than guessing from filenames.

## Diagnose first, theorize second

Failures here are usually **silent** — an empty picker, a config in the wrong
folder, a modal with no content. Guessing produces confident wrong answers.
Order of evidence:

1. **Exception files** in `Documents\Electronic Arts\The Sims 4\`:
   - `lastException.txt` — Python/gameplay. With Better Exceptions installed it
     names the offending mod and reports `TuningLoadFinished`.
   - `lastUIException.txt` — ActionScript/UI. **A different layer.** A UI-only
     failure leaves `lastException` clean, so "no exceptions" is not health.
   - The game archives these as `lastException_<timestamp>.txt` on next launch,
     so an un-suffixed file means "thrown during the most recent session".
2. **Mod logs** (`mc_cmd_center.log`, `Andirz_SmartCoreScript.log`,
   `lot51_core.log`, `WickedWhimsInfoLog.log`, Basemental, MoreStudents). They
   timestamp each launch — use them to tell whether the game has even been run
   since a change.
3. **The packages themselves** — `scripts/deep_scan.py`.

## Scripts

```bash
py scripts/deep_scan.py        # full audit -> report.json
py scripts/snapshot.py         # diff mods vs last run; --save updates baseline
py scripts/classify_adult.py   # bucket mods adult / adjacent / keep
```

`deep_scan.py` reports: byte-identical duplicate packages, EA tuning overridden
by 2+ mods (real conflicts), every package that overrides EA tuning with its
date, all resource TGI collisions by type, and per-script validity.

`snapshot.py` only writes its baseline with `--save` — run it twice without the
flag and you would otherwise compare a state against itself.

## Facts that make the analysis work

- **DBPF**: header 96 bytes; entry count at 0x24, index size at 0x2C, index
  offset at 0x40 (u64). Index starts with a flags word saying which of
  type/group/instance-hi are constant. Compression `0x5A42` = zlib.
- **Tuning type IDs are per-class** (Buff `0x6017E896`, LootActions `0x0C772E27`,
  …) — there is no single "tuning" type. `0x220557DA` is **STBL**, not tuning.
  Detect tuning by decompressing and looking for a leading `<I`/`<M` element;
  strip the UTF-8 BOM first or you will miss most of it.
- **EA ships no standalone tuning** — it lives in one large binary combined-tuning
  blob, so EA names cannot be read that way. But a mod that *overrides* EA tuning
  keeps EA's name and uses a **small integer instance ID** (`< 2**32`), while
  mod-authored tuning uses large 64-bit hashes. That heuristic finds real
  overrides fast and is the backbone of conflict detection.
- **Script mods** must be ZIP archives no more than one folder deep inside
  `Mods\`. Bytecode must be **Python 3.7** (pyc magic `3394`); a newer magic only
  survives if a matching `.py` is also in the archive (zipimport falls back).
- **UI mods replace whole bundles, not panels.** Type `0x62ECC59A` resources are
  large shared UI layout bundles (~1.4–1.9 MB each; EA ships 258 in
  `Data\Client\UI.package`). Two UI mods "conflict" when both ship an edited copy
  of the same bundle — the later one wins **wholesale**, with no merging. Do not
  infer which on-screen panel is affected from the mod's name; the bundles are
  not organised per panel. To tell a compat build from a plain one, diff the
  ASCII symbols: a merged build retains the other mod's symbols (0–1 missing),
  an unmerged one drops several.
- **Injector chains are a real crash class.** Many mods wrap
  `load_data_into_class_instances`. An old mod whose injected function has a
  fixed signature dies when a newer mod passes `*args` — the error names the
  function, e.g. `rexchooseclassmate_add_superaffordances() takes 2 positional
  arguments but 3 were given`. `deep_scan.py` lists chain members by date;
  oldest = highest risk.

## Judgment

- Report **verified vs inferred** explicitly. Say which is which.
- Prefer one decisive test over a third theory. Disabling all mods for a single
  launch splits "mod problem" from "game problem" instantly.
- Sort findings by whether they can break a save, not by how many there are.
  Thousands of CC texture collisions are normal; one stale tuning override is not.
