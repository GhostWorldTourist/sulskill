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

The gate fails in one direction that matters: **silently, towards "clear"**.
A term that matches nothing, a package the reader could not open, a mod folder
it never looked in — none of them raise, and all of them look exactly like a
clean library. Every bug this suite covers shipped and was found by accident:

| test file | the failure it covers |
| --- | --- |
| `test_matching.py` | a compiled term that matches nothing. Five terms mixing letters and digits were dead this way — the tokeniser split them apart |
| `test_review.py` | packages reading as empty and printing as clear: zlib magic sniffing that knew one of three level markers, no RefPack decoder, CASP names being UTF-16 |
| `test_discovery.py` | finding nothing on a manual install because the path assumed a mod manager's staging folder |
| `test_integrity.py` | a shim copied into a skill and then left behind when the shared one changed |

## Terms in tests

**No test may contain a real blocklist term.** The list ships as digests
because this repository is public and a readable list is a search index for
exactly the material it refuses. A test naming the terms would undo that.

Where a test needs terms it invents them with the same *shape* — a handle
mixing letters and digits, a handle that is also an ordinary English word —
and compiles them through `blocklist_add` into a temporary list. That also
tests the compiler, which a hand-written digest would not.

## Known gap

Nothing here proves the **shipped** list's terms are reachable, only that the
matcher handles each shape correctly. Reachability cannot be tested from the
digests, because a digest cannot be inverted. Closing it properly means having
`blocklist_add` verify each term round-trips at compile time, and refuse the
ones that do not.
