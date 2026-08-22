"""Prove the test suite can actually fail. `py tests/mutate.py`

A suite that has only ever been run against working code has not been shown to
detect anything. This copies the repository to a temp directory, puts one real
defect back at a time, and asserts that **the test which owns that defect**
fails - then restores and confirms the tree comes back green.

Every mutation below is a bug that was really in this repository, restored
verbatim. None is invented:

  ledger-blank    the bisect ledger's loader falling back to empty state, so
                  `restore` printed "nothing is out" over a full holding
                  directory. On a manual install those were the only copies.
  hold-clobber    arming deleting whatever was already held under the same
                  name to clear the way - on a manual install, deleting the
                  only copy of a previously held mod.
  restore-stomp   restore overwriting a file that already exists in Mods
                  instead of refusing and reporting the collision.
  top-level-units units taken from the top of Mods, so a folder called
                  "Gameplay" became one unit holding every gameplay mod in the
                  library and a bisection could only ever name the cabinet.
  staging-guess   staging counted as a second copy without the deployment
                  manifest tying it to THIS Mods folder, so a manual install
                  was told it had an undo that would not restore one file.
  ambiguous-pick  a bare mod name matching two mods resolving to whichever
                  sorted first, silently cutting a mod nobody named.
  no-charset      the shared report page emitted without <meta charset>, so
                  every report read as windows-1252 off disk and turned § into
                  Â§.
  loose-coherence the save reader's family check counting "half" as a majority,
                  which passes every two-person household whatever its members
                  are called and costs three quarters of the separation.

The disciplines here are borrowed from cyberwise's Test-ToolMutations.ps1,
which learned each of them the hard way:

  * **A copy, never the real tree.** A mutation left behind by a crashed run is
    a defect committed by accident.
  * **The baseline must pass first.** If the unmutated copy fails, nothing
    below means anything, so this refuses to continue.
  * **Assert the test that OWNS the mutation fails**, not merely that something
    did. "The suite went red" is satisfied by an unrelated flake, and then a
    blind test reads as a working one.
  * **Confirm the heal.** A restore that does not restore poisons every later
    result, so each mutation is followed by a clean run.
  * **Say when a mutation no longer applies.** If the anchor text has changed,
    that is reported loudly rather than silently not mutating and blaming the
    tests for not noticing.
  * **A fresh interpreter every run.** Python caches modules, and this suite
    reloads modules and patches shared ones; an in-process re-run would carry
    state between mutations. Two tests in this repository already failed
    order-dependently for exactly that reason.
  * **Normalise line endings before matching.** This repository is checked out
    with CRLF on Windows while the sources are written LF, so an anchor copied
    from a source file will not match the file on disk.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

DOCTOR = 'sulskill-doctor/scripts'
ROSTER = 'sulskill-roster/scripts'

# (name, relative path, anchor, replacement, test name that must fail)
MUTATIONS = [
    ('nothing-is-out: held files reported as nothing being out',
     f'{DOCTOR}/holdlog.py',
     "            'out': out,\n"
     "            'conflict': conflict,",
     "            'out': [],\n"
     "            'conflict': conflict,",
     'test_a_deleted_journal_still_reports_the_files_as_out'),

    ('hold-clobber: arming deleting whatever was already held',
     f'{DOCTOR}/holdlog.py',
     "        if self.locate(rel):",
     "        if False:",
     'test_holding_over_an_existing_held_file_refuses'),

    ('restore-stomp: restore overwriting a file already in Mods',
     f'{DOCTOR}/holdlog.py',
     "        if os.path.exists(dst):\n"
     "            return False, ('a file already exists at that path in Mods - '\n"
     "                           'not overwriting it')",
     "        if False:\n"
     "            return False, 'unreachable'",
     'test_unhold_itself_refuses_an_occupied_path'),

    ('top-level-units: a category folder swallowed as one mod',
     f'{DOCTOR}/bisect_mods.py',
     "        if direct or not subdirs or depth >= MAX_DEPTH:",
     "        if True:",
     'test_a_category_is_descended_into_not_taken_as_one_mod'),

    ('staging-guess: staging counted without a manifest tying it to Mods',
     f'{DOCTOR}/install.py',
     "        'second_copy': bool(man and staging),",
     "        'second_copy': bool(staging),",
     'test_a_manual_install_never_claims_a_second_copy'),

    ('ambiguous-pick: a name matching two mods resolving to the first',
     f'{DOCTOR}/bisect_mods.py',
     "            elif len(hits) > 1:",
     "            elif len(hits) > 1 and False:",
     'test_a_leaf_matching_two_mods_is_refused_not_guessed'),

    ('no-charset: the report page emitted without a charset declaration',
     f'{DOCTOR}/report_style.py',
     "    return (f'<meta charset=\"utf-8\">\\n'\n"
     "            f'<title>{title}</title>",
     "    return (f'<title>{title}</title>",
     'test_it_declares_utf8'),

    ('loose-coherence: half counted as a majority in the family check',
     f'{ROSTER}/savegame.py',
     "            if names and names.most_common(1)[0][1] * 2 > len(h['members']):",
     "            if names and names.most_common(1)[0][1] * 2 >= len(h['members']):",
     'test_a_scrambled_household_join_is_reported'),
]


def norm(text):
    return text.replace('\r\n', '\n')


def run_suite(tree):
    """A fresh interpreter every time. -> (exit code, combined output)."""
    proc = subprocess.run(
        [sys.executable, os.path.join(tree, 'tests', 'run.py')],
        capture_output=True, text=True, cwd=tree,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def failed_tests(output):
    """Test names unittest reported as FAIL or ERROR."""
    return set(re.findall(r'^(?:FAIL|ERROR): (\w+)', output, re.M))


def copy_repo():
    tmp = tempfile.mkdtemp(prefix='sulskill-mutate-')
    tree = os.path.join(tmp, 'repo')
    shutil.copytree(
        REPO, tree,
        ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    return tmp, tree


def main(argv=None):
    only = (argv or sys.argv[1:])
    tmp, tree = copy_repo()
    print('mutating a copy at %s\n' % tree)
    try:
        code, out = run_suite(tree)
        if code != 0:
            print('FAIL  the unmutated copy does not pass - nothing below '
                  'would be meaningful')
            print('\n'.join(out.splitlines()[-25:]))
            return 1
        print('ok    the unmutated copy passes\n')

        npass = nfail = 0
        for name, rel, anchor, replacement, owner in MUTATIONS:
            if only and not any(o in name for o in only):
                continue
            path = os.path.join(tree, rel.replace('/', os.sep))
            with open(path, encoding='utf-8') as f:
                original = f.read()
            if norm(anchor) not in norm(original):
                nfail += 1
                print('FAIL  %s' % name)
                print('        the code this mutation edits has changed - it '
                      'no longer applies')
                print('        looked for: %s' % anchor.splitlines()[0])
                continue

            mutated = norm(original).replace(norm(anchor), norm(replacement))
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(mutated)
            mcode, mout = run_suite(tree)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(original)
            hcode, _hout = run_suite(tree)

            caught = mcode != 0
            right = owner in failed_tests(mout)
            clean = hcode == 0
            if caught and right and clean:
                npass += 1
                print('ok    detects: %s' % name)
                continue
            nfail += 1
            print('FAIL  %s' % name)
            if not caught:
                print('        the bug was put back and every test still '
                      'passed')
            elif not right:
                print('        it failed, but not on the test that owns this')
                print('        expected: %s' % owner)
                got = sorted(failed_tests(mout))
                print('        got     : %s' % (', '.join(got[:4]) or '(none)'))
            if not clean:
                print('        the restore did not put the tree back - later '
                      'results are unreliable')

        print('\n%d detected, %d not' % (npass, nfail))
        return 1 if nfail else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
