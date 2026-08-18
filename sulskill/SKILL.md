---
name: sulskill
description: The front door to the sulskill family of Sims 4 skills - what each part does and which one applies. Use when someone asks what these Sims 4 skills can do, wants an overview before starting, is not sure which part they need, or asks about modding The Sims 4 in general terms without naming a specific mod or problem.
---

# sulskill

Nine skills for modding The Sims 4. They are separate so that only the relevant
one loads — an answer about world geography should not be reasoning through
WickedWhims settings — but they share one refusal policy, one setup, and one
house style.

**You usually do not need to name a part.** Describe the problem and the right
one loads on its own. This page is for when you want to see what exists.

## Diagnosing and auditing

| part | for |
| --- | --- |
| **sulskill-doctor** | the game crashes, hangs, or a feature silently stops working; finding conflicts, duplicates, broken script mods; reading exception logs; describing what every installed mod does |

Start here when something is *wrong* and you do not yet know why.

**Reference on the base game itself** — format rules, load-order and hashing
facts, and the baselines a claim about a mod should be read against — is in
[BASEGAME.md](BASEGAME.md). Read it before concluding that two resources
conflict, that a hash does not match, or that a value read out of SimData is
what it appears to be.

## Configuring a specific mod

| part | for |
| --- | --- |
| **sulskill-mccc** | MC Command Center settings, without the in-game pie menus |
| **sulskill-wickedwhims** | WickedWhims settings profiles |
| **sulskill-kuttoe** | Kuttoe's mods — Home Regions, Career Overhaul, Spellcaster Tweaks, and the rest |
| **sulskill-basemental** | what Basemental Drugs has configured in a save (read-only) |
| **sulskill-languages** | frankk's Language Barriers — which world speaks what |

## Knowing the game

| part | for |
| --- | --- |
| **sulskill-worlds** | every world: map position, neighbours, pack, and what each mod calls it |
| **sulskill-roster** | the premade Sims and households the game ships with |

## Building mods

| part | for |
| --- | --- |
| **sulskill-modbuild** | authoring `.package` files, SimData resources, tuning instance ids |

## Before anything runs

These are Python tools, standard library only — nothing to install beyond an
interpreter. Most Sims players do not have one, so **detect it by running it,
not by checking PATH**, and install it for the person rather than asking them
to: [SETUP.md](SETUP.md).

Every part also enforces one refusal policy, checked before any script does
work: [POLICY.md](POLICY.md).

Changing any of the shared machinery — the gate, the package readers, mod
discovery — run `py tests/run.py` from the repository root, where `tests/README.md`
explains what each file covers. Standard library only, well under a second. The
suite lives in the repository, not in an installed skill, so it is there when
you have the checkout and absent when you only have the skill.

## Works with or without a mod manager

Mods installed by hand in `Documents/Electronic Arts/The Sims 4/Mods` are as
well supported as a manager's deployment. Nothing here requires Vortex.
