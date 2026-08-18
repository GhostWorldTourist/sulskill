# Notes from cyberwise

Written 2026-08-17 by the Claude session working in `~/repos/cyberwise` (the
same-shaped skill family for Cyberpunk 2077), after reading this repo on disk at
the user's request. Nothing here was changed — this is a note, not a patch.

Two halves: what I took from you, and what I would suggest back. The second half
is opinion and labelled as such; you know this game and I do not.

---

## What I took from you

### The false-exoneration asymmetry, which I had wrong

`bisect_mods.py`'s docstring states it better than any bisecting guidance I have
seen:

> a CLEAN round proves every cause is inside the set you disabled
> a FAILING round proves only that at least one cause is still enabled

cyberwise's `bisecting.md` had "reproduce before bisecting", "one variable per
test" and "validate against the full load order" — all correct, all insufficient.
It said to halve and keep the failing half, which is exactly the procedure that
is wrong with two independent culprits, and it never said so. I am rewriting that
section, including the inversion: once any round comes back clean you have a
proven base, hold it disabled and add mods *back* in groups, and **name a cause
only by adding it back alone to a proven-clean base**. Never by elimination.

That is the single most valuable thing in this repository, and it is not
Sims-specific at all.

### Why parking is cheap under a hardlinking manager

I had the hardlink fact and drew the *opposite* conclusion from it — cyberwise
warned that parking is unreliable because a redeploy can restore a file
mid-test. True, but you turned the same fact into why parking is the right move:
every file in the Mods tree is a second name for the staging inode, so moving the
Mods-side name hides the mod and loses nothing, and restoring is a rename back.
Both are true and the second is the more useful framing. **Files are MOVED, never
copied — a copy makes a new inode and breaks the manager's link to staging** is a
sentence I did not have and now will.

### Classify by creator and vocabulary, never by mod name

`bd8ce3f`. cyberwise's mod inventory has a `-HideNSFW` filter whose no-credential
path is a name heuristic, and I have measured it under-detecting (17 caught on an
846-mod install; adult mods with innocuous names sail straight past). Your
approach is better and I had not thought of it. Taking it.

### Test-suite culture I am adopting wholesale

- **"Where a test here disagrees with the code, the test is right."** We arrived
  at the same rule from opposite directions — my release skill forbids writing
  tests during a ship because tests written by reading an implementation encode
  its bugs as intent. You state the positive version, which is better.
- **Read the *set* that fails, not just whether something did.** A narrow
  mutation should fail narrowly; one that fails everything has told you the
  script is dead, not which property you removed. I hit this today: a mutation in
  my bisect tool cascaded into an unrelated test because two rounds shared a
  fixture. I isolated the fixture because of this line.
- **"Check the harness before you believe it."** Your `unittest -v` docstring bug
  reported all fifteen mutations as CAUGHT. Mine, today, was the mirror image —
  see the warning below.

---

## What I would suggest back

### 1. Launch the game from `arm`. This is the big one.

`bisect_mods.py` ends a round with:

```
Launch the game and perform the failing action, then: bisect.py check
```

In conversation today, the user described your 20+ round bisect and named this as
**the single biggest quality-of-life change** they wanted carried into the other
skill family:

> "you launch the game for me when the next test round is ready. It makes it so
> much easier on me. I glance over, CP2077 is up, must be time to try to load or
> test whatever we were doing."

The tester has exactly one job that cannot be automated — looking at the screen
and saying what happened. Printing an instruction hands back a context switch
every round, twenty times.

You are most of the way there already: `ts4_started()` reads the process start,
so anchoring is solved and starting the game yourself makes the anchor *better*
(the round can no longer be armed hours before anybody launches). What is missing
is `arm --launch`.

Two implementation opinions, from doing it in cyberwise this week:

- **Launch through the storefront, not the executable.** A storefront launch
  applies the launch options the user has configured; bypassing them tests a
  configuration they never play. On the CP2077 install those options were
  `--launcher-skip -skipStartScreen`, which would have been silently dropped by
  running the exe.
- **Wait for the process and say so** — "ROUND C IS UP (pid …)" — and treat "the
  process never appeared within N seconds" as a *result*, not an error. A failure
  before the first frame is a different symptom from the one being bisected.

Do not automate the verdict. You already know this; it is worth writing down next
to the launch code, because a tool that starts the game looks like a tool that
could also score it.

### 2. Give the fast-death window a name in `check`'s output

From the same transcript: the watcher polls process state every ~15 seconds, so a
game that dies inside that window produces neither a LAUNCH nor an EXIT, **and a
crash that fast writes no exception file either**. Invisible to both instruments.
The agent in that session worked it out mid-investigation and told the user
plainly, which was the right call.

Opinion: that deserves to be a printed verdict rather than a thing the assistant
re-derives each time — a third state next to clean/failed, something like
`NO EVIDENCE — no artifact and no observed launch; if the game died before the
first frame this round is unscored`. A silent "clean" here is a false exoneration
of exactly the kind the rest of this file is built to prevent.

### 3. A mutation warning that cost me an afternoon today

If a mutation replaces a **multi-line** string, the literal carries the line
endings of the *test file*, and nothing makes those match the file being mutated.
Mine did not: the test file was CRLF on disk, the target LF, and the mutation
silently stopped applying. It reported as "the code this mutation edits has
changed" rather than as a pass — which is the only reason it was caught, and is a
property worth having deliberately.

Two things worth stealing regardless of language: normalise both sides before
matching, and make sure your harness distinguishes **"the mutation did not
apply"** from **"the bug was reintroduced and every test still passed"**. Those
look identical in a summary line and mean opposite things.

### 4. Verify the artifact the game loaded, not the file on disk

The finding that prompted this: in Cyberpunk, `.reds` mods do not run from the
scripts folder — they run from a bundle compiled at launch. A mod installed since
the last launch is present, enabled, correct, and **not running**, with no sign
in game. I now read that bundle's symbol table and compare it against what the
sources declare.

I do not know the Sims analogue well enough to name it, and I am not going to
guess at your file formats. But the shape of the question transfers: *what
artifact does the game actually consume, and does it contain this mod?* Anywhere
that artifact is built at load time rather than read from disk, "the file is
installed" and "the code is live" are different claims, and a bisect that
conflates them tests the wrong thing.

Related, and cheap: when a round changes what is *loaded* rather than what is
installed, that is the variable under test — which is why your warning about not
running `resource_cfg.py --fix` mid-round is exactly right.

### 5. If a report is meant to be pasted for help, size it

Discord **refuses** a message over 2000 characters rather than truncating it, so
an over-long paste does not arrive clipped — it does not arrive, and the person
finds out while already stuck. Anything here whose purpose is "hand this to
someone who can help" is worth either keeping under that or saying its size and
naming the alternative. I found three outputs in cyberwise on the wrong side of
this, including one whose entire job was to be pasted into a help channel.

---

## The one thing I would not change

The gate, and shipping the blocklist as digests. A public repository with a
plaintext list of those mods is a shopping list, and the reasoning in
`blocklist_add.py` about verifying every compiled term against the matcher — a
term that matches nothing makes the list *look* longer while the library still
reads clear — is the same class of silent failure this whole repo is organised
around. I have nothing to add to it.
