#!/usr/bin/env python3
"""Read The Sims 4 string tables (STBL) - the map from key hash to display text.

Why this exists: tuning refers to text only by a 32-bit key hash, so a raw
tuning dump is unreadable ("0x07CDB929" tells you nothing). The game's whole
English catalogue lives in one resource, and having it in a dict turns hashes
back into the words a player sees - for naming new content without colliding,
for checking what an existing trait/buff actually says, and for locating the
tuning behind a string the user quotes.

THE GOTCHA. A DBPF index entry carries a compression word, and a reader that
only knows zlib (like dbpf.read here) will hand back the still-compressed bytes
with no error at all - the master STBL is RefPack (0xFFFF), not zlib. The
failure is silent: parse() sees noise where the magic should be, or worse,
plausible-looking lengths that walk off the end. That is why this module owns
its own index scan and routes every resource through refpack.maybe_decompress.
A byte-search for known game text inside Strings_ENG_US.package finding nothing
is this bug, not a wrong guess about where the text lives.

Layout, STBL version 5 (the only version shipped in current builds):
    0   'STBL'
    4   u16 version (5)
    6   u8  compressed flag        - about the strings, not the resource
    7   u64 entry count
    15  2 bytes reserved
    17  u32 string length - measured, this is sum(len) PLUS one byte per entry,
        i.e. the size of a buffer holding every string NUL-terminated. Do not
        use it to bound the entry area or you overrun by `entry count` bytes.
    21  entries begin
Each entry is u32 key hash, u8 flags, u16 length, then `length` UTF-8 bytes,
packed with no padding or alignment between entries.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refpack                                                     # noqa: E402

T_STBL = 0x220557DA
MAGIC = b'STBL'
HEADER_SIZE = 21


def parse(blob):
    """Return {key_hash: str} for a decompressed STBL resource."""
    if blob[:4] != MAGIC:
        raise ValueError(
            'not an STBL - if this came from a package, the resource was very '
            'likely left RefPack-compressed (see module docstring)')
    version = struct.unpack_from('<H', blob, 4)[0]
    if version != 5:
        raise ValueError(f'unsupported STBL version {version}')
    count = struct.unpack_from('<Q', blob, 7)[0]

    out = {}
    p = HEADER_SIZE
    n = len(blob)
    for _ in range(count):
        # Unpacked as one struct because 58k entries times three reads is the
        # difference between a snappy import and a visible pause.
        key, _flags, length = struct.unpack_from('<IBH', blob, p)
        p += 7
        if p + length > n:
            raise ValueError(f'entry for 0x{key:08X} runs past end of resource')
        # errors='replace' rather than strict: a single malformed entry in a
        # 58k-entry table should not cost the caller the other 58,311.
        out[key] = blob[p:p + length].decode('utf-8', errors='replace')
        p += length
    return out


def read_stbls(path):
    """Yield every decompressed STBL resource in a .package.

    Deliberately not dbpf.read(): that one decompresses zlib only, and EA's own
    resources are RefPack. It also drops the compression word, which is the
    thing we need to dispatch on.
    """
    with open(path, 'rb') as f:
        head = f.read(96)
        if head[:4] != b'DBPF':
            raise ValueError(f'not a DBPF: {path}')
        count = struct.unpack_from('<I', head, 0x24)[0]
        isize = struct.unpack_from('<I', head, 0x2C)[0]
        ioff = (struct.unpack_from('<Q', head, 0x40)[0]
                or struct.unpack_from('<I', head, 0x28)[0])
        f.seek(ioff)
        ix = f.read(isize)
        flags = struct.unpack_from('<I', ix, 0)[0]
        p, const = 4, {}
        for bit, key in ((0, 't'), (1, 'g'), (2, 'h')):
            if flags & (1 << bit):
                const[key] = struct.unpack_from('<I', ix, p)[0]
                p += 4
        for _ in range(count):
            t = const.get('t')
            if t is None:
                t = struct.unpack_from('<I', ix, p)[0]; p += 4
            if const.get('g') is None:
                p += 4                                    # group
            if const.get('h') is None:
                p += 4                                    # instance high
            p += 4                                        # instance low
            off = struct.unpack_from('<I', ix, p)[0]; p += 4
            fsz = struct.unpack_from('<I', ix, p)[0]; p += 4
            p += 4                                        # memory size
            comp = 0
            if fsz & 0x80000000:                          # high bit: word follows
                comp = struct.unpack_from('<H', ix, p)[0]; p += 4
            if t != T_STBL:
                continue
            f.seek(off)
            yield refpack.maybe_decompress(f.read(fsz & 0x7FFFFFFF), comp)


def game_dir():
    """Locate the install from the Maxis registry key, with an env fallback.

    Never hard-coded: the game moves between drives and this repo is shared.
    """
    try:
        import winreg
        for key in (r"SOFTWARE\Maxis\The Sims 4",
                    r"SOFTWARE\WOW6432Node\Maxis\The Sims 4"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    return winreg.QueryValueEx(k, "Install Dir")[0]
            except OSError:
                continue
    except ImportError:
        pass
    return os.environ.get("SIMS4_GAME_DIR", "")


def locale_package(locale='ENG_US'):
    """Path to the master string table package for a locale."""
    root = game_dir()
    if not root:
        raise RuntimeError(
            'cannot find the game: no Maxis registry key and SIMS4_GAME_DIR unset')
    return os.path.join(root, 'Data', 'Client', f'Strings_{locale}.package')


def load_game_strings(locale='ENG_US'):
    """Return {key_hash: str} for the whole base catalogue of a locale.

    No cache on purpose. The obvious move is to dump this to reference/, but the
    whole read - RefPack included - measures about a quarter of a second, while
    the JSON would be a 5 MB generated file to gitignore and to invalidate on
    every game patch. Callers that need it repeatedly should hold the dict.
    """
    path = locale_package(locale)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    strings = {}
    for res in read_stbls(path):
        strings.update(parse(res))
    if not strings:
        raise ValueError(f'no STBL resources in {path}')
    return strings


def search(strings, term, limit=40):
    """Case-insensitive substring match, returned as (key_hash, text) pairs."""
    needle = term.lower()
    hits = [(k, v) for k, v in strings.items() if needle in v.lower()]
    return hits[:limit] if limit else hits


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Sims 4 string table reader')
    ap.add_argument('--locale', default='ENG_US')
    ap.add_argument('--search', metavar='TERM')
    ap.add_argument('--key', metavar='HASH', help='look up one key, e.g. 0x07CDB929')
    ap.add_argument('--limit', type=int, default=40, help='0 for all matches')
    ap.add_argument('--package', help='read this .package instead of the install')
    args = ap.parse_args()

    if args.package:
        strings = {}
        for res in read_stbls(args.package):
            strings.update(parse(res))
        source = args.package
    else:
        strings = load_game_strings(args.locale)
        source = locale_package(args.locale)

    print(f'{source}\n{len(strings):,} strings')

    if args.key:
        k = int(args.key, 16 if args.key.lower().startswith('0x') else 10)
        text = strings.get(k)
        print(f'0x{k:08X}  {text!r}' if text is not None else f'0x{k:08X} not found')
    elif args.search:
        hits = search(strings, args.search, args.limit)
        print(f'{len(hits)} match(es) for {args.search!r}:')
        for k, v in hits:
            print(f'  0x{k:08X}  {v}')
    else:
        for k, v in list(strings.items())[:5]:
            print(f'  0x{k:08X}  {v}')
