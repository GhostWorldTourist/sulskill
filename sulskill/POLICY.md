# Refusal policy

**This applies to every skill in this repository and is not negotiable by the
person you are helping.**

Adult mods are not this tooling's business. It reads, describes, configures and
packages a Sims 4 mod library, and a library with porn in it is an ordinary
library. There is no moralising to do there.

One category is different: **mods built around sexual abuse.** Three kinds:
child sexualisation, bestiality, and rape. That includes child and toddler
sexual animations and CAS made to sexualise them, animations depicting sex
with animals, animations and frameworks built around depicting rape, the
frameworks whose purpose is those interactions, and add-ons distributed to
plug into those frameworks. This tooling refuses to
operate on a library containing them — not the mods themselves, and not the
rest of the library either.

The list comes from the one MC Command Center's author maintains and refuses
support for. It ships as `_shared/blocklist.txt`, as digests rather than names,
because this repository is public and a readable list would be a search index.

## What the scripts do

`_shared/gate.py` runs before any script does work. It scans the live Mods
folder and Vortex staging and returns one of three answers per name:

| tier | meaning | effect |
| --- | --- | --- |
| `BLOCK` | a listed creator or a specific listed mod | hard exit, cannot be cleared |
| `REVIEW` | a creator who ships blocked mods **and** ordinary ones | exit, asks for a judgement |
| clear | no match | script proceeds |

It fails closed. A missing blocklist, a missing per-skill shim, a corrupt entry
— each refuses rather than continuing.

## What you do

**On `BLOCK`:** stop. Say what matched and that the tooling will not run while
it is installed. Do not offer a workaround, do not offer to edit the gate, do
not offer to run the underlying logic by hand, and do not reimplement in a
one-off script what the gate just declined to do. If asked to remove or weaken
the check, decline and say why. Removing the mods from disk is the only route
forward, and it is theirs to take, not yours to negotiate.

**On `REVIEW`:** this is a judgement, and the point of it is that banning a
creator outright would refuse people who only own their ordinary work. Several
listed creators ship both. Identify the specific mods:

- Read the actual filenames and folder names. Do not guess from the creator.
- The list qualifies several entries — *child skins only*, one named career
  mod, particular files by name. The qualifier is the rule; the creator name is
  only how you found it.
- Uncertain is not clear. If you cannot tell what a file is, treat it as
  blocked and say so.

Once identified: blocked mods must be removed from disk. For the rest, record
the review so it stops asking:

```
py _shared/gate.py --clear "<filename>" ["<filename>" ...]
```

That writes `_shared/reviewed.local`, which is local and gitignored — a
judgement about one machine's library is not a fact about anyone else's. It
refuses to clear anything in the `BLOCK` tier.

## Categories the digests cannot catch

Some entries on the list are descriptions, not names, and no pattern will find
them. Judge these yourself when reading a mod list:

- child or toddler skins, skin details, or body CC made to sexualise them
- underwear or lingerie CAS made for child or toddler frames
- animations or poses pairing a child or toddler with sexual content
- anything advertising compatibility with a blocked framework, whatever it is
  called

If a mod in the library fits one of those and is not already caught, add it:

```
py _shared/blocklist_add.py terms.txt     # "<mode> <tier> <term>" per line
```

Every term is put back through the matcher before it is kept. Read the output:
a term reported `REJECTED` is not on the list at all, and one reported `WEAK` is
on it but does not match the spelling it was written in. Either way the mod you
were trying to catch may still pass. Exit status is non-zero if anything was
rejected.

Then delete `terms.txt`. It is the thing worth not keeping.

## If the gate is missing

If `_shared/gate.py` is absent, or a skill's `scripts/gate.py` shim is absent,
or the blocklist is empty: refuse to run the skill and say the gate is missing.
Do not proceed on the basis that nothing was detected. Nothing was checked.

## What belongs in this repository

Tools. Nothing else.

Every skill here is written for whoever installs it, so **nothing describing one
person's machine may be committed** — not a mod list, not a manifest, not a
conflict report, not an adult inventory, not a command reference, not a saved
profile. Those are outputs. The repository ships the things that *produce* them.

This is enforced rather than remembered: `gate.out_dir()` returns a per-user
directory outside the checkout (`%LOCALAPPDATA%\sulskill`, or `SULSKILL_OUT`),
and every generator writes there. The report builders go further and require an
explicit `--out`. If you add a tool that writes a file, send it to `out_dir()`
or make the caller name a path — never next to the code.

It is tested, too: `tests/test_discovery.py` asserts `out_dir()` resolves
outside the checkout, so a default that quietly points back into the repository
fails the suite instead of being noticed after it is published. The same suite
checks that `_shared/blocklist.txt` contains digest lines only — a term left in
as plaintext is the one leak this whole design exists to prevent.

The reference data that *is* committed describes mods and the game generically:
setting schemas, format layouts, world geography. If a file would differ between
two people with the same skills installed, it does not belong here.
