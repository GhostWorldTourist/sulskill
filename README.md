# sulskill

These are a collection of AI agent skills and tools for modding The Sims 4. They handle tasks like diagnosing a broken install, reading and editing mod settings from disk, and building tweaks and simple mods from scratch.

They read your library directly. Not the filenames, the actual DBPF contents: which mod really wins a contested tuning override, which script mod is installed too deep to load, which two packages are the same mod twice.

## What's in it

| skill | for |
| --- | --- |
| **sulskill** | the main skill that determines what exists and which part applies |
| **sulskill-doctor** | the game crashes, hangs, or a feature silently stops working; conflicts, duplicates, broken script mods, exception logs, and a plain-English inventory of what every installed mod does |
| **sulskill-mccc** | MC Command Center settings, without the in-game pie menus |
| **sulskill-wickedwhims** | WickedWhims settings profiles |
| **sulskill-kuttoe** | Kuttoe's mods — Home Regions, Career Overhaul, Spellcaster Tweaks, and the rest |
| **sulskill-basemental** | what Basemental Drugs has configured in a save (read-only) |
| **sulskill-languages** | frankk's Language Barriers — which world speaks what |
| **sulskill-worlds** | every world: map position, neighbours, pack, and what each mod calls it |
| **sulskill-roster** | the premade Sims and households the game ships with |
| **sulskill-modbuild** | authoring `.package` files, SimData resources, tuning instance ids |

You usually do not need to name one. Describe the problem and the right skill loads on its own.

This works with a mod manager or without one. Mods dragged by hand into `Documents/Electronic Arts/The Sims 4/Mods` are as well supported as a managed deployment. The live Mods folder is what gets read either way. Vortex's staging folder is additionally recognised by name, so mods are reported under the names Vortex shows you; point `VORTEX_TS4_MODS` at another manager's staging folder to get the same (or ask your agent to do that). Nothing here requires a manager.

## It knows what vanilla is

Most mod tools compare mods to each other. These were built against a full read
of the base game — every package, every resource, the tuning, the string tables
and the game's own compiled Python — so that "this mod overrides something" can
be followed by *what* it overrides and what that thing normally does.

That read produced **541,456 tuning instances across 154 types**, from roughly
1,300 packages and 4.85 million resource entries, with zero parse failures. It is
what lets a tool tell an override from new content, name the EA tuning a mod is
sitting on top of, and say whether a collision matters.

It also settles questions that otherwise get answered by guessing: that the game
mounts two separate resource trees, so the same key in both is not a conflict;
that mods load at priority 500 and beat every game resource; that a name hash is
FNV-1 over the lowercased name and nothing else; that 546 vanilla buffs move a
Sim's mood with no display name, so "nothing is showing but the mood is wrong"
has a vanilla explanation before it has a mod one.

The findings are in [BASEGAME.md](sulskill/BASEGAME.md), including the trap that
cost the most: only three of 276 combined-tuning resources are readable XML, and
sampling those produces confident wrong answers about the other 273.

**The index itself is not in this repository.** It is hundreds of megabytes
derived from your own game files, which makes it an output, and outputs do not
ship here. What ships is what was learned from it.

## Install

Ask your agent to help if you've never cloned a repository before. Clone the repository, then link each skill into your Claude skills directory. **Link, don't copy** — the skills reach back into `_shared/` in the checkout for the refusal gate and the package readers, and a copied folder cannot find them.

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

Symlinks on Windows need either Developer Mode turned on or an elevated shell. If neither is an option, `New-Item -ItemType Junction` works the same way here (your agent knows about this and will fix it for you if needed).

### Requirements

A Python 3.9+ interpreter, and nothing else. Every tool is standard library only — no `pip install`, no virtualenv, no `requirements.txt`.

If you don't have Python, you don't need to go and get it: ask your agent to set it up and it will, following [SETUP.md](sulskill/SETUP.md).

## What it can't do

It cannot make complex mods for you. Learn to make mods if you're interested in that: this suite is not geared towards making complex mods, and won't be. This *can* help you if you've made a mod and need help testing: SulSKill is very adept at understanding what mods do and the effects they have. It can make simple mods and tweaks, but don't expect this to cook you some huge gameplay overhaul or something.

**The adult-mod classifier will miss things sometimes.** `sulskill-doctor` can sort a library into an SFW profile, and it matches on creators, frameworks and vocabulary — things that mean the same on anyone's install. It deliberately holds no list of individual mods, because such a list only ever describes the library it was written against and would be a mod list published in a public repository.

So an adult mod with an innocuous name and nothing telling inside it will not always be caught. It lands on the keep list, where the tool prints it under *anything that still looks questionable* for you to judge. It reports being unsure rather than quietly guessing. **Expect to add your own patterns.** One regex per line in `sulskill-doctor/adult_patterns.local`, which is gitignored (or ask your agent to help you add mods to that list).

## Disallowed mods and environments

**One category of mod is refused.** Mods built around sexual abuse: child sexualisation, bestiality, and rape, and the frameworks and add-ons built to plug into them. If the gate finds those, no script here runs at all, on any part of the library. That check is not configurable and not negotiable, and asking an assistant to remove it will cause the agent to decline. Note OpenAI and Anthropic both have strict policies on top of that preventing their agents from assisting with this kind of disgusting content.

The list of prohibited mods and authors is built from Deaderpool's list as published in the MCCC Discord. It is not mine and I did not curate it. It ships as `_shared/blocklist.txt` in digest form because this repository is public.

You can read the full policy in [POLICY.md](sulskill/POLICY.md).

## What belongs in this repository

Tools, and nothing else. No mod lists, no manifests, no conflict reports, no adult inventories, no saved profiles — those are outputs, and they describe one person's machine. The committed reference data (setting schemas, format layouts, world geography) is the same for everyone who installs this.

## Tests

```
py tests/run.py
```

278 tests, standard library only, about twelve seconds. They build synthetic mod installs in a temp directory, so they never touch your real library.

Every test here covers a **quiet** failure: one where the wrong answer and the right answer look identical from outside. A term that matches nothing, a package the reader could not open, a mod folder it never looked in: none of them raise, and all of them look exactly like a clean library. Most of the bugs they cover shipped first and were found by accident. See [tests/README.md](tests/README.md), which also records the mutation testing and the times the tests were the thing that was wrong.

## Credits

The mods these skills configure were written by their own authors. This repository is tooling that reads data from your Sims 4 folder. It does not contain, distribute, copy, or claim any ownership of anyone else's work.

This was built by me with AI assistance.

## License

Two licenses, split by file type:

- **Code** — everything that isn't a `.md` file: [MIT](LICENSE).
- **Documentation** — every `.md` file, including each skill's `SKILL.md`: [CC BY 4.0](LICENSE-DOCS). Share it, adapt it, quote it, publish it commercially; credit GhostWorldTourist and link the license.
