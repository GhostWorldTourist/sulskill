---
name: sulskill-doctor
description: Diagnose The Sims 4 mod problems and audit a mod library — find conflicts, crash risks, duplicates, broken script mods, read the game's exception logs, and bisect the library when the logs name nothing. Use when the game crashes, hangs, misbehaves after adding mods, when a feature silently stops working, when the user does not know which mod is responsible, or when they want a health check of their mods.
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
2. **`mc_lastexception.html`**, written by MC Command Center into the Mods
   folder. **Read this before bisecting anything.** It dumps the failing frame
   *with its local variables and arguments*, where `lastException.txt` often
   carries only the downstream wreckage. In one real investigation it named the
   offending mod and the exact `TypeError` twenty-one times, in plain text,
   while twenty-five bisect rounds were spent narrowing towards it.
3. **Mod logs** (`mc_cmd_center.log`, `Andirz_SmartCoreScript.log`,
   `lot51_core.log`, `WickedWhimsInfoLog.log`, Basemental, MoreStudents). They
   timestamp each launch — use them to tell whether the game has even been run
   since a change.
4. **The packages themselves** — `scripts/deep_scan.py`.

## When the logs name nothing — bisect without fooling yourself

Sometimes the evidence above names nothing: the report blames a frame every run
produces, or there is no report at all. The library itself is then the only
instrument left — disable some mods, launch, see what changes. That works, and
the obvious way to do it is wrong.

**Only a clean round proves anything.** A clean round proves every cause is
inside the set you disabled. A failing round proves only that at least one cause
is still enabled — it says nothing about what you removed. The intuitive step,
*"I pulled that half and it still broke, so that half is innocent"*, is valid
only when there is exactly one culprit. Two mods that each break the load on
their own make every half you pull fail, because the other one is still there;
you then narrow into a set that never held the whole answer and spend the rest
of the investigation inside it. **The tell is single-mod rounds that all fail.**
If pulling A alone fails, and pulling B alone fails, and A and B were the only
candidates left, there was never one culprit and the narrowing that produced
that pair was fiction.

**After the first clean round, invert to add-back.** Hold the proven-clean
configuration and add mods *back* in groups. Both outcomes are now informative,
because everything outside the group is already known clean: a failure means a
cause is in what you just added, a clean run clears it. Add-back costs more
rounds per mod and finishes sooner. `scripts/bisect_mods.py` switches to it on the
first clean round and refuses to narrow on a failing round before then.

**Name a cause only by adding it back alone** to a clean base and watching that
fail. Elimination is not naming — "it must be the one left" assumes the single
culprit all over again. Once one is named, run the confirmation round with every
named cause removed and everything else live: a second cause only becomes
visible after the first is out of the way, and skipping that round is how an
investigation ends one mod early.

**Choose the symptom marker before round one, and require it to vary.** Pick the
artifact that distinguishes a good run from a bad one, not the loudest error in
the file. A mod whose exception appears in every run — including the clean ones —
is not the cause however convincing the defect inside it looks, and a failing run
with *no* such exception refutes it outright. The corollary is worth stating on
its own: **a suspect that was enabled during a clean round is not the always-on
cause.**

**Anchor every artifact to the round.** A report written before the launch says
nothing about the configuration now on disk; attributing one is how a round gets
scored backwards. Check its timestamp against the game process, and use the mod
logs at step 3 to confirm the game was even run since the change.

**Score after the failing action, not after the launch.** The load that breaks
is the one the player triggers, and the reports arrive minutes after startup. A
file read while it is still being written reported 0, then 4, then 7 findings for
one failed round. Wait for it to go quiet. Note also that **success can be the
absence of a file** rather than a zero inside one.

**"No exception file" is three different situations, and only one is a pass.**
The round passed; or nobody played it; or the game died before the first frame,
too fast to write a report and gone before any process poll could see it. They
are byte-identical from outside, so silence only means *clean* when something
else shows the game actually ran — the mod logs at step 3 answer that even after
it has exited. And while the game is still up, silence means *not answered yet*:
one round read as clean 51 seconds in and produced its failure at three minutes.
`bisect_mods.py` reports these as `IN PROGRESS` and `NO EVIDENCE` rather than
folding them into a pass.

**Launch the game from the tool** — `arm --launch`. The tester's one irreducible
job is watching the screen and saying what happened; making them go and start the
game as well hands back a context switch every round, twenty times over. The game
appearing *is* the instruction, which is also friendlier for anyone who does not
want to think about any of this. Set `SIMS4_LAUNCH_CMD` to go through a
storefront instead of the executable, so the round runs with whatever launch
options the player actually plays with. A process that never appears is a
*result* — a failure before the first frame is a different symptom — not a tool
error. Starting the game is the tool's job; deciding what happened is not.

**Confirm the mods you are testing are actually live.** "Installed" and "loaded"
are different claims: a package deeper than any `PackedFile` rule never loads
(`resource_cfg.py`), a script mod more than one folder deep or built for the
wrong Python never runs, and a mod sitting in a manager's staging folder with no
deploy is present in every inventory and absent from the game. A round that
changes none of the variables it thinks it changed reads exactly like a round
that exonerates something.

**When the candidate set is small enough to read, stop bisecting and read it.**
This is the lesson that costs the most to learn late. Halving is for sets too
large to inspect; at a couple of dozen mods it is usually cheaper to open the
`.ts4script` archives and look. Mods that ship their `.py` alongside the `.pyc`
can simply be read, and the answer is often a single shared idiom visible in
five minutes — after an hour of launches has not produced it.

**Scan `.pyc`, not just `.py`.** Most mods ship bytecode only, so a source-only
scan silently samples a biased subset and can make a routine idiom look like a
smoking gun. Search compiled members too (see the `zipimport` note under *Facts*
for why source-only archives still load).

### Guards as instruments

When a mod's own bug takes the load down, a wrapper around the failing method
that catches the error and **logs what it caught** is worth more than the fix.
It answers "was this mod involved?" in one launch, where bisection needs many,
and its log is evidence afterwards that the fault is real and how often it fires.

Catch exactly one exception type, so the guard cannot mask an unrelated failure,
and record enough to identify the tuning involved. Verify it against the real
method first: a guard written for a classmethod that meets a staticmethod raises
`TypeError` from inside the injection and takes down the load it was written to
protect — a containment fix that fails open is worse than none.

## Scripts

```bash
py scripts/bisect_mods.py      # isolate what breaks a load, without false clears
py scripts/deep_scan.py        # full audit -> report.json
py scripts/resource_cfg.py     # what actually loads; --fix removes redundancy
py scripts/snapshot.py         # diff mods vs last run; --save updates baseline
py scripts/variants.py         # alternatives installed side by side; stale builds
py scripts/moodprint.py        # who wins a contested buff, and what winning changed
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
flag and you would otherwise compare a state against itself. It compares against
the last saved snapshot, falling back to `index.pkl` and then to nothing; on
that last one every file reads as added, which is the honest answer on a first
run and leaves the script-validity check — which needs no baseline — running.

## Variant sets — two builds of one mod, both installed

Mods that offer a choice ship the choice as separate packages: `_casVer` or
`_RewardVer`, `10min` or `25min`, `Normal` or `Rough`. Install two and they do
not add up — they describe the same resources, so one silently overwrites the
other and which one wins is load order. The same shape appears when an update
lands beside the build it replaces instead of on top of it.

Neither shows up as a problem anywhere else. Both packages load, nothing errors,
and the game behaves like whichever one happened to win.

```bash
py scripts/variants.py               # -> variants.json, exit 1 if a set is found
py scripts/variants.py --min 0.4     # widen the net (default 0.60)
py scripts/variants.py --no-overlaps # only the sets it can actually name
```

**What decides it is the resource sets, not the names.** Two packages that are
alternatives describe the *same* resources with different content. Two packages
that are modules of one mod describe *different* resources. Filenames cannot
tell those apart — `Mod_EP02` and `Mod_EP03` look exactly like `Mod_10min` and
`Mod_25min` — so a shared name is only allowed to corroborate a shared resource
set, never to accuse on its own. Pairs that overlap heavily with nothing tying
them to one mod are reported separately, unjudged, because "two mods colliding"
and "a variant set whose naming does not say so" look identical from here. That
list is worth reading — it is where two different authors patching the same
buff shows up.

**The measure is containment, not Jaccard**, because alternatives differ by
exactly the resource that *is* the choice being made and Jaccard charges them
for it. Eight nanny schedules holding three resources each and agreeing on two
score 0.50 — under any sane Jaccard floor, and invisible. What matters is the
share of the *smaller* package the other one also describes: 0.67, reported.
The guard that keeps that honest is size. A three-resource patch sitting wholly
inside a five-hundred-resource mod is fully contained too, and it is an addon
overriding a subset, not an alternative to the whole; alternatives are near
enough the same size as each other. Below two resources a package is too small
to accuse anything on resources alone and needs the names to agree — six files
named `_Age_Adult`, `_Age_Elder` and so on, holding the same single resource,
are as total an overwrite as exists.

**Versions are read from the source archive first, then the filename.** Those
disagree often, and the filename is the one that lies: a package whose name
carries no version at all, sitting beside one named `_V1.7.3`, shipped inside
an archive named `_V1.10` and is the *newer* of the two. Trust the filename and
the tool recommends deleting the current build.
That dereference needs `vortex.deployment.json`, which lives in
`Mods\Vortex Mods\` and whose `relPath` values are relative to that folder, not
to `Mods\`. Without it, versions fall back to filenames and say so in the output.

Only builds of the *same* flavour supersede each other. Two flavours at one
version are a live choice, not a stale build, and nothing is safe to remove.

## Emotions — who won the argument, and what it changed

`variants.py` says two packages describe the same resources. `moodprint.py`
answers the question after it: **which one the game actually reads, and what the
winner does differently.** Buff tuning is where that matters most, because a
buff carries the mood it pushes and the weight it pushes with, and a mod that
overrides one takes the *whole* resource — not the field it meant to change.

```bash
py scripts/moodprint.py                 # ledger + hammers + what changed
py scripts/moodprint.py --mood Tense    # only buffs pushing one mood
py scripts/moodprint.py --mod chingyu   # only buffs won or lost by one mod
py scripts/moodprint.py --limit 0       # no truncation
```

Exit 1 if any override changed anything. Four sections:

- **Emotional ledger** — every *winning* buff by mood, with the mods
  contributing most. Counting every definition instead would inflate it by
  exactly the mods that are not running.
- **Override hammers** — weights far above normal (≥100). While one is active
  nothing else can outweigh it, and the mood's total stops meaning anything, so
  those moods are annotated rather than quietly summed.
- **Silenced** — a buff that moved an emotion and now does not, either because
  the winner dropped `mood_type` or set the weight to 0. The moodlet still
  appears in game, which is why this is invisible from inside it.
- **Every buff overridden** — packages where nothing survives.

**Load order is the whole answer, and it is decided by the filename.** The game
walks `Mods` in case-insensitive path order and the *last* read of a resource
key wins. Punctuation sorts ahead of letters, so a package named `!Addon…` is
read **first** and therefore loses to everything after it — the opposite of what
the `!` prefix is normally meant to do. Add-ons named that way to override their
own base mod lose every buff in them. That is why the report names the file as
well as the mod: the filename is the thing to change.

Weight absent is reported as unstated, never as 0. A buff that states weight 0
was deliberately silenced; one that states none was not, and collapsing them
reports a real change as no change.

## Resource.cfg — run this before believing an inventory

"The mod is installed and nothing happens" is usually this file. The game does
not walk `Mods\`; it loads exactly what the `PackedFile` globs match, and `*`
stops at a directory separator — which is why the file needs one rule per depth.
A package one folder deeper than the deepest rule is present, listed by every
tool here, and never read. Check it before theorising about conflicts:

```bash
py scripts/resource_cfg.py            # coverage + redundancy
py scripts/resource_cfg.py --fix      # merge repeated blocks and rules
```

**Fix the redundancy without being asked.** Installers and hand-edits append
rather than merge, so the file accumulates copies of itself; leaving that for
the player to notice is leaving a landmine in the one file that decides what
loads. `--fix` is safe to apply on sight because it cannot change the outcome —
it merges equal priorities and drops repeated globs, so the set of
(priority, glob) pairs and their order come out identical. It backs the file up
first, and rewrites **in place** rather than replacing, so a manager-deployed
hardlink stays linked and the staging copy is fixed with it.

**Unreachable packages are reported, never fixed.** Adding a depth rule changes
what loads, and that is the player's call — say which files are dark and let
them choose between a deeper rule and a flatter folder.

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

That pattern set matches creators, frameworks, and vocabulary — things that mean
the same on anyone's install. It deliberately holds no list of individual mods.
An adult mod with an innocuous name and nothing telling inside it cannot be
reached by any keyword, and hard-coding the ones from a particular library is a
mod list, which this repository does not ship. Those mods land on the keep list,
where `classify_adult.py` prints them under *anything that still looks
questionable* for a person to judge — the tool says it is unsure rather than
quietly guessing. To settle that judgement for your own install, put one regex
per line in `sulskill-doctor/adult_patterns.local`; it is gitignored, the same
way `_shared/reviewed.local` is, and for the same reason.

`apply_plan.py` turns that exclude list into the fewest Vortex search terms that
cover it, so a profile is a few search-and-select passes instead of hundreds of
clicks. The terms are derived from the mod names each run, and any term that
would also select something on the keep list is discarded — otherwise the plan
could tell you to Ctrl+A a block with a keeper in it and show no sign it had.
An unchanged library gives the same plan every time, so re-running it and
diffing tells you something.

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
- **A stale injector wrapper takes down the whole tuning load, and the error
  names it.** `InstanceManager.load_data_into_class_instances(self,
  packs_to_load=None)` gained its second parameter; mods generated before that
  declare their wrapper as `(original, self)` and are handed three positionals
  through the usual `_inject(*args)` shim. The result is
  `TypeError: <name>() takes 2 positional arguments but 3 were given`, raised at
  `instance_manager.py:251` — which is **not inside any try/except**. It escapes,
  the service manager logs "Error during initialization of service" and
  **abandons the tuning service**, and the game loads a zone with tuning
  half-applied. Every manager registered after the failure point never loads and
  no `_tuning_loaded_callback` runs for anyone.

  The visible result is not "a mod feature is missing". It is
  `venue_residential` without `sub_venue_types`, a fish bowl with no
  `inventory_component`, a default posture of `None`, and households that will
  not load — none of which mention the mod at fault.

  **This is checkable without a bisect.** Scan `.ts4script` archives for
  functions installed onto that method and count their parameters: two is the
  bug, `*args`/`**kwargs` or an explicit `packs_to_load` is fine. The fix is to
  update the mod. On a 1,300-mod library, sixteen mods wrapped the method and
  only the stale ones were fatal — so "many mods do this" is not a reason to
  suspect any of them.
- **Injector chains are a real crash class.** Many mods wrap
  `load_data_into_class_instances`. An old mod whose injected function has a
  fixed signature dies when a newer mod passes `*args` — the error names the
  function, e.g. `rexchooseclassmate_add_superaffordances() takes 2 positional
  arguments but 3 were given`. `deep_scan.py` lists chain members by date;
  oldest = highest risk.

## Judgment

- Report **verified vs inferred** explicitly. Say which is which.
- Prefer one decisive test over a third theory. Disabling all mods for a single
  launch splits "mod problem" from "game problem" instantly. Past that, see
  *When the logs name nothing* — the narrowing that feels obvious there is
  unsound, and it fails silently.
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
