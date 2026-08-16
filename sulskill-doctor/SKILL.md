---
name: sulskill-doctor
description: Diagnose The Sims 4 mod problems and audit a mod library — find conflicts, crash risks, duplicates, broken script mods, and read the game's exception logs. Use when the game crashes, hangs, misbehaves after adding mods, when a feature silently stops working, or when the user wants a health check of their mods.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Sims 4 doctor

Forensic tooling for a large modded install. Reads DBPF packages directly rather
than guessing from filenames.


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
py scripts/manifest.py         # one-line description per mod; --hide-nsfw to omit
py scripts/commands.py         # console commands each script mod registers
py scripts/commands_doc.py     # curated JSON -> a markdown doc (--out required)
py scripts/commands_html.py    # curated JSON -> a searchable page (--out required)
```

`deep_scan.py` reports: byte-identical duplicate packages, EA tuning overridden
by 2+ mods (real conflicts), every package that overrides EA tuning with its
date, all resource TGI collisions by type, and per-script validity.

`snapshot.py` only writes its baseline with `--save` — run it twice without the
flag and you would otherwise compare a state against itself.

## Console commands

There is no bundled command list, deliberately. A list of commands is a list of
installed mods, and that describes one person's machine — this skill ships the
tools that build it, never the output. Build it fresh against whatever library
is actually in front of you:

```bash
py scripts/commands.py --json raw.json      # every command actually installed
py scripts/commands.py --mod kuttoe         # narrowed to one mod
```

`commands.py` reads compiled scripts rather than trusting a wiki. Two passes,
and the second one matters: heavily obfuscated mods — MCCC and WickedWhims
among them — do not disassemble, so their command names are recovered from
string constants instead and marked *unverified*. A disassembly-only tool
reports the library's two biggest mods as having no commands at all.

Turning a raw scan into a document means judging which of a thousand-odd
commands a player would care about, and that is reading work, not pattern work.
It is also embarrassingly parallel and does not need your strongest reasoning:
**split the mods into batches and hand each to a cheaper, faster agent tier if
your harness has one**, then merge. Have each batch write its own file rather
than return the JSON in a message — a crashed session loses the message and
keeps the file.

Feed whatever comes back through the builders rather than writing the document
by hand. Both re-scan and drop any command the library does not actually
register, so a half-remembered command name cannot reach the page:

```bash
py scripts/commands_doc.py  curated/*.json --out ~/Downloads/commands.md
py scripts/commands_html.py curated/*.json --out ~/Downloads/commands.html
```

`--out` is required on both and must point outside the repository. `--adult-out`
(markdown) and `--include-adult` (html) control whether adult mods appear, using
the same pattern set as `classify_adult.py`.

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

## Reading a BetterExceptions conflict report

`tm.be.conflictscan` in game writes `BE-ConflictReport.html` under
`Mods\...\TMEX-Settings\`. Parse it with `scripts/be_report.py`.

**It is not an inventory.** On a 2,330-package library it named 114 packages and
zero script mods - it lists only what COLLIDES. For a full mod list use MCCC's
`GetSystemInfo` (shift-click a Sim -> Sim Commands -> Logging Commands), which
walks the whole Mods tree and includes `.package`, `.ts4script` and `.zip`.

### A collision is not a bug until you diff it

The report says two mods provide the same resource. It does not say whether that
matters. `--diff MODNAME` pulls the colliding resource out of both packages and
shows what actually differs - that is the step that turns "a conflict was
reported" into "here is what you lose". Three outcomes, all real:

- **Identical** - harmless, whichever wins is the same file.
- **Metadata** - differs but has no gameplay effect. Three Andirz mods each ship
  a `SmartCoreModInfoSnippet` under the SAME instance id, so only one registers.
  That is a bug in their framework, not something the player can fix, and it
  changes nothing in play. `METADATA_CLASSES` in the script marks these.
- **Divergent behaviour** - the one that costs you something. Example:
  `z_MCM_goLater` and `HighSchool_MoreStudents` both rewrite EA's
  `weeklySchedule_HighSchool_Active_Career` snippet (188 vs 203 lines, student
  caps 50 vs 30, different time windows). Last loaded wins, so you get one mod's
  schedule and silently lose the other's.

### Same author does not mean safe

The instinct that two mods by one creator must be coordinated is wrong often
enough to be dangerous. `goLater` and `MoreStudents` share an author and still
overwrite each other's work; two RVSN candy-bowl mods both ship
`RVSN:candyBowl_GrabTreat_oct2020` at slightly different sizes. Always diff.

### Severity is a heuristic, and it is blunt

`TYPES` scores by resource type: StringTable and Image collisions are noise,
tuning collisions are not. That gets the triage order roughly right and is wrong
in individual cases - it scored the Andirz metadata snippets "high". Use it to
sort, then diff before acting.

```bash
py scripts/be_report.py                      # all pairs, worst first
py scripts/be_report.py --severity high
py scripts/be_report.py --exclude taylor --exclude mariah   # hide fixed ones
py scripts/be_report.py --diff goLater       # what do I actually lose?
py scripts/be_report.py --mods               # every mod named, by hit count
```
