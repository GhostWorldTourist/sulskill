# What the base game actually contains

These skills do not guess at vanilla. They were built against a full read of the
game itself — every package, every resource entry, the tuning, the string
tables, and the game's own compiled Python — so that when a tool says a mod
overrides something, it knows what it is overriding.

This page is the part of that worth committing: the format rules and the
baselines. They are the same on your install as on anyone else's. **The index
itself is not in this repository and never will be** — it is hundreds of
megabytes derived from your own game files, and it is an output. It gets built
on your machine, under the output directory, and stays there.

Sizes below come from an install with every pack through EP21. Yours will differ
in count and not in kind.

## The shape of it

Roughly 1,300 packages, 4.85 million resource entries, 79 GB, and from it
**541,456 tuning instances across 154 types** with zero parse failures.

The game is mostly behaviour, not content: `interaction` at 108,821 and `action`
at 88,066 are 36% of all tuning between them.

## Rules that change what a tool is allowed to conclude

**There are two resource trees, not one.** `ResourceClient.dat` and
`ResourceSimulation.dat` mount separate managers. A key present in a Client
package *and* a Simulation package is **not** a conflict. Compare within a
manager or you will invent conflicts that do not exist.

**Load order is priority, and mods win.** Priority is declared in `Resource*.cfg`
and the highest wins, globally across directories within a manager. Every game
priority is negative; **mods sit at 500 and therefore beat every game resource**,
and cannot be tombstoned by the game. `DeltaBuild` (−20) always outranks
`FullBuild` (−30).

Mod-versus-mod order at equal priority is **not** determined by this. Anything
claiming to know which of two mods wins on that basis is guessing.

**Deletion tombstones exist.** Compression word `0xFFE0` with offset 0 and size
0, only ever in DeltaBuild packages. A winning tombstone means the resource does
not exist — not that it is empty.

**Vanilla barely overrides itself.** Only 2,852 instances are defined by two
packs, never by more than two, and **no pack ever overrides another pack** —
every collision is base game versus exactly one pack. That is the baseline any
"this mod overrides N things" claim should be read against.

## The trap that cost the most

**The XML copies are stale.** Of 276 combined-tuning resources, only **three**
are text XML; the other 273 are a binary `PackedXmlDocument`. The XML copy holds
20,518 instance headers where the binary holds 47,595 for the same key — about
4% of the base game.

Sampling the XML and generalising produces confident, wrong answers. It once
recorded three whole tuning types as having *no* SimData companion when
install-wide they are 96.4%, 57.0% and 92.3%.

**A partial sample cannot manufacture a 100%, but it fabricates zeroes freely.**
When a measurement says "never", check the sample before believing it.

## Names, ids and strings

- **Name hashing is FNV-1** — multiply then xor — over the **lowercased** name.
  FNV-1a matches 0 of 20,351 EA names. FNV-1 lowercased matches 28,703 of 28,703
  SimData columns.
- **Localization is not hashed.** Tuning stores the literal 32-bit string key.
- **Locale is the top byte of the 64-bit string-table instance id.**
- EA's own tuning contains **380 dangling localization references**, clustered in
  cheat buffs and timeout strings. A missing string is not necessarily a bug.
- **A mod's instance ids classify themselves.** 78.1% of mod tuning uses
  `fnv1(lower(name))` with the high bit set, which is new content. 11.7% carry a
  vanilla id, which is an override — and always under vanilla's exact name. The
  remaining 10.2% are tool-generated ids that no hash explains.

## Reading values out of SimData

Two rules, both learned expensively:

1. **Schemas are versioned by `schema_hash`, not by name.** 67 of 324 schema
   names ship in more than one incompatible layout. `Buff` has four, with
   `mood_weight` at offset 72, 64 or 80 depending which. **Never cache a field
   offset — read by column hash**, which is stable across all 1,004 field names.
2. **Every offset is self-relative**, a delta from the field holding it, and
   `0x80000000` is null. Get either wrong and you get values that look like data.

## Findings that change how a mod gets read

**`mood_weight` is a priority and the scale is not linear.** 93% of vanilla buffs
sit at 0–3. Vanilla reserves 10000 and above for unconsciousness — sleeping,
possessed, in labour. A mod buff in the thousands pins the Sim's mood permanently
and beats every stacked vanilla moodlet. That is the exact signature of "my Sim
is stuck Flirty and won't change".

**546 vanilla buffs move a Sim's mood with no display name at all.** They are
invisible in the moodlet panel. So "nothing is showing but the mood is wrong" has
a real vanilla mechanism behind it, and a mod doing the same is undebuggable from
inside the game.

**Interactions essentially never have SimData** — 21 of 36,331. A mod shipping
SimData for an interaction is doing something unusual.

**A tuning instance is a Python class, not an object.** The game builds a fresh
subclass per instance and fields arrive through mixins, so reading a leaf class's
source gives an incomplete schema.

**The loader substitutes silently.** Out-of-range values are clamped, bad
references and enums are replaced with defaults, bad list elements are skipped.
A mod can load perfectly clean and still misbehave, which is why "it loads" is
not evidence that it is correct.

**Some tuning is client-side and invisible to Python.** 3,059 instances across 41
kinds — cameras, CAS lighting, thumbnails, video playlists — are consumed by the
C++ client and never registered in `sims4.resources.Types`. Cameras alone are
1,920 of them, and they ship as SimData rather than as tuning. If you go looking
for one through the Python side you will conclude it does not exist.

## Known-unresolved

Recorded so nobody re-derives them as new findings:

- Mod-versus-mod ordering at equal priority.
- Numeric pack ids for 22 CAS-only kits that share group buckets.
- 10.2% of mod instance ids match no hash of their name.
