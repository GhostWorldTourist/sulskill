# Tests

```
py tests/run.py             # from the repository root
py -m unittest discover -s tests -v
```

Standard library only, like everything else here. Nothing to install.

They build synthetic mod installs and synthetic packages in a temp directory,
so they do not read the machine's real Sims 4 library and mean the same thing
wherever they run.

## What these are for

Everything here covers a failure that is **quiet** — one where the wrong result
and the right result look identical from outside.

The gate fails in one direction that matters: silently, towards "clear". A term
that matches nothing, a package the reader could not open, a mod folder it never
looked in — none of them raise, and all of them look exactly like a clean
library. Scaling fails the same way: a compounded cooldown is a plausible
number, just a steadily more absurd one, and nothing about it looks wrong in a
diff. Most of the bugs below shipped, and were found by accident:

| test file | the failure it covers |
| --- | --- |
| `test_matching.py` | a compiled term that matches nothing. Five terms mixing letters and digits were dead this way — the tokeniser split them apart; a creator handle escaping by being spelled with a separator inside it; and the compiler keeping a term that no spelling of any name can reach |
| `test_review.py` | packages reading as empty and printing as clear: zlib magic sniffing that knew one of three level markers, no RefPack decoder, CASP names being UTF-16 |
| `test_discovery.py` | finding nothing on a manual install because the path assumed a mod manager's staging folder |
| `test_integrity.py` | a shim copied into a skill and then left behind when the shared one changed |
| `test_scaling.py` | `rescale` compounding because it read the current value instead of the mod default; a pin reported but never written; a preview quoting a stale schema instead of the file it is about to overwrite |
| `test_resource_cfg.py` | a package deeper than any `PackedFile` rule: installed, inventoried, never loaded. Also that deduplicating the file cannot change what loads — the repair is only safe to apply unasked if that holds |
| `test_variants.py` | two packages that overwrite each other reported as one mod's modules, and a stale build reported as current because the filename carried an older version than the archive it shipped in. Both read as a clean library |

### Written from the design, not from the code

`test_scaling.py` asserts the claims made in `sulskill-kuttoe/SKILL.md` and in
`_scaling_about` — derived scale, recompute from `base`, pins beat derivation,
things that repeat forever are left alone. That distinction is the point: tests
written by reading an implementation encode its bugs as intent and then defend
them. **Where a test here disagrees with the code, the test is right.**

Each group was checked by mutation — break the property deliberately, confirm
that group fails and the others do not. Fourteen mutations for the groups above,
fourteen caught; twenty-three more for `test_variants.py`, all caught; five for
`CompileTimeReachability`, all caught. If you add a test, do the same; a test
that has never failed has not been shown to test anything.

The two escapes in that second round are the reason it is worth doing. One
mutation changed which name `shared_stem` cut against and nothing failed — not a
missing test, but a parameter that had become provably dead when the end of a
string started counting as a token boundary, and it was deleted. The other
reordered `version_of` so the filename beat the source archive, and nothing
failed because no fixture had the two *disagree*; building that case found a
real bug sitting behind it, where a stale filename version split one build into
two flavours and quietly stopped anything from ever being marked superseded.
A mutation that escapes is telling you something either way.

`CompileTimeReachability` made the point a third time. Its "verified against the
whole batch rather than alone" mutation escaped, and the fault was in the test:
its two terms did not actually overlap, so the dead one failed its probes under
either scheme and the test could not tell them apart. It asserted the right
property and proved nothing. Rewriting the pair so the dead token's probe name
is caught by the live substring made the mutation fail as intended. Worth
noticing that the escape was caused by the fixture, not the assertion — the test
had read as obviously correct right up until something tried to break it.

Written-from-the-design earns its keep: `test_matching.py` asserted that
`SomeMod by Handle_Name` is the same authorship claim as `SomeMod by
HandleName`, and the gate disagreed — its `by` branch read only the first
segment, so a handle escaped by being spelled with an underscore in it. The
test was right and `_creator_tags` was fixed.

## Terms in tests

**No test may contain a real blocklist term.** The list ships as digests
because this repository is public and a readable list is a search index for
exactly the material it refuses. A test naming the terms would undo that.

Where a test needs terms it invents them with the same *shape* — a handle
mixing letters and digits, a handle that is also an ordinary English word —
and compiles them through `blocklist_add` into a temporary list. That also
tests the compiler, which a hand-written digest would not.

## Reachability is now checked where it can be

This used to be listed here as a known gap: nothing proved the terms on the
**shipped** list were reachable, only that the matcher handled each shape
correctly. It cannot be proved from the file, because a digest cannot be
inverted — by the time the list ships, the names are gone.

Compile time is the one moment the term and its digest exist together, so that
is where the question is now asked. `blocklist_add.verify` puts every compiled
term back through `gate.matches` under the spellings a library actually uses —
as written, run together, bracketed, attributed, with a Vortex suffix — against
a list holding **that term alone**. A term no spelling reaches is refused and
left out; one that matches but not the way it was written is kept and reported
as `WEAK`, since it is still doing work.

Verifying each term alone rather than against the whole batch is the part worth
keeping: two terms that overlap will cover for each other, and the dead one
looks reachable on the strength of the live one's hit.

What is still not provable: terms compiled **before** this existed. Retiring
that means recompiling from the source terms file, which is the one thing this
repository deliberately does not keep.

## Known gap

`caselog/` sits untracked inside the checkout and has a stray `SKILL.md.new`
beside it. It is not wired into anything and wants either finishing or moving
out of the working tree.
