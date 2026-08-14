#!/usr/bin/env python3
"""Build a VERIFIED schema for MCCC settings by reading MCCC's own bytecode.

Why this exists
---------------
MCCC's tooltip corpus gives a reliable key->description mapping for only 41 of
~440 settings, so `explain` had to hedge on the rest. But the *machine-checkable*
half of a setting's contract - its type, default, legal range, and legal string
codes - is not in the tooltips at all. It is in the code, and it is exact.

Every getter in mc_settings.pyc is a one-liner of the form

    def get_show_computer_menu(self):
        return self._get_setting_value('Show_Computer_Menu_Type', 'str', 'A')
    def get_friendship_difficulty_adjustment(self):
        return self._get_setting_value('Friendship_Difficulty_Adjustment', 'int', 0, -50, 10)

so disassembling the call recovers (name, type, default, min, max) exactly.

Do NOT read those arguments off co_consts positionally: CPython de-duplicates
equal constants, so a setting whose default and minimum are both 0 collapses two
arguments into one const and silently shifts everything after it. That is how
Relationship_MoveinPercent (default 0, min 0, max 100) appears as a 3-tuple
while Relationship_BreakupMoveoutSim (default 1, min 0, max 3) appears as a
4-tuple. Disassembly reads real argument order and is immune.

Legal string codes are recovered separately, from the *_choices_dialog functions
that write each setting. A dialog is only trusted when it references exactly one
known setting name - otherwise a function that configures several settings at
once would cross-assign one setting's codes to another.

Run this after an MCCC update; it rewrites reference/mccc_schema.json.
"""
import glob
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pyc37 import load_pyc, walk                                # noqa: E402

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
MODS = _os.path.join(SIMS, 'Mods', 'Vortex Mods')
LIVE = os.path.join(MODS, "mc_settings.cfg")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'reference', 'mccc_schema.json')

# Only the opcodes these small helpers use. The host interpreter's dis.opname is
# WRONG here - 3.11 renumbered the opcode table and TS4 ships 3.7 bytecode.
LOAD_CONST, LOAD_METHOD, LOAD_GLOBAL, LOAD_ATTR = 100, 160, 116, 106
CALL_METHOD, CALL_FUNCTION, CALL_FUNCTION_KW, EXTENDED_ARG = 161, 131, 141, 144

CODE_RE = re.compile(r'^[A-Z][A-Z0-9]{0,3}$')


def instructions(co):
    """Yield (op, arg) for a 3.7 code object, resolving EXTENDED_ARG."""
    ext = 0
    for i in range(0, len(co.code), 2):
        op, arg = co.code[i], co.code[i + 1] | (ext << 8)
        ext = 0
        if op == EXTENDED_ARG:
            ext = arg
            continue
        yield op, arg


def setting_call_args(co):
    """Recover a _get_setting_value(...) call as (positional list, kwargs dict).

    Two call shapes occur. The short getters pass everything positionally
    (CALL_METHOD / CALL_FUNCTION). The ones that constrain a range pass the
    bounds by keyword (CALL_FUNCTION_KW), where the final const is a tuple of
    the keyword NAMES and the values sit immediately before it:

        _get_setting_value('Maximum_Household_Size', 'int', 8,
                           min_value=8, max_value=104)

    Handling only the positional form silently drops every ranged setting -
    which is exactly the set whose bounds are worth validating.
    """
    pending, armed = [], False
    for op, arg in instructions(co):
        if op in (LOAD_METHOD, LOAD_GLOBAL, LOAD_ATTR):
            if co.names[arg] == '_get_setting_value':
                armed, pending = True, []
            continue
        if not armed:
            continue
        if op == LOAD_CONST:
            pending.append(co.consts[arg])
        elif op in (CALL_METHOD, CALL_FUNCTION):
            return pending[:arg], {}
        elif op == CALL_FUNCTION_KW:
            names = pending[-1] if pending and isinstance(pending[-1], tuple) else ()
            if not names:
                return pending[:arg], {}
            vals = pending[-1 - len(names):-1]
            return pending[:arg - len(names)], dict(zip(names, vals))
    return None, None


def scan_getters():
    """name -> {type, default, min, max} from mc_settings.pyc."""
    out = {}
    for script in sorted(glob.glob(os.path.join(MODS, "mc_*.ts4script"))):
        try:
            z = zipfile.ZipFile(script)
        except Exception:
            continue
        for entry in z.namelist():
            if not entry.endswith('.pyc'):
                continue
            try:
                mod = load_pyc(z.read(entry))
            except Exception:
                continue
            for co, _ in walk(mod):
                args, kw = setting_call_args(co)
                if not args or not isinstance(args[0], str):
                    continue
                rec = {'setting': args[0], 'source': f"{os.path.basename(script)}::{entry}"}
                if len(args) > 1 and isinstance(args[1], str):
                    rec['type'] = args[1]
                if len(args) > 2:
                    rec['default'] = args[2]
                # positional bounds (older getters) then keyword bounds
                if len(args) > 3:
                    rec['min'] = args[3]
                if len(args) > 4:
                    rec['max'] = args[4]
                if 'min_value' in kw:
                    rec['min'] = kw['min_value']
                if 'max_value' in kw:
                    rec['max'] = kw['max_value']
                out.setdefault(args[0], rec)
    return out


def scan_codes(known):
    """setting -> sorted legal string codes, from single-setting dialogs."""
    out = {}
    for script in sorted(glob.glob(os.path.join(MODS, "mc_*.ts4script"))):
        try:
            z = zipfile.ZipFile(script)
        except Exception:
            continue
        for entry in z.namelist():
            if not entry.endswith('.pyc'):
                continue
            try:
                mod = load_pyc(z.read(entry))
            except Exception:
                continue
            for co, _ in walk(mod):
                strs = [k for k in (co.consts or ()) if isinstance(k, str)]
                named = [s for s in strs if s in known]
                # exactly one setting in scope, or codes would cross-assign
                if len(set(named)) != 1:
                    continue
                codes = {s for s in strs if CODE_RE.match(s) and s not in known}
                if codes:
                    out.setdefault(named[0], set()).update(codes)
    return {k: sorted(v) for k, v in out.items()}


# Code tables that live in SHARED dialogs - the setting name is passed in as a
# parameter, so it never appears as a const beside its own codes and the
# single-setting rule above cannot find them. Each was read off the bytecode by
# hand; the source is recorded so it can be re-checked after an MCCC update.
SHARED = {
    r'^Show_.*NotificationType$': {
        'codes': ['0', 'N', 'P', 'R', 'AF', 'AR', 'AL'],
        'labels': {'0': 'off', 'AL': 'All', 'N': 'NpcOnly', 'P': 'PlayedOnly'},
        'source': 'mc_cmd_center.ts4script::mc_dialogs.pyc::__init__ '
                  'and mc_utils.pyc::is_sim_valid_for_show_notification',
    },
    r'_DaysToRun$': {
        'codes': ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'],
        'labels': {},
        'strlist': True,
        'note': 'empty string = every day',
        'source': 'mc_pregnancy.ts4script::mc_pregnancy_dlg.pyc::_get_days_to_run_default',
    },
}

# Semantics that are not expressible as type/range, each confirmed against
# bytecode. These are the traps: a value that is legal but does not mean what
# its name suggests.
NOTES = {
    'Relationship_BreakupMoveoutSim':
        'NOT a percentage - selects WHO moves out: 0 None, 1 Male, 2 Female, 3 Random.',
    'Relationship_MoveinPercent':
        'Rolled per eligible sim per story-progression pass, not once across the '
        'population, so it compounds. Gated by Relationship_MoveinRomanceAmt.',
    'Relationship_BreakupPercent':
        'Per-pass roll. Has no DaysToRun, so it gets far more opportunities per '
        'week than Marriage_* does if Marriage_DaysToRun is set.',
    'Relationship_BreakupMarriagePercent':
        'Divorce. Per-pass roll; 1 is the minimum non-zero value.',
    'Show_Sim_Menu_Type':
        'A AllMenus, ASH AllShiftOnly, S SimOnly, SSH SimShiftOnly, R RelPanel, '
        'N NoMenus. S is NOT shift-click - the SH suffix is.',
    'Show_Computer_Menu_Type':
        'A AllMenus, ASH AllShiftOnly, N NoMenus only. Setting S hides the menu '
        'entirely (no branch matches).',
    'Show_Cheats_Menu_Type': 'A AllMenus, ASH AllShiftOnly, N NoMenus only.',
    'Show_Gnome_Menu_Type': 'A AllMenus, ASH AllShiftOnly, N NoMenus. Default N.',
    'RelationshipCullingType':
        'D / E / C. Disabling costs save size but preserves relationship history, '
        'which matters most on long custom lifespans.',
}

DIFFICULTY_CURVE = {
    'applies_to': '*_Difficulty_Adjustment',
    'source': 'mc_cmd_center.ts4script::mc_utils.pyc::get_difficulty_ratio (disassembled)',
    'formula': ('result = 1.0 * v; '
                'if v < 0: pos = -v; '
                'result = round(1 - pos*0.1, 2) if v > -10 else round(1/pos, 2)'),
    'meaning': {
        '0': 'disabled - caller skips the multiplier entirely',
        '1': 'true neutral (1.0x)',
        'positive': 'direct multiplier: 2 -> 2.0x, 10 -> 10.0x',
        '-1..-9': 'linear: 0.9x down to 0.1x (so -4 = 0.6x, -5 = 0.5x)',
        '-10 and below': 'reciprocal cliff: -10 -> 0.1x, -20 -> 0.05x, -50 -> 0.02x',
    },
}


def main():
    if not os.path.isdir(MODS):
        sys.exit(f"MCCC scripts not found: {MODS}")
    live = json.load(open(LIVE, encoding='utf-8')) if os.path.exists(LIVE) else {}
    known = set(live)

    getters = scan_getters()
    codes = scan_codes(known)

    settings = {}
    for name, rec in getters.items():
        entry = {k: v for k, v in rec.items() if k != 'setting'}
        # The single-setting-dialog scrape is a heuristic, so it is sanity-checked
        # twice before anything downstream is allowed to REJECT a value on its say-so:
        #   * a one-element set is a stray constant, not an enumeration;
        #   * if the value currently in the live config is absent from the set, the
        #     set is demonstrably incomplete.
        # Failing either, the codes are still recorded (useful to a reader) but
        # marked unreliable so validation only warns instead of blocking.
        if name in codes and len(codes[name]) >= 2:
            entry['codes'] = codes[name]
            entry['codes_source'] = 'single-setting dialog (heuristic)'
            cur = live.get(name)
            if isinstance(cur, str) and cur and cur not in codes[name]:
                entry['codes_reliable'] = False
                entry['codes_note'] = (f"live value {cur!r} is not in this set, so it "
                                       f"is incomplete - not enforced")
        for pat, shared in SHARED.items():
            if re.search(pat, name):
                entry['codes'] = shared['codes']
                entry['codes_source'] = shared['source']
                if shared.get('strlist'):
                    entry['strlist'] = True
                if shared.get('note'):
                    entry['note'] = shared['note']
        if name in NOTES:
            entry['semantics'] = NOTES[name]
        settings[name] = entry

    # settings present in the config but with no getter (rare; still record them)
    for name in sorted(known - set(settings)):
        settings[name] = {'source': 'present in config, no getter found'}

    doc = {
        'generated_from': MODS,
        'settings': settings,
        'difficulty_curve': DIFFICULTY_CURVE,
        'counts': {
            'total': len(settings),
            'with_type': sum(1 for v in settings.values() if 'type' in v),
            'with_range': sum(1 for v in settings.values() if 'min' in v or 'max' in v),
            'with_codes': sum(1 for v in settings.values() if 'codes' in v),
        },
    }
    os.makedirs(os.path.dirname(os.path.normpath(OUT)), exist_ok=True)
    with open(os.path.normpath(OUT), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write('\n')
    print(f"wrote {os.path.normpath(OUT)}")
    for k, v in doc['counts'].items():
        print(f"  {k:<12} {v}")


if __name__ == '__main__':
    main()
