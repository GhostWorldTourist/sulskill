---
name: sulskill-basemental
description: Read and explain what Basemental Drugs currently has configured in a Sims 4 save - cannabis and gambling legality per world, police severity, parental reactions, criminal records - and advise on what settings to change in-game. Read-only by design. Use when the user asks what Basemental settings are set, what a Basemental setting does, or which worlds have legalised.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Basemental Drugs config

**This skill reads and advises. It does not write.** That is a design decision,
not a limitation — see below.


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

## Why there is nothing to edit

Basemental stores its settings as **traits stamped onto every human teen-or-older
Sim in the save**:

```python
add_trait(trait_id):            # utilities/library.pyc
    sim_info_manager().get_all()
      → species == HUMAN
      → age >= TEEN
      → add_trait to each
```

There is no settings file. `saves\BasementalDrugs\*.json` holds only general
per-save values (beer crafting, dust rate, eco footprint) — never legalisation.

It self-heals: `_update_basemental_preliminary_save_data` runs at save-load and
calls `add_traits_based_on_sim_trait_check`, which is *if any Sim has LEG_X, give
LEG_X to all Sims*. So new townies, Sims ageing into teen, and Gallery imports
are all stamped on the next load. Losing a Sim loses nothing.

The in-game menu reads the **active Sim** (`sim_has_trait` defaults to
`active_sim_info`) as a proxy for world state, because every Sim carries
identical flags. Write to everyone, read from whoever's handy.

**Consequence:** the only ways to change a setting are Basemental's own menu or
`traits.equip_trait` + a reload to propagate. A mod that equipped these traits
would be a second configurator fighting the first, so this skill does not try.
Guide the user through the in-game menu instead.

## Reading state

```bash
py scripts/bmd.py state              # newest save
py scripts/bmd.py state --save <path>
py scripts/bmd.py menus              # the 23 in-game settings menus
py scripts/bmd.py traits POLICE_     # look up trait ids
```

`state` harvests protobuf varints from the save's `0x0D` sim resource and matches
them against known trait ids.

**The method is validated, and validating it matters**: on a real save it finds
EA's own ids at plausible counts — `34318` (young adult) on 102 Sims, `276492`
(attracted to women) on 60. That is what licenses reading an *absent* id as
"genuinely not set" rather than "scan missed it". Re-check that control if the
save format ever changes.

**Settings only reach the save on save.** A setting made in the UI this session
is invisible to this tool until the user saves the game. If `state` reports
nothing set and the user insists otherwise, that is the first thing to check —
not a bug.

Prefer a real `Slot_00000NNN.save`; `Slot_ffffffff.save` is the in-progress slot.

## The settings surface

23 menus. The ones with real consequences:

| Menu | Controls |
|---|---|
| `legalize` | cannabis legality, 27 worlds, one `LEG_*` trait each |
| `legalize_gambling` | same 27 worlds, `LEG_GAMBLING_*` |
| `police` | `POLICE_EASY` / `POLICE_HARD` / `POLICE_NOBUSTS` / `POLICE_SHUTDOWN` |
| `reactions` | `PARENTAL_CANNABIS`, `PARENTAL_ALCOHOL`, `PARENTAL_TOBACCO`, … |
| `addiction`, `cheats_addiction` | predisposition and per-substance cheats |
| `npc` | dealer NPCs |

**Police severity is global.** There is no per-world enforcement level, so
"illegal but tolerated" cannot be expressed — a world is either bust-free or it
is not. When a world's fiction is "nobody polices this" (Forgotten Hollow,
Moonwood Mill), the mechanically correct setting is **legal**.

Getting legality wrong gets Sims arrested: `MISDEMEANOR` / `FELONY` /
`HARD_FELONY`, `PRISON_OG`, `LAW_FIRM_BEST|MED|BAD`,
`GET_OUT_OF_JAIL_FREECARD`. Treat it as gameplay, not flavour.

## World identity

Basemental names worlds after their **pack** (`CITYLIFE`, `PET_WORLD`,
`MULTIUNIT_WORLD`) and uses two schemes that disagree with each other — the
`LEG_*` trait is pack-named, the `Legalization` buff sometimes place-named. Use
`sulskill-worlds` for the translation; never map by eye. Ten worlds have no
legalisation flag at all, including Britechester, Granite Falls and Selvadorada.

## Maintenance

`py scripts/extract_bmd.py` rebuilds `reference/basemental.json` (trait ids +
menu tree) from the installed mod. Re-run after a Basemental update; trait ids
are stable but the world list grows with packs.
