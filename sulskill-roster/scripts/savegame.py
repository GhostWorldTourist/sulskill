"""Read a Sims 4 save file: its worlds, lots, households and Sims.

A `.save` is a DBPF package like any other, and the resource that matters is
type `0x0000000D` - a single protobuf message a few megabytes wide holding the
whole simulated world. Everything here comes out of that message.

How the field numbers were established, since that is the only part worth
distrusting
-------------------------------------------------------------------------------
There is no published schema for this, so nothing below is quoted from one and
nothing is guessed either. Each field was fixed by reading a real save and
requiring the reading to be falsifiable:

  * The four repeated top-level records were identified by their contents.
    Field 4 carries 'Willow Creek' and its in-game description; field 7 carries
    lot names like 'Oakenstead'; field 5 carries a surname and a number that
    behaves like money; field 6 carries a first and last name.

  * `sim.household` was confirmed by joining it, not by inspection. Every one
    of 386 Sims joined a household record, and the household's own name matched
    the surname the Sim record carries independently - 386 agreements, zero
    disagreements. A join that is right by accident does not do that.

  * `lot.world` joined 414 of 414. `household.lot` joins only some households
    on purpose: the rest have no home, which is the game's own unhoused pool
    and is reported as such rather than as a failure.

  * `sim.gender` and `sim.age` were found by distribution, then checked against
    the game itself. Across 386 Sims exactly one field takes only {4096, 8192}
    and exactly one takes only powers of two up to 128 - and `enums()` below
    reads `sims/sim_info_types.pyc` out of the installed game to get the names,
    rather than trusting anybody's memory of them. That is where INFANT = 128
    comes from; it is not written down here as a fact, it is looked up.

  * Species is deliberately absent. No field in the sample took species-shaped
    values, so there is nothing to report and a guess would have been a lie
    about somebody's pets.

`verify()` re-checks all of that at runtime against the save in front of it. A
game patch that renumbers a field should make this say so, loudly, rather than
quietly relabelling somebody's family.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  '..', '..', 'sulskill-modbuild', 'scripts'))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  '..', '..', 'sulskill-basegame', 'scripts'))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import collections
import os
import re
import struct
import zipfile

import pb
import refpack
import dbpf_index

SAVE_DATA = 0x0000000D          # the resource holding the simulated world

# Top-level repeated records.
F_WORLD, F_HOUSEHOLD, F_SIM, F_LOT = 4, 5, 6, 7

# Within each record. Named rather than inlined so the reading is legible and
# so verify() and the readers cannot drift apart.
W_ID, W_NAME, W_DESC = 1, 3, 10
H_ID, H_NAME, H_LOT, H_FUNDS, H_CREATOR = 2, 3, 4, 5, 21
S_HOUSEHOLD, S_FIRST, S_LAST, S_GENDER, S_AGE, S_SURNAME = 4, 5, 6, 7, 8, 22
L_ID, L_NAME, L_WORLD, L_DESC = 1, 2, 10, 14

# Used only if the installed game cannot be read - see enums(). Kept because a
# report with no life stages is worse than one that says where its labels came
# from, but it is the fallback and it says so.
FALLBACK_AGE = {1: 'Baby', 2: 'Toddler', 4: 'Child', 8: 'Teen',
                16: 'Young Adult', 32: 'Adult', 64: 'Elder', 128: 'Infant'}
FALLBACK_GENDER = {4096: 'Male', 8192: 'Female'}

AGE_ORDER = (128, 1, 2, 4, 8, 16, 32, 64)     # youngest to oldest, for display

# Whether the household join is sound is tested by family coherence: in a
# household of two or more, do at least half the members share one last name?
#
# Comparing a Sim's surname against their household's NAME cannot do this job.
# People rename households, marry Sims across them, take in roommates and
# delete the premades outright, and every one of those makes the two differ
# while the join stays perfectly correct - one renamed household makes all of
# its members "disagree" at once, so no threshold separates an edited save from
# a broken reader.
#
# Coherence does separate them, measured rather than assumed. Across three real
# saves the true join scores 0.74-0.77; the same saves with their members
# shuffled between households score 0.00-0.01. 0.40 sits in the middle of that
# gap with room on both sides.
#
# "Majority" is strict on purpose. Counting half as coherent makes every
# two-person household pass whatever its members are called, which is most of
# the sample and washed the signal out - the loose rule scored 0.90 real
# against 0.39 shuffled, a quarter of the separation.
COHERENCE_LIMIT = 0.40
COHERENCE_MIN_SAMPLE = 8


def enums():
    """Age and Gender names, read out of the installed game. -> (ages, genders, source)

    The game ships its own Python, and `sims/sim_info_types.pyc` defines both
    enums. Reading them means a patch that adds a life stage is picked up
    instead of mislabelled, and it means these names are the game's rather than
    a tool author's recollection - which is exactly the sort of detail that is
    easy to be confidently wrong about.

    Falls back to a copy taken the same way, and says which was used.
    """
    try:
        import pyc37
        base = gate.game_dir()
        zpath = os.path.join(base, 'Data', 'Simulation', 'Gameplay',
                             'simulation.zip')
        with zipfile.ZipFile(zpath) as z:
            co = pyc37.load_pyc(z.read('sims/sim_info_types.pyc'))
        found = {}
        for c, _depth in pyc37.walk(co):
            name = getattr(c, 'name', None)
            if name in ('Age', 'Gender') and name not in found:
                got = _class_ints(c)
                if got:
                    found[name] = got
        if 'Age' in found and 'Gender' in found:
            ages = {v: _pretty(k) for k, v in found['Age'].items()
                    if v in AGE_ORDER}
            genders = {v: _pretty(k) for k, v in found['Gender'].items()}
            if ages and genders:
                return ages, genders, 'the installed game'
    except Exception:                                          # noqa: BLE001
        pass
    return dict(FALLBACK_AGE), dict(FALLBACK_GENDER), 'a stored copy'


def _class_ints(code):
    """`NAME = <int>` assignments in a 3.7 class body, from its bytecode.

    LOAD_CONST followed by STORE_NAME is what a class-level constant compiles
    to. Reading the bytecode rather than executing it keeps this from running
    any of the game's code.
    """
    out, last = {}, None
    body = code.code
    for i in range(0, len(body) - 1, 2):
        op, arg = body[i], body[i + 1]
        if op == 100:                                   # LOAD_CONST
            last = code.consts[arg]
        elif op == 90:                                  # STORE_NAME
            if isinstance(last, int) and not isinstance(last, bool):
                out[code.names[arg]] = last
            last = None
    return out


def _pretty(name):
    """YOUNGADULT -> Young Adult, ELDER -> Elder."""
    special = {'YOUNGADULT': 'Young Adult'}
    if name in special:
        return special[name]
    return name.capitalize()


def _text(v):
    try:
        s = v.decode('utf-8')
    except UnicodeDecodeError:
        return ''
    return s if s.isprintable() else ''


def _rec(blob):
    """One protobuf message -> {field number: [values]}."""
    out = {}
    for f, _wt, v in pb.parse(blob):
        out.setdefault(f, []).append(v)
    return out


def _one(rec, field, default=None):
    got = rec.get(field)
    return got[0] if got else default


class Save:
    """One save file, read. Plain data - nothing here touches the game."""

    def __init__(self, path):
        self.path = path
        self.slot = os.path.basename(path)
        self.size = os.path.getsize(path)
        self.mtime = os.path.getmtime(path)
        self.worlds, self.households, self.sims, self.lots = [], [], [], []
        self.ages, self.genders, self.enum_source = enums()
        self._read()

    # ---- reading -------------------------------------------------------

    def _payload(self):
        entries = [e for e in dbpf_index.index(self.path) if e[0] == SAVE_DATA]
        if not entries:
            raise ValueError('%s has no save-data resource (type 0x%08X). '
                             'It may be a backup shell or a different kind of '
                             'package.' % (self.slot, SAVE_DATA))
        # Largest, in the event a save ever carries more than one.
        _t, _g, _i, off, fsz, comp = max(entries, key=lambda e: e[4])
        with open(self.path, 'rb') as fh:
            fh.seek(off)
            raw = fh.read(fsz)
        return refpack.maybe_decompress(raw, comp)

    def _read(self):
        top = pb.parse(self._payload())
        for f, _wt, v in top:
            if f == F_WORLD:
                self.worlds.append(self._world(_rec(v)))
            elif f == F_HOUSEHOLD:
                self.households.append(self._household(_rec(v)))
            elif f == F_SIM:
                self.sims.append(self._sim(_rec(v)))
            elif f == F_LOT:
                self.lots.append(self._lot(_rec(v)))
        self._link()

    def _world(self, r):
        return {'id': _one(r, W_ID), 'name': _text(_one(r, W_NAME, b'')),
                'description': _text(_one(r, W_DESC, b'')),
                'lots': [], 'households': [], 'population': 0}

    def _household(self, r):
        return {'id': _one(r, H_ID), 'name': _text(_one(r, H_NAME, b'')),
                'lot_id': _one(r, H_LOT), 'funds': _one(r, H_FUNDS, 0),
                'creator': _text(_one(r, H_CREATOR, b'')),
                'members': [], 'lot': None, 'world': None}

    def _sim(self, r):
        first = _text(_one(r, S_FIRST, b''))
        last = _text(_one(r, S_LAST, b''))
        return {'first': first, 'last': last,
                'name': (first + ' ' + last).strip(),
                'household_id': _one(r, S_HOUSEHOLD),
                'surname': _text(_one(r, S_SURNAME, b'')),
                'gender': _one(r, S_GENDER), 'age': _one(r, S_AGE),
                'household': None}

    def _lot(self, r):
        return {'id': _one(r, L_ID), 'name': _text(_one(r, L_NAME, b'')),
                'world_id': _one(r, L_WORLD),
                'description': _text(_one(r, L_DESC, b'')),
                'world': None, 'household': None}

    def _link(self):
        worlds = {w['id']: w for w in self.worlds if w['id'] is not None}
        lots = {l['id']: l for l in self.lots if l['id'] is not None}
        houses = {h['id']: h for h in self.households if h['id'] is not None}

        for lot in self.lots:
            w = worlds.get(lot['world_id'])
            if w:
                lot['world'] = w
                w['lots'].append(lot)
        for h in self.households:
            lot = lots.get(h['lot_id'])
            if lot:
                h['lot'] = lot
                lot['household'] = h
                h['world'] = lot['world']
                if lot['world']:
                    lot['world']['households'].append(h)
        for s in self.sims:
            h = houses.get(s['household_id'])
            if h:
                s['household'] = h
                h['members'].append(s)
        for h in self.households:
            if h['world']:
                h['world']['population'] += len(h['members'])

    # ---- labels --------------------------------------------------------

    def age_name(self, sim):
        return self.ages.get(sim['age'], 'Unknown')

    def gender_name(self, sim):
        return self.genders.get(sim['gender'], 'Unknown')

    # ---- derived facts -------------------------------------------------

    def housed(self):
        return [h for h in self.households if h['lot']]

    def unhoused(self):
        return [h for h in self.households if not h['lot']]

    def by_age(self):
        """{age value: count}, in life-stage order."""
        seen = collections.Counter(s['age'] for s in self.sims)
        order = [a for a in AGE_ORDER if a in seen]
        order += [a for a in sorted(seen) if a not in AGE_ORDER]
        return [(a, seen[a]) for a in order]

    def by_gender(self):
        return collections.Counter(s['gender'] for s in self.sims)

    def surnames(self, limit=10):
        counts = collections.Counter(s['last'] for s in self.sims if s['last'])
        return counts.most_common(limit)

    def total_funds(self):
        return sum(h['funds'] or 0 for h in self.households)

    def occupied_worlds(self):
        return [w for w in self.worlds if w['households']]

    def coherence(self):
        """Do households look like families? -> (fraction, households measured)

        For each household of two or more: does a MAJORITY share one last name?
        This is the test that the household join is real, and it is deliberately
        blind to what the household is called, because renaming one is the most
        ordinary edit there is.

        A blended family, a couple who kept their names, a house of roommates -
        each of those is a genuine miss, and all of them are ordinary. That is
        why the answer is a proportion across the whole save rather than a
        verdict on any one household, and why the threshold sits far below what
        a real save scores.
        """
        multi = [h for h in self.households if len(h['members']) >= 2]
        if not multi:
            return 1.0, 0
        ok = 0
        for h in multi:
            names = collections.Counter(m['last'] for m in h['members']
                                        if m['last'])
            if names and names.most_common(1)[0][1] * 2 > len(h['members']):
                ok += 1
        return ok / len(multi), len(multi)

    # ---- self-check ----------------------------------------------------

    def verify(self):
        """Re-check every assumption this reader makes. -> [complaint strings]

        Empty means the save agreed with the field map on every point that can
        be tested. A non-empty list is not a crash and not a reason to hide the
        report - it is the reason to print what stopped agreeing, because a
        renumbered field is exactly what a game patch does and exactly what
        would otherwise turn this into a confident wrong answer.
        """
        bad = []
        if not self.sims:
            bad.append('no Sims were found at all - the record layout has '
                       'probably changed')
            return bad

        joined = [s for s in self.sims if s['household']]
        if len(joined) < len(self.sims):
            bad.append('%d of %d Sims did not join a household'
                       % (len(self.sims) - len(joined), len(self.sims)))
        ratio, sample = self.coherence()
        if sample >= COHERENCE_MIN_SAMPLE and ratio < COHERENCE_LIMIT:
            bad.append('only %d%% of households of two or more have a majority '
                       'sharing one last name (across %d households). A real '
                       'save runs about 75%%, and a join that put Sims in the '
                       'wrong households runs about 0%% - so the household join '
                       'looks wrong rather than the families looking unusual'
                       % (round(ratio * 100), sample))

        stray = [l for l in self.lots if l['world'] is None]
        if stray:
            bad.append('%d lots are in no world' % len(stray))

        unknown_age = {s['age'] for s in self.sims} - set(self.ages)
        if unknown_age:
            bad.append('life stage values with no name in the game\'s own '
                       'enum: %s' % sorted(unknown_age))
        unknown_sex = {s['gender'] for s in self.sims} - set(self.genders)
        if unknown_sex:
            bad.append('gender values with no name in the game\'s own enum: %s'
                       % sorted(unknown_sex))

        nameless = [s for s in self.sims if not s['name']]
        if len(nameless) > len(self.sims) // 10:
            bad.append('%d Sims have no readable name' % len(nameless))
        return bad


SLOT = re.compile(r'^Slot_[0-9A-Fa-f]{8}\.save$')


def saves_dir():
    sims = os.environ.get('SIMS4_DIR') or os.path.join(
        os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
    return os.path.join(sims, 'saves')


def find_saves(directory=None):
    """Current saves, newest first. Backups are deliberately excluded.

    The game keeps `.ver0`, `.ver1` and `.day.ver0` alongside each slot. They
    are previous states of the same save, so listing them would offer somebody
    five copies of one world and no way to tell which is theirs.
    """
    directory = directory or saves_dir()
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    hits = [os.path.join(directory, n) for n in names if SLOT.match(n)]
    return sorted(hits, key=lambda p: os.path.getmtime(p), reverse=True)
