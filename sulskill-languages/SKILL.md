---
name: sulskill-languages
description: Read and edit frankk's Language Barriers settings for The Sims 4 - which language each world speaks natively, how second languages are assigned and inherited, and toddler language acquisition. Use when the user asks what languages a world speaks, wants to change a world's native or second languages, or wants to tune how bilingualism spreads.
---


> **Before running any script here:** these tools need a Python 3.9+
> interpreter and most Sims 4 players do not have one. Detect it by
> *running* it, not by checking PATH, and install it for the user if it
> is missing — see [SETUP.md](../sulskill/SETUP.md).

# Language Barriers config

frankk's Language Barriers gives Sims native and second languages and makes
conversation depend on whether two Sims share one. `lb_settings.cfg` is a plain
sectioned text file — a genuinely editable config, unlike Basemental (settings
are traits inside the save) or MCCC (rewritten from memory when the game saves).

```bash
py scripts/lb.py show                 # behavioural settings
py scripts/lb.py show --all           # including the regional table
py scripts/lb.py regions              # world -> native / second languages
py scripts/lb.py regions --filter Nordska
py scripts/lb.py set "Bilingual Chance=0.35"
py scripts/lb.py set "REGIONAL LANGUAGES.Newcrest=Simlish / Nordska, Tartosiano"
```


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

## Where the file must live

`fklb/data/configurations.pyc::get_config` resolves `lb_settings.cfg` relative to
**`__file__`** — the script's own directory. So the cfg must sit beside
`frankk_LanguageBarriers.ts4script`. Vortex deploying the mod folder flat into
`Mods\Vortex Mods\` satisfies that.

**It fails quietly.** A cfg stranded in a subfolder makes the mod log
`SETTINGS FILE MISSING` and run on built-in defaults — the game still works, so
the symptom is "my settings do nothing", not an error. The mod's own README also
says to delete the file if you are not customising, so an absent cfg is normal
rather than a fault.

## Format

Sections in `[BRACKETS]`, then `Key = Value` padded for alignment. The regional
section is shaped differently — each line is a **world**:

```
Sulani = Toki Sulani / Simlish, Komorebigo, Tomaru
         ^native       ^secondaries, comma-separated
```

Native before the slash, secondaries after.

## The ten languages

`Simlish, Windenburgish, Tartosiano, Nordska, Selvadoradian, Toki Sulani,
Komorebigo, Tomaru, Ravena, Sixami`

`set` rejects a language outside that list, because a typo in a regional line
does not error — it just leaves that world with no shared language, which shows
up much later as Sims who inexplicably cannot talk to each other. Pass `--force`
when an add-on legitimately introduces a new language.

## World naming

28 worlds are mapped. Compare world names **case-insensitively** against
`sulskill-worlds`: the mod writes `Strangerville` where EA writes `StrangerVille`,
and a case-sensitive check reports a world that is mapped as missing.

Genuinely unmapped: **Batuu, Granite Falls, Selvadorada** — vacation worlds with
no residents, so there is nobody to assign a native language to.

## Add-ons

Three optional packages ship separately and are pure toggles with no settings:
`LB_HideCommunicationNotifications`, `LB_HideLanguageContextNotifications`,
`LB_HideSixamiFromSimlingo`. Drop them anywhere.

## Not to be confused with

`Andirz_CustomElectives_LanguageBarriers.package` is a different mod entirely —
15 `UniversityCourseData` resources adding language electives to Discover
University. It has no configuration surface at all.
