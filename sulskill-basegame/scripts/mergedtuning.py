"""Reader for The Sims 4 COMBINED_TUNING resources (type 0x62E94D38).

EA ships gameplay tuning merged: one COMBINED_TUNING resource per Simulation
package holding every instance that package contributes, with an interned
constant pool so repeated subtrees are stored once.

The format is not guessed. It comes out of the game's own bytecode -
sims4/tuning/merged_tuning_manager.pyc, sims4/tuning/serialization.pyc and
sims4/tuning/tunable_base.pyc in Data/Simulation/Gameplay/core.zip.

WHAT THE GAME SAYS THE DOCUMENT IS

    <combined>
      <g s="merged">  ...pool entries, each with x="N"...  </g>
      <R n="buff">    ...one <I> per instance of that tuning type...  </R>
      <R n="trait">   ...  </R>
    </combined>

merged_tuning_manager.NAME_ABBR is the abbreviation table, verbatim:

    Tunable T   TunableEnum E   TunableTuple U   TunableVariant V
    TunableList L   Class C   Module M   Instance I
    class c   name n   module m   type t   instance_type i
    is_none o   TOOL_path p   ref r   ix x   merged g   res_inst s
    Res_Type R

MergedTuningManager._load_combined_file_by_key walks the root's children: a
child tagged 'g' goes to _load_merged_file, which stores every direct child
under its own x attribute - `indexed_tunables[node.get('x')] = node`, with the
index kept as a STRING, never int(). A child tagged 'R' goes to _load_res_node,
which takes the R's n attribute as the resource type name and stores each
child under int(child.get('s')) - so <I s=...> is the instance id in decimal.

REFERENCES

Every consumer in the game does the identical thing, in four places
(serialization.ETreeTuningLoader._load_node twice and ._load_tunable,
tunable._TunableCollection.load_etree_node, tunable.TunableVariant and
tunable.TunableTuple.load_etree_node):

    if child.tag == MergedTuningAttr.Reference:        # 'r'
        node = mtg.get_tunable_node(child.get(MergedTuningAttr.Index))
    ...load `node` in place of `child`...

So <r x="N"/> means "substitute pool slot N here", and it is a plain
substitution of the whole element - tag, attributes, text and children. The
element's *name* is read from the reference before substitution
(child.get('n')), never from the pool entry, which is why a reference can be
written <r n="key" x="5"/> while slot 5 is stored as <T x="5">...</T>. Pool
entries can reference other pool entries, so resolution is recursive.

TWO PHYSICAL ENCODINGS

Only 3 of the 276 resources in a full install are literal XML text. The other
273 are a packed binary the game calls BinaryTuning, handled by the native
_tuning module (`if _tuning.is_binary_merged_tuning(raw): ... binxml.root`).
That is a SimData container - magic 'DATA', version 0x101 - carrying three
named schemas that spell out what it is:

    PackedXmlDocument  { first_element:Object, top_element:Object,
                         element_count:UInt32, string_table:Vector }
    PackedXmlNode      { text:UInt32, attrs:Object, children:Object }
    PackedXmlAttribute { name:UInt32, value:UInt32 }

Every tag, attribute name, attribute value and text run is an index into one
interned string table. Node rows are sorted with all text nodes first, so a
node index below `first_element` is a text run and anything at or above it is
an element. attrs and children are NUL-terminated arrays of relative object
offsets. Nodes are deduplicated - the same node row is reached from several
parents - so the packed document is a DAG, not a tree.

Both encodings decode to the same logical document and this module presents
them identically.

USAGE

    import dbpf_index, mergedtuning

    ents = [(off, fsz, comp) for t, g, i, off, fsz, comp
            in dbpf_index.index(package) if t == 0x62E94D38]
    for blob in dbpf_index.fetch(package, ents):
        ct = mergedtuning.Combined(blob)
        for inst in ct.instances():
            # inst.res_type  'buff'                  (the <R n=...>)
            # inst.attrs     {'c':..., 'i':..., 'm':..., 'n':..., 's':...}
            # inst.id        int(attrs['s'])
            if inst.attrs.get('n') != 'buff_Focused':
                continue
            elem = ct.expand(inst)           # ElementTree Element, no <r> left
            print(mergedtuning.tostring(elem))

Headers alone are cheap: instances() does not resolve anything, so an index of
every instance costs one pass and no pool work.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import io
import struct
import xml.etree.ElementTree as ET
from collections import namedtuple

COMBINED_TUNING = 0x62E94D38

# merged_tuning_manager.NAME_ABBR, from the game's bytecode.
NAME_ABBR = {
    'Tunable': 'T', 'TunableEnum': 'E', 'TunableTuple': 'U',
    'TunableVariant': 'V', 'TunableList': 'L', 'Class': 'C', 'Module': 'M',
    'Instance': 'I', 'class': 'c', 'name': 'n', 'module': 'm', 'type': 't',
    'instance_type': 'i', 'is_none': 'o', 'TOOL_path': 'p', 'ref': 'r',
    'ix': 'x', 'merged': 'g', 'res_inst': 's', 'Res_Type': 'R',
}
ABBR_NAME = {v: k for k, v in NAME_ABBR.items()}

POOL_TAG = NAME_ABBR['merged']        # 'g'
RES_TAG = NAME_ABBR['Res_Type']       # 'R'
INST_TAG = NAME_ABBR['Instance']      # 'I'
REF_TAG = NAME_ABBR['ref']            # 'r'
INDEX_ATTR = NAME_ABBR['ix']          # 'x'
NAME_ATTR = NAME_ABBR['name']         # 'n'
RES_INST_ATTR = NAME_ABBR['res_inst']  # 's'

# How deep expand() will go before it decides something is wrong. Measured
# worst case over every instance in a full install is well under 60; this is
# a guard against pathology, not a real limit.
MAX_DEPTH = 400


class MergedTuningError(Exception):
    """Base for anything this module refuses to decode."""


class ReferenceCycle(MergedTuningError):
    """A pool slot reaches itself. Carries the chain that closed the loop."""

    def __init__(self, chain):
        self.chain = list(chain)
        super().__init__('reference cycle: ' + ' -> '.join(self.chain))


class MissingSlot(MergedTuningError):
    """<r x="N"/> where slot N is not in the pool."""

    def __init__(self, slot):
        self.slot = slot
        super().__init__('reference to undefined pool slot %r' % (slot,))


class TooDeep(MergedTuningError):
    """Expansion exceeded MAX_DEPTH without closing a cycle."""


class Instance(namedtuple('Instance', 'res_type tag attrs node')):
    """One tuning entry's header plus an opaque handle to its body.

    res_type  the <R n=...> this entry sits under - 'buff', 'trait', ...
    tag       'I' instance tuning, 'M' module tuning, 'C' class tuning.
              _load_res_node stores every child of <R>, not just <I>, so
              module tuning is a first-class entry and must not be skipped.
    attrs     the header attributes: c class, i tuning type, m module,
              n tuning name, s instance id (decimal string)
    node      backend handle; pass the Instance itself to Combined.expand()
    """

    __slots__ = ()

    @property
    def id(self):
        """Instance id as an int, from s=. None if absent."""
        s = self.attrs.get(RES_INST_ATTR)
        return int(s) if s is not None else None

    @property
    def name(self):
        """Tuning name, from n=."""
        return self.attrs.get(NAME_ATTR)


def tostring(elem):
    """Serialise an expanded element to a str."""
    return ET.tostring(elem, encoding='unicode')


def is_packed(data):
    """True for the binary BinaryTuning encoding, False for XML text."""
    return data[:4] == b'DATA'


# ---------------------------------------------------------------------------
# backends
#
# Both expose the same tiny node protocol so expand() has one code path:
#   tag(n) attrib(n) text(n) children(n)
# plus pool() and resources(). A "node" is whatever the backend wants it to
# be - an Element for XML, an int row index for the packed form.
# ---------------------------------------------------------------------------

class _XmlDoc:
    """Literal <combined> XML text.

    The pool is read with iterparse and kept; the instance bodies are read on
    a second streaming pass and dropped as they are consumed, so a 14.5 MB
    resource never has more than the pool plus one instance live.
    """

    kind = 'xml'

    def __init__(self, data):
        self._data = data
        self._pool = {}
        # Stop the moment </g> closes: the pool precedes every <R>, and the
        # rest of a 14.5 MB document does not need to be in memory at once.
        it = ET.iterparse(io.BytesIO(data), events=('end',))
        for ev, el in it:
            if el.tag == POOL_TAG:
                for child in el:
                    idx = child.get(INDEX_ATTR)
                    if idx is not None:
                        self._pool[idx] = child
                break
        del it

    def pool(self):
        return self._pool

    def instances(self):
        stack = []
        res_type = None
        for ev, el in ET.iterparse(io.BytesIO(self._data),
                                   events=('start', 'end')):
            if ev == 'start':
                stack.append(el)
                if el.tag == RES_TAG:
                    res_type = el.get(NAME_ATTR)
                continue
            stack.pop()
            if stack and stack[-1].tag == RES_TAG:
                yield Instance(res_type, el.tag, dict(el.attrib), el)
                stack[-1].remove(el)
            elif el.tag == POOL_TAG:
                # Already captured in __init__; free the duplicate.
                el.clear()
                if stack:
                    stack[-1].remove(el)

    @staticmethod
    def tag(n):
        return n.tag

    @staticmethod
    def attrib(n):
        return n.attrib

    @staticmethod
    def text(n):
        return n.text

    @staticmethod
    def tail_of(parent, child):
        return child.tail

    @staticmethod
    def children(n):
        return list(n)


_NULL = 0x80000000


class _PackedDoc:
    """SimData-wrapped PackedXmlDocument.

    Nothing is materialised as an Element until something asks for it, which
    matters: the largest of these decompresses to 32 MB and holds hundreds of
    thousands of node rows.
    """

    kind = 'packed'

    def __init__(self, data):
        d = self._d = data
        if d[:4] != b'DATA':
            raise MergedTuningError('not a DATA container')
        self.version = self._u32(4)
        ti_off, ti_cnt = self._rel(8), self._u32(12)
        sc_off, sc_cnt = self._rel(16), self._u32(20)
        if ti_off is None or sc_off is None:
            raise MergedTuningError('DATA container has no tables')

        by_name, by_size = {}, {}
        for k in range(sc_cnt):
            o = sc_off + 24 * k
            cols = {}
            col_off, col_cnt = self._rel(o + 16), self._u32(o + 20)
            for j in range(col_cnt):
                c = col_off + 20 * j
                cols[self._cstr(self._rel(c))] = (
                    struct.unpack_from('<H', d, c + 8)[0], self._u32(c + 12))
            sch = (self._cstr(self._rel(o)), self._u32(o + 12), cols)
            by_name[o] = sch
            by_size.setdefault(sch[1], sch)

        # EP01/SimulationFullBuild0 ships two TableInfo rows whose schema
        # pointers are garbage - they land inside the column array instead of
        # on a schema record. The schemas themselves are present and correct,
        # so fall back to matching the row size against the schema's declared
        # size, which the container states independently. The game does not
        # care either way: _tuning.BinaryTuning has the layout compiled in and
        # never consults these pointers.
        tables = {}
        self.schema_pointers_ok = True
        for k in range(ti_cnt):
            o = ti_off + 28 * k
            sch_off = self._rel(o + 8)
            dtype, rowsize = self._u32(o + 12), self._u32(o + 16)
            info = (dtype, rowsize, self._rel(o + 20), self._u32(o + 24))
            sch = by_name.get(sch_off)
            if sch is None and sch_off is not None:
                self.schema_pointers_ok = False
            if sch is None:
                sch = by_size.get(rowsize)
            key = sch[0] if sch else '_dtype%d_%d' % (dtype, rowsize)
            tables.setdefault(key, []).append((info, sch))

        try:
            (doc_i, doc_s) = tables['PackedXmlDocument'][0]
            (self._node_i, node_s) = tables['PackedXmlNode'][0]
            (self._attr_i, attr_s) = tables['PackedXmlAttribute'][0]
        except (KeyError, IndexError):
            raise MergedTuningError(
                'DATA container is not a PackedXmlDocument (tables: %s)'
                % sorted(tables)) from None

        self._node_off, self._node_sz = self._node_i[2], self._node_i[1]
        self._node_cnt = self._node_i[3]
        c_text, c_attrs, c_kids = (node_s[2]['text'][1], node_s[2]['attrs'][1],
                                   node_s[2]['children'][1])
        self._c_text, self._c_attrs, self._c_kids = c_text, c_attrs, c_kids
        self._a_name = attr_s[2]['name'][1]
        self._a_value = attr_s[2]['value'][1]

        doc = doc_i[2]
        cols = doc_s[2]
        first = self._rel(doc + cols['first_element'][1])
        top = self._rel(doc + cols['top_element'][1])
        self.element_count = self._u32(doc + cols['element_count'][1])
        st = doc + cols['string_table'][1]
        st_off, st_cnt = self._rel(st), self._u32(st + 4)

        self._strings = []
        if st_off is not None:
            for k in range(st_cnt):
                self._strings.append(self._cstr(self._rel(st_off + 4 * k)))
        # Node rows below first_element are text runs, everything else is an
        # element. This is the document's own discriminator, not a heuristic.
        self._first_elem = (self._idx(first) if first is not None
                            else self._node_cnt)
        if top is None:
            raise MergedTuningError('PackedXmlDocument has no top_element')
        self.root = self._idx(top)

        self._pool_cache = None

    # -- raw readers --------------------------------------------------------
    def _u32(self, o):
        return struct.unpack_from('<I', self._d, o)[0]

    def _rel(self, o):
        v = struct.unpack_from('<I', self._d, o)[0]
        if v == _NULL:
            return None
        return o + struct.unpack_from('<i', self._d, o)[0]

    def _cstr(self, o):
        e = self._d.index(b'\0', o)
        return self._d[o:e].decode('utf-8', 'replace')

    def _idx(self, abs_off):
        return (abs_off - self._node_off) // self._node_sz

    def _row(self, n):
        return self._node_off + self._node_sz * n

    def _reflist(self, o):
        """NUL-terminated array of relative object offsets at abs o."""
        out = []
        while True:
            v = struct.unpack_from('<I', self._d, o)[0]
            if v == _NULL:
                return out
            out.append(o + struct.unpack_from('<i', self._d, o)[0])
            o += 4

    def _is_text(self, n):
        return n < self._first_elem

    # -- node protocol ------------------------------------------------------
    def tag(self, n):
        return self._strings[self._u32(self._row(n) + self._c_text)]

    def attrib(self, n):
        o = self._rel(self._row(n) + self._c_attrs)
        if o is None:
            return {}
        s = self._strings
        return {s[self._u32(a + self._a_name)]:
                s[self._u32(a + self._a_value)] for a in self._reflist(o)}

    def _kids(self, n):
        o = self._rel(self._row(n) + self._c_kids)
        if o is None:
            return []
        return [self._idx(a) for a in self._reflist(o)]

    def text(self, n):
        out = []
        for k in self._kids(n):
            if not self._is_text(k):
                break
            out.append(self._strings[self._u32(self._row(k) + self._c_text)])
        return ''.join(out) or None

    def children(self, n):
        """Element children only; text runs become text()/tails."""
        return [k for k in self._kids(n) if not self._is_text(k)]

    def tail_of(self, parent, child):
        """Text runs that follow `child` inside `parent`, if any."""
        kids = self._kids(parent)
        try:
            i = kids.index(child)
        except ValueError:
            return None
        out = []
        for k in kids[i + 1:]:
            if not self._is_text(k):
                break
            out.append(self._strings[self._u32(self._row(k) + self._c_text)])
        return ''.join(out) or None

    # -- document shape -----------------------------------------------------
    def pool(self):
        if self._pool_cache is None:
            p = {}
            for child in self.children(self.root):
                if self.tag(child) != POOL_TAG:
                    continue
                for slot in self.children(child):
                    idx = self.attrib(slot).get(INDEX_ATTR)
                    if idx is not None:
                        p[idx] = slot
            self._pool_cache = p
        return self._pool_cache

    def instances(self):
        for res in self.children(self.root):
            if self.tag(res) != RES_TAG:
                continue
            res_type = self.attrib(res).get(NAME_ATTR)
            for inst in self.children(res):
                yield Instance(res_type, self.tag(inst), self.attrib(inst),
                               inst)


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

class Combined:
    """A decompressed COMBINED_TUNING resource, either encoding."""

    def __init__(self, data):
        self._doc = _PackedDoc(data) if is_packed(data) else _XmlDoc(data)
        self.kind = self._doc.kind

    @property
    def pool(self):
        """{slot string: unexpanded node}. Slots are strings, as in the game."""
        return self._doc.pool()

    def instances(self):
        """Yield an Instance per child of every <R>. Resolves nothing.

        Includes <M> module tuning and <C> class tuning, because
        _load_res_node stores every child of <R> under int(child.get('s')),
        not only the <I> ones. Filter on Instance.tag if you want just
        instance tuning.
        """
        return self._doc.instances()

    def expand(self, node, max_depth=MAX_DEPTH):
        """Resolve every <r x=.../> under `node` and return standalone XML.

        `node` may be an Instance, a pool slot key, or a node handle from
        either. The result is a fresh ElementTree Element that shares nothing
        with the document and contains no <r> elements and no x= attributes.

        Raises ReferenceCycle if a slot reaches itself, MissingSlot for a
        dangling reference and TooDeep past max_depth.
        """
        if isinstance(node, Instance):
            node = node.node
        elif isinstance(node, str):
            try:
                node = self.pool[node]
            except KeyError:
                raise MissingSlot(node) from None
        return self._expand(node, (), max_depth)

    # `path` is the chain of slots currently being substituted. It has to be
    # the path and not a global visited set: a slot legitimately appears many
    # times in one document, just never inside itself.
    def _expand(self, node, path, max_depth, name=None, drop_index=False):
        if len(path) > max_depth:
            raise TooDeep('expansion exceeded %d levels; last slots %s'
                          % (max_depth, ' -> '.join(path[-8:])))
        doc = self._doc
        tag = doc.tag(node)
        if tag == REF_TAG:
            attrs = doc.attrib(node)
            slot = attrs.get(INDEX_ATTR)
            if slot in path:
                raise ReferenceCycle(list(path) + [slot])
            pool = self.pool
            if slot not in pool:
                raise MissingSlot(slot)
            # The referring element supplies the name; the pool entry supplies
            # everything else. serialization.py reads child.get('n') before it
            # ever looks the slot up, and never consults the slot's own n.
            return self._expand(pool[slot], path + (slot,), max_depth,
                                name=attrs.get(NAME_ATTR), drop_index=True)

        out = ET.Element(tag)
        if name is not None:
            out.set(NAME_ATTR, name)
        for k, v in doc.attrib(node).items():
            if drop_index and k == INDEX_ATTR:
                continue
            # A named reference wins over anything the slot carries; an
            # unnamed one (a list element) means the element has no name, so
            # a stray n on the slot must not leak in either.
            if drop_index and k == NAME_ATTR:
                continue
            out.set(k, v)
        out.text = doc.text(node)
        for child in doc.children(node):
            sub = self._expand(child, path, max_depth)
            sub.tail = doc.tail_of(node, child)
            out.append(sub)
        return out

    def raw(self, node):
        """The unexpanded element, references intact. For inspection."""
        if isinstance(node, Instance):
            node = node.node
        if self.kind == 'xml':
            return node
        return _materialise(self._doc, node)


def _materialise(doc, node):
    out = ET.Element(doc.tag(node))
    for k, v in doc.attrib(node).items():
        out.set(k, v)
    out.text = doc.text(node)
    for child in doc.children(node):
        sub = _materialise(doc, child)
        sub.tail = doc.tail_of(node, child)
        out.append(sub)
    return out


def read(data):
    """Convenience: Combined(data)."""
    return Combined(data)


def iter_resources(package, index=None, fetch=None):
    """Yield (group, instance_id, Combined) for every CT resource in a package.

        import dbpf_index, mergedtuning
        for grp, iid, ct in mergedtuning.iter_resources(pkg):
            ...

    dbpf_index is imported lazily so this module stays a pure decoder that
    can be handed bytes from anywhere.
    """
    if index is None or fetch is None:
        import dbpf_index
        index = index or dbpf_index.index
        fetch = fetch or dbpf_index.fetch
    ents = [(t, g, i, off, fsz, comp)
            for t, g, i, off, fsz, comp in index(package)
            if t == COMBINED_TUNING]
    for (t, g, i, off, fsz, comp) in ents:
        blob = next(fetch(package, [(off, fsz, comp)]))
        yield g, i, Combined(blob)


if __name__ == '__main__':
    # Usage example, and a debugging tool:
    #   py mergedtuning.py <package>                  list tuning types
    #   py mergedtuning.py <package> <type>           list instances of a type
    #   py mergedtuning.py <package> <type> <name>    print expanded XML
    import collections
    import sys

    sys.stdout.reconfigure(encoding='utf-8')
    pkg = sys.argv[1]
    want_type = sys.argv[2] if len(sys.argv) > 2 else None
    want_name = sys.argv[3] if len(sys.argv) > 3 else None

    for grp, iid, ct in iter_resources(pkg):
        print('# %s  group=0x%X instance=%016X  %s  %d pool slots'
              % (pkg, grp, iid, ct.kind, len(ct.pool)), file=sys.stderr)
        if want_type is None:
            n = collections.Counter()
            for inst in ct.instances():
                n[inst.res_type] += 1
            for k, v in sorted(n.items()):
                print('%6d  %s' % (v, k))
            continue
        for inst in ct.instances():
            if inst.res_type != want_type:
                continue
            if want_name is None:
                print('%-22s %-8s %s' % (inst.id, inst.tag, inst.name))
            elif inst.name == want_name:
                print(tostring(ct.expand(inst)))
