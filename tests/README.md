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
| `test_snapshot.py` | a baseline written when it should not have been, which swallows the change: the next run reports +0 / -0 / ~0, and so does a library nobody touched. Also `index.pkl`'s size-less records marking the whole library as changed, and a traceback on a missing baseline taking the script-validity check with it |
| `test_moodprint.py` | naming the wrong mod as the winner of a contested buff — a case-sensitive sort reverses the outcome for every mixed-case pair, and the report is confident either way. Also an absent `mood_weight` read as 0, and a mood id whose value is followed by an inline XML comment |
| `test_basegame_readers.py` | format readers that return *something* rather than failing: a codec the reader does not know handing back still-compressed bytes, a locale read from the wrong byte of the instance id, FNV-1 silently becoming FNV-1a (they differ only in operation order), a SimData row-data offset that resolves to nothing, and a builder that writes an empty index when it cannot find the game — which makes every later query answer "not found", and read as fact |
| `test_basegame.py` | a lookup that returns nothing for a reason unrelated to the data. Querying instance 14965 against the raw JSONL found zero rows because the field is `id` not `instance`, and because ids are stored as strings so the ones above 2^63 survive — a wrong field name and a wrong value type both look exactly like "not present", and people act on "not present". Also the writer and reader disagreeing about where the database lives, which nothing would catch until somebody built an index and could not query it |
| `test_evidence.py` | a diagnostic file that exists and is never read. One investigation ran twenty-five bisect rounds while `mc_lastexception.html` sat in the Mods folder naming the culprit twenty-one times — missed because the reader worked from a remembered list of artifacts, so a file not on the list did not exist. The assertions that matter are therefore about the files the tool does *not* recognise; a longer allowlist fixes one investigation, reporting the unknown fixes the next one |
| `test_bisect_mods.py` | a false exoneration. Clearing the mods you just disabled because the round still failed is sound only with exactly one culprit; with two, every half fails, each round clears innocent and guilty alike, and the search narrows into a region that never held the answer. Nothing errors and the rounds keep halving. Also an exception file from a previous session scored as this round's result, and one read mid-write scored as clean |
| `test_simdata.py` | a name hash computed the wrong way, which returns a plausible number and writes a resource the game never finds under the name it claims — `fnv64` shipped as FNV-1a over the original casing, wrong twice, with zero callers and a docstring inviting one. Also the format's null pointer (`0x80000000`, not `-1`) read as an ordinary offset, resolving ~2 GB below the buffer: table names decoded as fragments and schema pointers landed outside the resource, and nothing raised |
| `test_classify_adult.py` | a mod that lands in no bucket: the counts still print, the plan still claims to cover everything, and the mod is never named — so it stays enabled in a profile built to exclude it, and the first sign is somebody seeing it in the game. Also a derived search term that selects something on the *keep* list, which tells you to Ctrl+A a block with a keeper in it and looks no different when it does |

### Written from the design, not from the code

`test_scaling.py` asserts the claims made in `sulskill-kuttoe/SKILL.md` and in
`_scaling_about` — derived scale, recompute from `base`, pins beat derivation,
things that repeat forever are left alone. That distinction is the point: tests
written by reading an implementation encode its bugs as intent and then defend
them. **Where a test here disagrees with the code, the test is right.**

Each group was checked by mutation — break the property deliberately, confirm
that group fails and the others do not. Fourteen mutations for the groups above,
fourteen caught; twenty-three more for `test_variants.py`, all caught; five for
`CompileTimeReachability`, all caught; fifteen for `test_moodprint.py`, one
escaping on the first pass; fifteen for `test_snapshot.py`, all caught; fourteen
for `test_classify_adult.py`, two escaping on the first pass; eighteen for
`test_bisect_mods.py`, one escaping; eight for `test_simdata.py`, all
caught; seven for `test_evidence.py`, one escaping; nine for `test_basegame.py`,
three escaping on the first pass; thirteen for `test_basegame_readers.py`, two
escaping because the assertions were vacuous. If you add a test,
do the same; a test that has never failed has not been shown to test anything.

Read the *set* that fails, not just whether something did. `test_snapshot.py`
passed on its first run, which proves nothing on its own — what makes it worth
keeping is that the narrow mutations fail narrowly: case-sensitive extension
matching fails one test, the depth limit off by one fails one test, losing the
`.py` fallback fails one test. Broad failures are legitimate for broad
properties — removing the empty-baseline fallback takes out nineteen tests, and
should — but a break that fails *everything* has told you the script is dead,
not which property you removed.

**Check the harness before you believe it.** The runner for `test_snapshot.py`
originally read the pass list out of `unittest -v` and subtracted it from the
tests it saw. With `-v`, unittest prints `... ok` on a test's **docstring** line,
not its name line, so every documented test read as failed and all fifteen
mutations reported CAUGHT — including, later, mutations in files those tests
never touch, which is what gave it away. Parse the failure list instead,
`^(?:FAIL|ERROR): (test_\w+)`, and take non-verbose output. Both harness bugs
found so far fail in the friendly direction: this one, and a `\r\n` comparison
that made every mutation look caught on Windows. A mutation harness that reports
all-caught on its first run is the thing to distrust, not the thing to file.

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

`test_moodprint.py` repeated the fixture lesson exactly. Its "sorted by
basename instead of by path" mutation escaped, and again the assertion was
right: the two packages in the fixture sorted the same way under both schemes,
so no outcome could distinguish them. Choosing a pair where the schemes
*disagree* — `mmm.package` at the root against `Sub/aaa.package` — made it fail
as intended.

`test_classify_adult.py` made it a fourth time, on the property that matters
most in that file — the check that no derived search term also selects a mod on
the keep list. Removing the check changed nothing, because the fixture's two
excluded mods shared a long prefix and the tie-break towards longer terms was
already avoiding the collision by accident. The colliding term has to be the
*widest* one, or nothing forces the choice.

`test_bisect.py` made it a fifth time, and prospectively rather than in
hindsight. Eighteen mutations, one escape on the first pass: "a halving failure
names a culprit" changed nothing, because the fixture disabled the entire
candidate set, leaving no enabled candidate for a wrong implementation to name.
Re-pointing it at a round that leaves some candidates enabled made it fail as
intended. A second test in that file could not fail at all until it was
rewritten — it asserted the holding directory sits outside `Mods`, but the
fixture set that directory itself, so it would have passed with any default.

Six of the seven escapes recorded here were fixtures that could not tell right
from wrong, which is worth knowing about how these read. The assertion is
rarely the problem. What fails is the case it is pointed at.

The sixth is its own lesson: `apply_plan.py`'s term pool was built from a set,
so two terms tying on both coverage and length were separated by string hashing,
and the mutation that broke widest-first selection escaped roughly one run in
three. A test that passes at random reads exactly like a test that passes.
**Run a mutation more than once** before recording it as caught, and if it is
unstable, fix the nondeterminism in the subject rather than the fixture — the
same hash order was also making the shipped plan differ between runs.

Its two genuine failures on first run were both real. One was my expectation of
load order, and the tool was right. The other was a bug: mood names were looked
for only in packages that also held buffs, so a mod shipping its moods
separately printed a bare id — the one thing in the report a reader can do
nothing with. Fixing that introduced a second, caught by the same test, where
the index was iterated twice and the second pass got an exhausted generator.

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
