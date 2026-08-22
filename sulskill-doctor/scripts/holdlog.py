"""Move mod files out of the way, and be able to put every one of them back.

This is the HOW. What to move is a judgement - a bisection strategy, a conflict
hypothesis, someone's hunch - and it belongs to the caller. Once something has
decided, the moving itself must be boring: no heuristics, no cleverness, no
case where the answer depends on which order things happened in.

The failure this exists to prevent
----------------------------------
The predecessor kept the list of what was moved in a single JSON file outside
the Mods folder, and read that file to decide what to restore. Its loader
swallowed every read error and returned an empty state, so a truncated write, a
cleared %LOCALAPPDATA%, or a changed SULSKILL_OUT all produced the same result:
`restore` printing "nothing is out" while the files sat in the holding
directory. On a Vortex install that is a shrug - redeploy and the tree is back.
On a manual install those files were the only copy, and the tool had just said
everything was fine.

So the design rule here is: **the filesystem is the truth, and the journal is
the map.** The holding directory mirrors the layout of Mods, which means the
held files describe their own way home even with no journal at all. The journal
adds what the layout cannot carry - which mod a file belonged to, which Mods
folder it came from, and when - and it is append-only, so a torn write costs
one line rather than the whole record.

Guarantees
----------
1. Files are MOVED, never copied. A copy makes a new inode and breaks a
   hardlink-deploying manager's link to staging.
2. Nothing is ever overwritten and nothing is ever deleted. Every collision is
   refused and reported. A tool whose undo can destroy something is not an undo.
3. Same-volume is checked BEFORE the first move, not discovered during it.
4. `held()` reconciles the journal against what is actually on disk and reports
   five states, none of which is a guess. A file the journal claims but which
   is on neither side is reported as MISSING, loudly, rather than dropped.
5. Every file in the holding directory is restorable whether or not the journal
   mentions it.

The journal format, which other tools may read
----------------------------------------------
`journal.jsonl` in the holding directory. One JSON object per line, appended and
fsynced, never rewritten. Unparseable lines are skipped and counted, never
treated as absent.

    {"v":1,"op":"session","ts":...,"tool":"bisect_mods","root":"...",
     "hold":"...","install":"manual","second_copy":false}
    {"v":1,"op":"hold","ts":...,"mod":"alpha","rel":"a.package","phase":"intent"}
    {"v":1,"op":"hold","ts":...,"rel":"a.package","phase":"done"}
    {"v":1,"op":"unhold","ts":...,"rel":"a.package","phase":"intent"}
    {"v":1,"op":"unhold","ts":...,"rel":"a.package","phase":"done"}

`intent` is written before the rename and `done` after it. Since a same-volume
rename is atomic, an intent with no matching done is not corruption - it is
answered by looking at which side the file is on, which is exactly what
`held()` does.

Standalone recovery, for when the calling tool is gone::

    py holdlog.py status
    py holdlog.py restore
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import json
import os
import sys
import time

JOURNAL = 'journal.jsonl'
FILES = 'files'
README = 'README-DO-NOT-DELETE.txt'

README_TEXT = """\
sulskill holding directory
==========================

The files under `{files}/` were MOVED out of your Mods folder by a sulskill
tool, so that the game could be started without them. They were not copied and
they were not modified.

DO NOT DELETE THIS FOLDER. On a manual install these are the only copies of
those mods.

To put everything back, run:

    py holdlog.py restore

If you no longer have the tool, you can do it by hand: everything under
`{files}/` mirrors its original path inside your Mods folder, so moving the
contents of `{files}/` back into

    {root}

reproduces the original layout exactly. `journal.jsonl` in this folder records
which mod each file belonged to and when it was moved.
"""


def _now():
    return time.time()


class Hold:
    """One holding directory, and the Mods folder its contents came from."""

    def __init__(self, hold_dir, root=None):
        self.dir = os.path.abspath(hold_dir)
        self.files = os.path.join(self.dir, FILES)
        self.journal = os.path.join(self.dir, JOURNAL)
        self.readme = os.path.join(self.dir, README)
        # The root recorded in the journal wins over the one passed in: the
        # files came from wherever they came from, and a caller guessing a
        # default must not redirect somebody's mods into a different folder.
        self._root_arg = os.path.abspath(root) if root else None
        # Memoised because `root` is consulted once per file moved, and reading
        # the whole journal each time makes a round that disables three hundred
        # files quadratic in a file that is growing as it goes.
        self._root_cache = None

    # ---- paths ---------------------------------------------------------

    def src(self, rel):
        return os.path.join(self.root, rel)

    def dst(self, rel):
        return os.path.join(self.files, rel)

    def legacy_dst(self, rel):
        """Where a predecessor version put this file: straight into the
        holding directory, with no `files/` level.

        Kept because somebody will upgrade mid-round, and a version that could
        not see the previous version's held files would greet them with
        "nothing is out" - which is the exact failure this module was written
        to end. Read from both layouts, write only to the new one.
        """
        return os.path.join(self.dir, rel)

    def locate(self, rel):
        """Where this held file actually is, or None. New layout wins."""
        for p in (self.dst(rel), self.legacy_dst(rel)):
            if os.path.exists(p):
                return p
        return None

    @property
    def root(self):
        if self._root_cache is None:
            self._root_cache = self.journal_root() or self._root_arg
        return self._root_cache

    def journal_root(self, records=None):
        """The Mods folder recorded by the most recent session, or None."""
        root = None
        for rec in (self.records() if records is None else records):
            if rec.get('op') == 'session' and rec.get('root'):
                root = rec['root']
        return root

    # ---- journal -------------------------------------------------------

    def records(self):
        """Every parseable journal line, in order. Unparseable ones are
        skipped here and counted by `damage()` - never silently dropped."""
        out = []
        try:
            with open(self.journal, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict):
                        out.append(rec)
        except OSError:
            return []
        return out

    def damage(self):
        """How many journal lines could not be parsed."""
        bad = 0
        try:
            with open(self.journal, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except ValueError:
                        bad += 1
        except OSError:
            return 0
        return bad

    def _append(self, rec):
        """Append one record. Flushed and fsynced, because the whole point is
        that it survives whatever happens to the process after this line.

        Two fsynced records per file costs about four seconds over a 1200-file
        round, and that is the right trade: the delay is paid once per arming,
        while the thing it buys - a journal that is still there after a crash,
        a reset, or a pulled plug - is the difference between a mod name and a
        mod. A lost tail line costs only the name anyway, since the file's own
        location is the record.
        """
        rec.setdefault('v', 1)
        rec.setdefault('ts', _now())
        os.makedirs(self.dir, exist_ok=True)
        with open(self.journal, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(rec, sort_keys=True) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def open_session(self, tool, info=None):
        """Record which Mods folder this holding directory serves, and what
        kind of install it is. Written once per arming, before any move."""
        root = self.root or ''
        rec = {'op': 'session', 'tool': tool, 'root': root, 'hold': self.dir}
        if info:
            rec['install'] = info.get('kind')
            rec['second_copy'] = bool(info.get('second_copy'))
        self._append(rec)
        self._root_cache = root or None      # this record is now the answer
        self.write_readme()

    def write_readme(self):
        """Leave the instructions with the files, not only in the tool.

        "Delete your The Sims 4 folder and let it regenerate" is the standard
        support answer for this game, and this directory is a sibling of Mods
        inside that folder - it has to be, to stay on one volume and out of
        Resource.cfg's reach. Someone following that advice mid-round should at
        least find a file telling them what they are about to throw away.
        """
        os.makedirs(self.dir, exist_ok=True)
        try:
            with open(self.readme, 'w', encoding='utf-8', newline='\n') as f:
                f.write(README_TEXT.format(files=FILES,
                                           root=self.root or '<your Mods folder>'))
        except OSError:
            pass

    # ---- reconciliation ------------------------------------------------

    def walk(self):
        """Every file actually sitting in the holding directory, as rel paths.

        This is the half that works with no journal: the holding directory
        mirrors Mods, so its own layout is a restore plan.

        Both layouts are read - `files/` as written by this version, and the
        bare holding directory as written by its predecessor - because the
        alternative is telling somebody who upgraded mid-round that nothing is
        out while their mods sit in the other one.
        """
        out = set()
        for dirpath, _dirs, files in os.walk(self.files):
            for f in files:
                full = os.path.join(dirpath, f)
                out.add(os.path.relpath(full, self.files))
        for dirpath, dirs, files in os.walk(self.dir):
            if dirpath == self.dir:
                # Everything the holding directory owns, rather than holds.
                dirs[:] = [d for d in dirs if d != FILES]
                files = [f for f in files if f not in (JOURNAL, README)]
            for f in files:
                full = os.path.join(dirpath, f)
                out.add(os.path.relpath(full, self.dir))
        return sorted(out)

    def labels(self, records=None):
        """rel -> mod name, from the journal. Absent is fine, not an error."""
        out = {}
        for rec in (self.records() if records is None else records):
            if rec.get('op') == 'hold' and rec.get('rel'):
                if rec.get('mod'):
                    out[rec['rel']] = rec['mod']
        return out

    def held(self):
        """Reconcile the journal against the disk. Nothing here is a guess.

        Every rel the journal mentions, plus every file actually present, is
        placed in exactly one bucket by asking which side it is on:

            in hold, not in Mods   out       - restorable, the normal state
            in hold, and in Mods   conflict  - both sides exist, do not touch
            not in hold, in Mods   restored  - already back
            in neither             missing   - say so, loudly

        `unjournalled` is the subset of `out` the journal never recorded.
        Those still restore; the layout is enough.
        """
        root = self.root
        on_disk = set(self.walk())
        records = self.records()             # read once, not once per question
        claimed = {rec['rel'] for rec in records
                   if rec.get('op') == 'hold' and rec.get('rel')}
        labels = self.labels(records)

        out, conflict, restored, missing = [], [], [], []
        for rel in sorted(on_disk | claimed):
            in_hold = rel in on_disk
            in_root = bool(root) and os.path.exists(os.path.join(root, rel))
            item = {'rel': rel, 'mod': labels.get(rel, '(unrecorded)')}
            if in_hold and in_root:
                conflict.append(item)
            elif in_hold:
                out.append(item)
            elif in_root:
                restored.append(item)
            else:
                missing.append(item)
        return {
            'root': root,
            'hold': self.dir,
            'out': out,
            'conflict': conflict,
            'restored': restored,
            'missing': missing,
            'unjournalled': [i for i in out if i['rel'] not in claimed],
            'damaged_lines': self.damage(),
        }

    # ---- preflight -----------------------------------------------------

    def preflight(self):
        """Everything that must be true before the first move. -> (ok, [why])

        Checked up front, together, because a move that fails halfway through a
        list leaves a library in a state nobody chose. The volume check is the
        one that matters: os.rename cannot cross volumes, and the copy-then-
        delete that would "work" instead duplicates the inode - which breaks a
        manager's hardlink, and on a manual install means the only copy of a
        mod spends the operation existing twice and then not at all.
        """
        why = []
        if not self.root:
            why.append('no Mods folder is known for this holding directory')
            return False, why
        if not os.path.isdir(self.root):
            why.append('the Mods folder does not exist: %s' % self.root)
        same = None
        try:
            os.makedirs(self.files, exist_ok=True)
            import install as _install
            same = _install.same_volume(self.root, self.files)
        except OSError as exc:
            why.append('cannot create the holding directory %s: %s'
                       % (self.files, exc))
        if same is False:
            why.append(
                'the holding directory is on a different volume from Mods.\n'
                '  Mods: %s\n  hold: %s\n'
                '  Files can only be moved within one volume. Moving across '
                'would copy\n'
                '  and then delete, which duplicates the file instead of '
                'relocating it -\n'
                '  it breaks a mod manager\'s hardlink to staging, and on a '
                'manual install\n'
                '  it puts the only copy of a mod through a delete. Set '
                'SULSKILL_BISECT_HOLD\n'
                '  to a path on the same volume as Mods.'
                % (self.root, self.files))
        elif same is None:
            why.append('cannot tell whether %s and %s are on the same volume; '
                       'refusing rather than finding out during the move'
                       % (self.root, self.files))
        return (not why), why

    # ---- the two operations --------------------------------------------

    def hold_file(self, mod, rel):
        """Move root/rel into the holding directory. -> (ok, error or None)"""
        src, dst = self.src(rel), self.dst(rel)
        if not os.path.exists(src):
            return False, 'not deployed'
        if self.locate(rel):
            # Never clear the way by deleting. Something is already held under
            # this name, and on a manual install it is the only copy of it.
            return False, ('already held from an earlier round - restore '
                           'before arming again')
        self._append({'op': 'hold', 'mod': mod, 'rel': rel, 'phase': 'intent'})
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
        except OSError as exc:
            return False, str(exc)
        self._append({'op': 'hold', 'rel': rel, 'phase': 'done'})
        return True, None

    def unhold_file(self, rel):
        """Move it back. -> (ok, error or None). Never overwrites."""
        src, dst = self.locate(rel), self.src(rel)
        if src is None:
            return False, 'missing from the holding directory'
        if os.path.exists(dst):
            return False, ('a file already exists at that path in Mods - '
                           'not overwriting it')
        self._append({'op': 'unhold', 'rel': rel, 'phase': 'intent'})
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
        except OSError as exc:
            return False, str(exc)
        self._append({'op': 'unhold', 'rel': rel, 'phase': 'done'})
        return True, None

    def restore_all(self):
        """Put back everything that is out. -> (restored, [(rel, why)])

        Driven by `held()`, so it restores files the journal never recorded and
        refuses the ones whose destination is occupied. Empty directories are
        tidied afterwards; the journal and the README are left alone.
        """
        state = self.held()
        done, failed = 0, []
        for item in state['out']:
            ok, err = self.unhold_file(item['rel'])
            if ok:
                done += 1
            else:
                failed.append((item['rel'], err))
        for item in state['conflict']:
            failed.append((item['rel'],
                           'present in both Mods and the holding directory - '
                           'left alone; compare them and delete one by hand'))
        self._prune()
        return done, failed

    def _prune(self):
        """Remove directories left empty by a restore. Never removes a file.

        os.rmdir refuses a non-empty directory, which is the safety here: this
        cannot delete anything that still holds something. Deepest first, so a
        nest of empty folders collapses in one pass.
        """
        keep = {self.dir, self.files}
        walked = list(os.walk(self.files)) + list(os.walk(self.dir))
        for dirpath, _dirs, _files in sorted(walked,
                                             key=lambda t: -len(t[0])):
            if os.path.abspath(dirpath) in keep:
                continue
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def report(state, install_info=None):
    """`held()` as text. -> [lines]"""
    out = []
    out.append('hold    : %s' % state['hold'])
    out.append('mods    : %s' % (state['root'] or '(unknown)'))
    if install_info:
        out.extend(_install_lines(install_info))
    if state['damaged_lines']:
        out.append('journal : %d unreadable line(s) - the files themselves are '
                   'still' % state['damaged_lines'])
        out.append('          the record, so nothing is lost, but mod names '
                   'may be missing.')
    if not any((state['out'], state['conflict'], state['missing'])):
        out.append('')
        out.append('nothing is out.')
        return out
    if state['out']:
        mods = sorted({i['mod'] for i in state['out']})
        out.append('')
        out.append('%d file(s) out, from %d mod(s):'
                   % (len(state['out']), len(mods)))
        for m in mods:
            out.append('   %s' % m)
        if state['unjournalled']:
            out.append('   (%d of these are not in the journal; they restore '
                       'from their' % len(state['unjournalled']))
            out.append('    path in the holding directory, which is enough.)')
    if state['conflict']:
        out.append('')
        out.append('CONFLICT - %d file(s) exist in BOTH Mods and the holding '
                   'directory.' % len(state['conflict']))
        out.append('Neither copy will be touched. Compare them and delete one '
                   'by hand:')
        for i in state['conflict'][:10]:
            out.append('   %s' % i['rel'])
    if state['missing']:
        out.append('')
        out.append('MISSING - %d file(s) the journal recorded are on neither '
                   'side:' % len(state['missing']))
        for i in state['missing'][:10]:
            out.append('   %-50s (%s)' % (i['rel'], i['mod']))
        out.append('Something outside this tool moved or deleted them. They '
                   'cannot be')
        out.append('restored from here - reinstall those mods from their '
                   'source.')
    return out


def _install_lines(info):
    import install as _install
    return ['  ' + ln for ln in _install.describe(info)]


def main(argv=None):
    import install as _install
    sims = os.environ.get('SIMS4_DIR') or os.path.join(
        os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
    default_hold = os.environ.get('SULSKILL_BISECT_HOLD') or os.path.join(
        sims, 'sulskill-bisect-hold')

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('action', choices=('status', 'restore'))
    ap.add_argument('--hold', default=default_hold)
    ap.add_argument('--root', default=os.path.join(sims, 'Mods'),
                    help='the Mods folder, if the journal does not name one')
    a = ap.parse_args(argv)

    h = Hold(a.hold, a.root)
    if not os.path.isdir(h.dir):
        print('no holding directory at %s - nothing was ever moved out.'
              % h.dir)
        return 0
    info = _install.detect(h.root) if h.root and os.path.isdir(h.root) else None

    if a.action == 'status':
        state = h.held()
        print('\n'.join(report(state, info)))
        return 1 if (state['conflict'] or state['missing']) else 0

    done, failed = h.restore_all()
    print('restored %d file(s)' % done)
    for rel, why in failed:
        print('   FAILED %-45s %s' % (rel, why))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
