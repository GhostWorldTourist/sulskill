"""Build the base-game index, in order, and say what it cost.

The index is what lets every other skill here tell an override from new content,
name the EA tuning a mod is sitting on top of, and check a claim about a mod
against what vanilla actually does. It is built from your own installed game.

**It is not downloaded, and it is not shipped.** The finished index is hundreds
of megabytes derived from EA's game files, and it differs with which packs you
own - a shipped copy would under-report for most people while looking
authoritative. So it is built locally, once, and it costs CPU rather than
anything else: every stage below is deterministic Python with no network and no
model in the loop.

    py scripts/index.py               build everything that is missing
    py scripts/index.py --force       rebuild from scratch
    py scripts/index.py --only <name> one stage
    py scripts/index.py --list        what the stages are and what they produce

Then query it with `q.py`, which is the part you use day to day:

    py scripts/q.py id 14965
    py scripts/q.py schema
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, sys, time, argparse, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(gate.out_dir(), 'basegame')

# (stage, script, what it produces, one-line why)
STAGES = (
    ('packages', 'build_packages.py', ('packages.jsonl', 'keys.bin'),
     'every package, its mount and priority, and the whole resource key space'),
    ('packs', 'build_packs.py', ('packs.json',),
     'pack ids, so a resource can be attributed to the pack that shipped it'),
    ('instances', 'build_instances.py', ('instances.jsonl', 'instances_summary.md'),
     'the tuning index - what an instance id actually is'),
    ('simdata', 'build_simdata_schemas.py', ('simdata_schemas.json',),
     'SimData column layouts, versioned by schema hash'),
    ('python', 'build_python_api.py', ('python_api.jsonl',),
     "the game's own classes and signatures, read from bytecode"),
    ('tuning-schema', 'build_tuning_schema.py', ('tunables.json', 'tuning_schema.md'),
     "which fields each tuning type may have, with EA's own descriptions"),
    ('strings', 'stbl.py', ('strings_en.jsonl', 'display_names.jsonl'),
     'player-visible text, and which tuning shows it'),
    ('db', 'build_db.py', ('ts4.db',),
     'fold the above into one queryable SQLite database'),
)


def produced(stage):
    return all(os.path.exists(os.path.join(OUT, f)) for f in stage[2])


def run(stage, force):
    name, script, outputs, why = stage
    if produced(stage) and not force:
        print('  %-14s already built (%s)' % (name, ', '.join(outputs)))
        return True
    print('  %-14s %s ...' % (name, why))
    started = time.time()
    cmd = [sys.executable, os.path.join(HERE, script)]
    if force and script == 'build_db.py':
        cmd.append('--force')
    result = subprocess.run(cmd, cwd=HERE)
    took = time.time() - started
    if result.returncode not in (0, 1):
        print('  %-14s FAILED (exit %d) after %.0fs'
              % (name, result.returncode, took), file=sys.stderr)
        return False
    missing = [f for f in outputs if not os.path.exists(os.path.join(OUT, f))]
    if missing:
        print('  %-14s ran but did not produce %s'
              % (name, ', '.join(missing)), file=sys.stderr)
        return False
    print('  %-14s done in %.0fs' % (name, took))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--force', action='store_true', help='rebuild even if present')
    ap.add_argument('--only', help='run one stage by name')
    ap.add_argument('--list', action='store_true', help='stages and their outputs')
    a = ap.parse_args(argv)

    if a.list:
        for name, script, outputs, why in STAGES:
            print('%-14s %-26s %s' % (name, ','.join(outputs), why))
        return 0

    game = os.environ.get('TS4_INSTALL') or gate.game_dir()
    if not game or not os.path.isdir(game):
        print('cannot find The Sims 4. Set SIMS4_GAME_DIR (or TS4_INSTALL) to '
              'the folder\ncontaining Data\\ and Game\\.', file=sys.stderr)
        return 2

    stages = STAGES
    if a.only:
        stages = tuple(s for s in STAGES if s[0] == a.only)
        if not stages:
            print('no stage %r. --list to see them.' % a.only, file=sys.stderr)
            return 2

    os.makedirs(OUT, exist_ok=True)
    print('game : %s' % game)
    print('index: %s\n' % OUT)
    started = time.time()
    for stage in stages:
        if not run(stage, a.force):
            print('\nstopped. Fix the stage above and re-run; stages already '
                  'built are skipped.', file=sys.stderr)
            return 1
    total = sum(os.path.getsize(os.path.join(OUT, f))
                for _, _, outs, _ in stages for f in outs
                if os.path.exists(os.path.join(OUT, f)))
    print('\nbuilt in %.0fs, %.0f MB in %s'
          % (time.time() - started, total / 1e6, OUT))
    print('Query it: py scripts/q.py schema')
    return 0


if __name__ == '__main__':
    sys.exit(main())
