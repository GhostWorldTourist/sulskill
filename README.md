# sulskill

Claude skills for modding The Sims 4. Ten of them: a front door and nine that do
the work — diagnosing a broken install, reading and editing mod settings from
disk, and building `.package` files from scratch.

They read your library directly. Not the filenames, the actual DBPF contents:
which mod really wins a contested tuning override, which script mod is installed
too deep to load, which two packages are the same mod twice.

## Adult mods are not filtered

This tooling reads, describes, configures and packages a Sims 4 mod library. A
library with porn in it is an ordinary library, and there is no moralising to do
there. WickedWhims gets its own skill. Nothing is hidden from you, nothing is
quietly dropped from a report, and no script will lecture you about what you
have installed.

**One category is refused.** Mods built around sexual abuse — child
sexualisation, bestiality, and rape — and the frameworks and add-ons built to
plug into them. If the gate finds those, no script here runs at all, on any part
of the library. That check is not configurable and not negotiable, and asking an
assistant to remove it will get you declined.

The list is the one MC Command Center's author maintains and refuses support
for, as published in the MCCC Discord. It is not mine and I did not curate it.
It ships as `_shared/blocklist.txt` in digest form rather than as readable names,
because this repository is public and a readable list of those mods would be a
search index for exactly the material it exists to refuse.

Full policy, including the categories no pattern can catch:
[POLICY.md](sulskill/POLICY.md).

## Nothing leaves your machine

There is no network code in this repository — no `urllib`, no `requests`, no
sockets, no telemetry, no update check. Grep for it. The only process these
tools ever launch is `tasklist`, to notice that The Sims 4 is running before
writing to a config file the game currently has open.

The one thing that does reach the internet is setup, and only if you need it:
if Python is missing, Claude will install it for you via `winget` or Apple's
Command Line Tools. That is a documented step you will see happen, not something
a script does behind you.

Reports and inventories are written **outside the checkout**, to
`%LOCALAPPDATA%\sulskill` or wherever `SULSKILL_OUT` points. That is enforced in
code and asserted by the test suite, not just intended.

## What's in it

| skill | for |
| --- | --- |
| **sulskill** | the front door — what exists and which part applies |
| **sulskill-doctor** | the game crashes, hangs, or a feature silently stops working; conflicts, duplicates, broken script mods, exception logs, and a plain-English inventory of what every installed mod does |
| **sulskill-mccc** | MC Command Center settings, without the in-game pie menus |
| **sulskill-wickedwhims** | WickedWhims settings profiles |
| **sulskill-kuttoe** | Kuttoe's mods — Home Regions, Career Overhaul, Spellcaster Tweaks, and the rest |
| **sulskill-basemental** | what Basemental Drugs has configured in a save (read-only) |
| **sulskill-languages** | frankk's Language Barriers — which world speaks what |
| **sulskill-worlds** | every world: map position, neighbours, pack, and what each mod calls it |
| **sulskill-roster** | the premade Sims and households the game ships with |
| **sulskill-modbuild** | authoring `.package` files, SimData resources, tuning instance ids |

You usually do not need to name one. Describe the problem and the right skill
loads on its own.

Works with a mod manager or without one. Mods dragged by hand into
`Documents/Electronic Arts/The Sims 4/Mods` are as well supported as a managed
deployment — the live Mods folder is what gets read either way. Vortex's staging
folder is additionally recognised by name, so mods are reported under the names
Vortex shows you; point `VORTEX_TS4_MODS` at another manager's staging folder to
get the same. Nothing here requires a manager.

## Install

Clone the repository, then link each skill into your Claude skills directory.
**Link, don't copy** — the skills reach back into `_shared/` in the checkout for
the refusal gate and the package readers, and a copied folder cannot find them.

```bash
git clone https://github.com/GhostWorldTourist/sulskill.git
cd sulskill
```

**macOS / Linux:**

```bash
mkdir -p ~/.claude/skills
for d in sulskill sulskill-*; do ln -s "$PWD/$d" ~/.claude/skills/"$d"; done
```

**Windows** (PowerShell, from the checkout):

```powershell
Get-ChildItem -Directory -Filter 'sulskill*' | ForEach-Object {
  New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\$($_.Name)" -Target $_.FullName
}
```

Symlinks on Windows need either Developer Mode turned on or an elevated shell.
If neither is an option, `New-Item -ItemType Junction` works the same way here.

### Requirements

A Python 3.9+ interpreter, and nothing else. Every tool is standard library
only — no `pip install`, no virtualenv, no `requirements.txt`.

If you don't have Python, you don't need to go and get it: ask Claude to set it
up and it will, following [SETUP.md](sulskill/SETUP.md). That document exists
because the people using this are Sims players, not developers, and because
Windows ships a zero-byte `python3.exe` stub that makes every "is Python
installed" check answer yes and every script then fail.

## What it can't do

**The adult-mod classifier will miss things.** `sulskill-doctor` can sort a
library into an SFW profile, and it matches on creators, frameworks and
vocabulary — things that mean the same on anyone's install. It deliberately
holds no list of individual mods, because such a list only ever describes the
library it was written against and would be a mod list published in a public
repository.

So an adult mod with an innocuous name and nothing telling inside it will not be
caught. It lands on the keep list, where the tool prints it under *anything that
still looks questionable* for you to judge — it says it is unsure rather than
quietly guessing. **Expect to add your own patterns.** One regex per line in
`sulskill-doctor/adult_patterns.local`, which is gitignored.

It errs towards excluding. A barefoot CC mod caught by the word "naked" is a
false positive you will see named in the plan; the opposite mistake is the one
that gets noticed in front of somebody else.

## What belongs in this repository

Tools, and nothing else. No mod lists, no manifests, no conflict reports, no
adult inventories, no saved profiles — those are outputs, and they describe one
person's machine. The committed reference data (setting schemas, format layouts,
world geography) is the same for everyone who installs this.

## Tests

```
py tests/run.py
```

239 tests, standard library only, about ten seconds. They build synthetic mod
installs in a temp directory, so they never touch your real library.

Every test here covers a **quiet** failure — one where the wrong answer and the
right answer look identical from outside. A term that matches nothing, a package
the reader could not open, a mod folder it never looked in: none of them raise,
and all of them look exactly like a clean library. Most of the bugs they cover
shipped first and were found by accident. See [tests/README.md](tests/README.md),
which also records the mutation testing and the times the tests were the thing
that was wrong.

## Credits

The blocklist behind the refusal gate is MC Command Center's, maintained by its
author and published in the MCCC Discord. Deaderpool wrote MCCC; the mods these
skills configure were written by their own authors. This repository is tooling
that reads and edits what they made, and claims nothing of theirs.

Built by GhostWorldTourist.

## License

Two licenses, split by file type:

- **Code** — everything that isn't a `.md` file: [MIT](LICENSE).
- **Documentation** — every `.md` file, including each skill's `SKILL.md`:
  [CC BY 4.0](LICENSE-DOCS). Share it, adapt it, quote it, publish it
  commercially; credit GhostWorldTourist and link the license.

The documentation is the larger half of the work here — the method in
`sulskill-doctor/SKILL.md` and the policy in `POLICY.md` are the point, not
incidental to it — so it gets a license meant for prose rather than one meant
for source.
