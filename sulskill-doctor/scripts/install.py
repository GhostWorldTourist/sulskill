"""How this library was deployed, and whether a second copy of it exists.

Every "moving a file out is harmless" claim in this skill was written on a
Vortex install and is false without one. Under a hardlink-deploying manager the
Mods tree is a set of second names for staging inodes, so hiding one loses
nothing and a purge rebuilds whatever went wrong. Drop the same files into Mods
by hand - which is what most players do - and the deployed file is the only
file. The identical `os.rename` is a no-op in one case and the sole custody of
someone's mod in the other.

So the question worth answering is not "is this Vortex". It is:

    if a file is moved out of Mods, does another copy still exist?

That is `second_copy`, and it is derived from what is on disk rather than from
a manager's name - a manager configured to deploy by copy still has staging, so
it is still recoverable, while a Vortex install whose staging folder has been
moved to another drive is not. Naming the manager would get both backwards.

Nothing here decides anything. It reports, and the caller changes its warnings
and its undo guarantees accordingly.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os

MOD_SUFFIXES = ('.package', '.ts4script')

# A top-level folder holding more than this many packages is being used as a
# category ("CAS", "Gameplay"), not as one mod. The number only has to separate
# a fat single mod from a filing cabinet, and nothing rides on the exact value:
# it changes a warning, never a move.
CATEGORY_HINT = 25


def _nearest(path):
    """The closest ancestor of `path` that exists (possibly `path` itself)."""
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return p
        p = parent
    return p


def _dev(path):
    """Volume id for `path`, or None. st_dev is the volume serial on Windows."""
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def same_volume(a, b):
    """Can `os.rename` move between these two paths? True/False/None.

    Checked against the nearest existing ancestor, because the destination
    usually does not exist yet and a missing path has no volume. Unknown is
    reported as None rather than guessed - the caller refuses on None instead
    of finding out halfway through a move.
    """
    da, db = _dev(_nearest(a)), _dev(_nearest(b))
    if da is None or db is None:
        return None
    return da == db


def vortex_manifest(root):
    """Vortex's deployment manifest inside Mods, or None."""
    man = os.path.join(root, 'Vortex Mods', 'vortex.deployment.json')
    return man if os.path.isfile(man) else None


def staging_dirs():
    """Manager staging folders that exist and actually hold something.

    An empty staging folder is not a second copy. Checking that it is populated
    rather than merely present is the difference between promising recovery and
    providing it.

    VORTEX_TS4_MODS REPLACES the default location rather than adding to it. It
    used to be additive, and on a machine that has Vortex installed for some
    other library the default path exists and is full - so a caller pointing
    this at an empty directory to say "there is no staging here" was answered
    with the unrelated one, and told it had a second copy of somebody else's
    mods.
    """
    env = os.environ.get('VORTEX_TS4_MODS')
    cand = [env] if env else [
        os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')),
                     'Vortex', 'thesims4', 'mods')]
    out = []
    for d in cand:
        if not d or not os.path.isdir(d):
            continue
        try:
            with os.scandir(d) as it:
                if any(True for _ in it):
                    out.append(d)
        except OSError:
            continue
    return out


def hardlinked(root, sample=25):
    """True/False/None: are the deployed files second names for another inode?

    None means it could not be told - no files to sample, or a filesystem that
    does not report link counts. None is not False, and the caller must not
    read it as proof of anything.
    """
    seen, linked = 0, 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.lower().endswith(MOD_SUFFIXES):
                continue
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            seen += 1
            if getattr(st, 'st_nlink', 1) > 1:
                linked += 1
            if seen >= sample:
                return linked > 0
    if not seen:
        return None
    return linked > 0


def layout(root):
    """What one mod looks like in this Mods folder, for a manual install.

    Returned as a dict rather than a verdict because the shapes fail
    differently and the caller warns differently for each:

      folders  one folder per mod - the shape bisection assumes
      flat     loose files at the top of Mods, so a mod that ships several
               files is several units and a round can split it in half
      mixed    both, so both warnings apply
    """
    dirs, loose, other = [], [], 0
    try:
        with os.scandir(root) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        return {'shape': 'empty', 'dirs': [], 'loose': [], 'category': [],
                'other': 0}
    for e in entries:
        if e.name == 'Vortex Mods':
            continue
        if e.is_dir():
            dirs.append(e.name)
        elif e.name.lower().endswith(MOD_SUFFIXES):
            loose.append(e.name)
        else:
            other += 1

    # Folders big enough to be a filing cabinet rather than a mod. Bisecting
    # these still works, it just names "CAS" as the culprit, which is true and
    # useless - so it is worth saying up front rather than after twenty rounds.
    category = []
    for name in dirs:
        n = 0
        for _dp, _dn, files in os.walk(os.path.join(root, name)):
            n += sum(1 for f in files if f.lower().endswith(MOD_SUFFIXES))
            if n > CATEGORY_HINT:
                category.append(name)
                break

    if not dirs and not loose:
        shape = 'empty'
    elif not loose:
        shape = 'folders'
    elif not dirs:
        shape = 'flat'
    else:
        shape = 'mixed'
    return {'shape': shape, 'dirs': dirs, 'loose': loose,
            'category': category, 'other': other}


def detect(root):
    """Everything the caller needs to choose its warnings and its guarantees.

    `second_copy` is the field that matters. True means an undo exists outside
    this tool - the manager can redeploy - and a lost holding directory is an
    inconvenience. False means this tool's holding directory and its journal
    are the only route back, which is a different promise and has to be kept
    differently.
    """
    man = vortex_manifest(root)
    staging = staging_dirs()
    kind = 'vortex' if man else 'manual'
    # A populated staging folder is only a second copy OF THIS LIBRARY if
    # something ties the two together, and the deployment manifest inside Mods
    # is that tie. Without it the staging folder belongs to a different game
    # folder, or is what is left after a purge - and a manual install that once
    # had Vortex would otherwise be told it has an undo that will not restore
    # a single one of its files. Erring towards "no second copy" only ever
    # makes this tool more careful.
    return {
        'root': root,
        'kind': kind,
        'manifest': man,
        'staging': staging,
        'second_copy': bool(man and staging),
        'hardlinked': hardlinked(root),
        'layout': layout(root) if kind == 'manual' else
                  {'shape': 'managed', 'dirs': [], 'loose': [],
                   'category': [], 'other': 0},
    }


def describe(info):
    """The install, in the terms the person reading it needs. -> [lines]"""
    out = []
    if info['kind'] == 'vortex':
        out.append('install : Vortex (deployment manifest found)')
    else:
        out.append('install : manual - no mod manager deployment manifest')

    if info['second_copy']:
        out.append('undo    : staging holds a second copy, at')
        out.append('          %s' % info['staging'][0])
        out.append('          A redeploy from the manager rebuilds Mods '
                   'whatever happens here.')
    else:
        out.append('undo    : THIS TOOL ONLY. No staging copy was found, so '
                   'the holding')
        out.append('          directory and its journal are the only way '
                   'back. Do not delete')
        out.append('          them, and restore before uninstalling anything.')

    shape = info['layout']['shape']
    if shape in ('flat', 'mixed'):
        which = ('loose files at the top of Mods' if shape == 'flat'
                 else 'folders and loose files')
        out.append('layout  : %s. A mod that ships several loose' % which)
        out.append('          files counts as several units here, so a round '
                   'can disable half')
        out.append('          of one mod - which behaves like a broken mod and '
                   'is not one.')
        out.append('          Group them into folders first, or take the '
                   'grouping from')
        out.append('          deep_scan.py, before cutting.')
    if info['layout']['category']:
        names = ', '.join(info['layout']['category'][:4])
        more = (' and %d more' % (len(info['layout']['category']) - 4)
                if len(info['layout']['category']) > 4 else '')
        out.append('folders : %s%s hold enough packages to be' % (names, more))
        out.append('          categories rather than mods. Bisecting names the '
                   'folder, not')
        out.append('          the mod inside it.')
    return out
