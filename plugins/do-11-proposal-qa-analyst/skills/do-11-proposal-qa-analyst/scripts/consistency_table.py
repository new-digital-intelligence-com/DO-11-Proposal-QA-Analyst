#!/usr/bin/env python3
"""Consistency gate. Two modes, one extraction engine.

    DRAFT mODE  — one document against its sources (produce-from-template / DO-03)
      consistency_table.py DRAFT --sources FILE [FILE ...] [--exempt V ...] [--json OUT]

    SET MODE    — a family of related documents against each other (audit-and-propose)
      consistency_table.py --set FILE [FILE ...] --authority FILE [--json OUT]

Lives in core/scripts rather than under an archetype because both need it and neither
owns it. Duplicating it would mean two copies of the extraction rules, and the rules
are the part that took the tuning.

**Draft mode** asks two questions, in order of how much they matter:

  1. **Does the draft contradict itself?** The same thing stated two ways — a minimum
     engagement that is £5M in the summary and £5,000,000 in the terms, a product
     called "Apex Advisory" on page 1 and "Apex advisory" on page 6, a date that
     moves. Reviewers catch these, which is the whole cost: their attention goes on
     proofreading instead of on the substance.

  2. **Does every figure in the draft exist in a source?** This is the one that is not
     a proofreading matter. A number in the draft that appears in none of the supplied
     sources was not supplied — it was written. Reporting it is the point of the gate.

**Set mode** asks a third: **where do these documents disagree with each other?** Same
labelled field, two values, in two documents. With `--authority` naming which document
outranks the others, each disagreement carries a proposed direction — change the
lower-ranked one. Without it, disagreements are reported with no direction, because
picking one on length or recency is how an audit corrupts a document estate.

Set mode also reports **facts stated exactly once** across the whole set. A figure with
one occurrence has nothing to be checked against; calling that clean is the quiet
failure this mode exists to prevent.

Deliberately not clever, in both modes. It does not judge whether a claim is true, does
not resolve a contradiction by picking a winner, and does not rewrite anything. It
produces the table a human reads, and it exits non-zero on the findings that must not be
scrollable past.

Reads .docx, .txt and .md with the standard library only — python-docx is frequently
absent and pip frequently cannot reach PyPI from a skill runtime.
"""
import argparse, json, re, sys, unicodedata, zipfile
from collections import defaultdict
from pathlib import Path

# --- extraction -------------------------------------------------------------

_WT = re.compile(r'<w:t(?:\s[^>]*)?>(.*?)</w:t>', re.S)
_PARA = re.compile(r'</w:p>')
_TAG = re.compile(r'<[^>]+>')


def docx_paragraphs(path: Path):
    """Paragraph text from a .docx, runs joined — a token or a figure is routinely
    split across three <w:t> elements after a spell-check pass, and reading each
    element separately turns '5,000,000' into '5', '000' and '000'."""
    with zipfile.ZipFile(path) as z:
        parts = [n for n in z.namelist()
                 if re.fullmatch(r'word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml', n)]
        for n in sorted(parts):
            xml = z.read(n).decode('utf-8', 'replace')
            for chunk in _PARA.split(xml):
                txt = ''.join(_WT.findall(chunk))
                txt = _TAG.sub('', txt)
                txt = (txt.replace('&amp;', '&').replace('&lt;', '<')
                          .replace('&gt;', '>').replace('&quot;', '"')
                          .replace('&apos;', "'"))
                if txt.strip():
                    yield txt.strip()


def paragraphs(path: Path):
    if path.suffix.lower() in ('.docx', '.dotx'):
                                       # .dotx is the same package shape
        yield from docx_paragraphs(path)
    else:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.strip():
                yield line.strip()


# --- patterns ---------------------------------------------------------------

CURRENCY = '£$€¥'
# A money or plain figure, with optional thousands separators, decimals, a scale
# suffix and a trailing percent. The scale suffix is what makes £5M and £5,000,000
# collide, which is the interesting case.
NUM = re.compile(
    rf'(?P<cur>[{CURRENCY}])?\s?'
    r'(?P<val>\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'\s?(?P<scale>[kKmMbB]n?\b|billion|million|thousand)?'
    r'\s?(?P<pct>%)?'
)
DATE = re.compile(
    r'\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}'
    r'|\d{4}-\d{2}-\d{2}'
    r'|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}'
    r'|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}'
    r'|Q[1-4]\s?(?:FY)?\d{2,4})\b'
)
# Two or more capitalised words in a row: the shape of a product, service or entity
# name. Sentence-initial capitals produce noise, which is why single words are out.
PROPER = re.compile(r'\b([A-Z][\w&.\'-]+(?:\s+(?:of|for|and|the|de|van)\s+|\s+)'
                    r'[A-Z][\w&.\'-]+(?:\s+[A-Z][\w&.\'-]+)*)\b')
EMAIL = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b')
URL = re.compile(r'\bhttps?://[^\s<>"\')]+')

SCALES = {'k': 1e3, 'm': 1e6, 'mn': 1e6, 'b': 1e9, 'bn': 1e9,
          'thousand': 1e3, 'million': 1e6, 'billion': 1e9}

# Figures that carry no commitment and would swamp the table.
TRIVIAL = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 24.0}

# Text that must not be read as a figure. Both were false positives on the first
# DO-03 run, where the gate reported six findings of which one was real — and a gate
# with five false positives out of six is a gate a reviewer learns to skip, which is
# worse than no gate.
VERSION = re.compile(r'\bv?\d+\.\d+(?:\.\d+)?\b(?=\s|$|[,;)\]])', re.I)

# A phone number is not a figure. "0800 555 0100" was parsed as 555010 and reported as
# an unsourced value — a finding that is both false and unintelligible. Matched before
# figures so the digits are masked out.
PHONE = re.compile(r'(?<![\d.])(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?){2,4}\d{2,4}'
                   r'(?![\d.])')

MONTHS = {m[:3].lower(): m for m in (
    'January February March April May June July August September October November '
    'December').split()}


def mask(text: str, *patterns) -> str:
    """Blank out matched spans, preserving length so offsets stay comparable.

    A date matched as a date must not also be harvested as a figure: "30 November
    2026" was reported as the unsourced figure 30, sitting in the table next to a
    real finding.
    """
    out = text
    for pat in patterns:
        out = pat.sub(lambda m: ' ' * len(m.group(0)), out)
    return out


def norm_date(s: str) -> str:
    """Canonical form for a date, so '12 Aug 2026' and '12 August 2026' agree.

    Without this, a draft citing its source's own approval date was reported as
    unsourced purely because the source abbreviated the month.
    """
    t = re.sub(r'[.,]', ' ', s)
    t = re.sub(r'\s+', ' ', t).strip()

    def month(m):
        return MONTHS.get(m.group(0)[:3].lower(), m.group(0))

    t = re.sub(r'\b[A-Za-z]{3,9}\b', month, t)
    return t.casefold()


def numeric_value(m) -> float | None:
    raw = m.group('val').replace(',', '').replace(' ', '')
    try:
        v = float(raw)
    except ValueError:
        return None
    s = (m.group('scale') or '').lower().rstrip('.')
    if s in SCALES:
        v *= SCALES[s]
    return v


def canonical_number(m) -> tuple[str, float] | None:
    """A scale-independent key, so £5M and £5,000,000 land in the same bucket."""
    v = numeric_value(m)
    if v is None:
        return None
    if m.group('pct'):
        return (f'{v:g}%', v)
    cur = m.group('cur') or ''
    if not cur and v in TRIVIAL:
        return None
    # Round to the nearest penny/cent so 5000000 and 5000000.00 agree.
    return (f'{cur}{round(v, 2):g}', v)


def norm_name(s: str) -> str:
    s = unicodedata.normalize('NFKD', s)
    s = re.sub(r'[\s\-–—_]+', ' ', s).strip()
    return s.casefold()


# "Minimum engagement: 250 endpoints" — a paragraph that states a named field. This
# is the only shape in which "the same thing stated twice" can be detected
# mechanically, because it is the only one where the document says what the number
# refers to. Everything else needs a reader; see the units table.
FIELD = re.compile(r'^(?P<label>[A-Za-z][A-Za-z \-/&]{2,40})\s*[:–—]\s*(?P<rest>\S.*)$')

# Units are collected for a human to scan, never to fail a run. "1.4 days" and
# "6.2 days" share a unit and are both correct — a before-and-after pair. Grouping on
# units and calling the result a contradiction would flag every improvement figure in
# the document.
UNIT = re.compile(r'\s*[-–]?\s*([A-Za-z]{4,24})')
UNIT_STOP = {'from', 'to', 'and', 'the', 'of', 'in', 'on', 'for', 'per', 'with',
             'that', 'this', 'than', 'across', 'over', 'under', 'about', 'was',
             'were', 'are', 'is', 'moved', 'fell', 'rose', 'billed'}


def unit_after(text: str, end: int) -> str | None:
    m = UNIT.match(text, end)
    if not m:
        return None
    w = m.group(1).casefold()
    if w in UNIT_STOP:
        return None
    return w[:-1] if w.endswith('s') and len(w) > 4 else w


# --- the table --------------------------------------------------------------

def collect(path: Path) -> dict:
    """{kind: {canonical_key: {surface_form: [contexts]}}}

    Plus two extra views used only for the contradiction findings:
      `field` — normalised label -> canonical value -> [(section, as written)]
      `unit`  — normalised unit  -> canonical value -> [(section, as written)]
    """
    out = {k: defaultdict(lambda: defaultdict(list))
           for k in ('figure', 'date', 'name', 'email', 'url', 'field', 'unit')}
    section = '(before the first heading)'
    for para in paragraphs(path):
        # A short paragraph with no terminal punctuation reads as a heading, which is
        # the best available section marker once the docx has been flattened to text.
        if len(para) < 80 and not para.rstrip().endswith(('.', ':', ';', ',', '?', '!')):
            section = para
        ctx = para if len(para) <= 120 else para[:117] + '...'
        # Figures are harvested from text with dates and version numbers blanked out,
        # so a date's day and a version's minor number are not counted twice.
        masked = mask(para, DATE, VERSION, PHONE)
        fm = FIELD.match(masked)
        label = norm_name(fm.group('label')) if fm else None
        # A labelled line carrying two or more figures is a range or a compound —
        # "Evidence: patch compliance moved from 71% to 96%" — not one field with two
        # competing values. Recording both put a false CONFLICT at the top of the
        # first real report, above the finding that mattered.
        if label and sum(1 for m in NUM.finditer(fm.group('rest'))
                         if canonical_number(m)) != 1:
            label = None
        for m in NUM.finditer(masked):
            c = canonical_number(m)
            if not c:
                continue
            surface = m.group(0).strip()
            out['figure'][c[0]][surface].append((section, ctx))
            if label:
                out['field'][label][c[0]].append((section, surface))
            if not m.group('pct'):
                u = unit_after(masked, m.end())
                if u:
                    out['unit'][u][c[0]].append((section, surface))
        for m in DATE.finditer(para):
            out['date'][norm_date(m.group(0))][m.group(0)].append((section, ctx))
        for m in PROPER.finditer(para):
            g = m.group(1)
            if len(g) > 3:
                out['name'][norm_name(g)][g].append((section, ctx))
        out['_paras'] = out.get('_paras', [])
        out['_paras'].append((section, para, ctx))
        for m in EMAIL.finditer(para):
            out['email'][m.group(0).casefold()][m.group(0)].append((section, ctx))
        for m in URL.finditer(para):
            out['url'][m.group(0).casefold()][m.group(0)].append((section, ctx))

    # Second pass over the names found: rescan case-insensitively so a name written
    # once as "Meridian Essential" and once as "Meridian essential" is recognised as
    # the same name. The first pass cannot see the second form at all — PROPER
    # requires a capital on every word, so a de-capitalised variant never matches and
    # the inconsistency is invisible, which is the case it most needs to catch.
    known = sorted(out['name'], key=len, reverse=True)
    for key in known:
        pat = re.compile(r'\b' + r'[\s\-–—]+'.join(re.escape(w) for w in key.split())
                         + r'\b', re.I)
        for section, para, ctx in out['_paras']:
            for m in pat.finditer(para):
                out['name'][key][m.group(0)].append((section, ctx))
    del out['_paras']
    return out


def source_keys(paths) -> dict:
    keys = {k: set() for k in ('figure', 'date', 'name', 'email', 'url')}
    for p in paths:
        got = collect(Path(p))
        for k in keys:
            keys[k] |= set(got[k])
    return keys


# --- set mode ---------------------------------------------------------------

def audit_set(paths: list, authority: str | None) -> dict:
    """Cross-check a family of related documents against each other.

    Three findings, and the third is the one that gets dropped:

      CONFLICT   one labelled field, different values, in different documents
      VARIANT    one value, written differently in different documents
      SINGLETON  a figure or date stated in exactly one document in the set

    SINGLETON is not a defect on its own — plenty of facts legitimately live in one
    place. It is reported because a set where every fact appears once produces an
    empty CONFLICT list, and an empty list reads as "consistent" when it actually
    means "nothing was cross-checkable". Those two must not look the same.
    """
    per_doc = {p: collect(Path(p)) for p in paths}
    auth = authority if authority in per_doc else None

    # Cross-document name rescan. collect() rescans each document for the names it
    # found in *that* document, which cannot see a variant that only exists elsewhere:
    # "Meridian Essential" in the manual and "Meridian essential" in the summary were
    # missed entirely, because PROPER needs a capital on every word and so never
    # matched the second form in the document where it appears. The union of names
    # across the whole set is the only thing that can catch it — which is the variant
    # this mode most needs to find.
    union = set()
    for t in per_doc.values():
        union |= set(t['name'])
    for p, t in per_doc.items():
        text = list(paragraphs(Path(p)))
        for key in sorted(union, key=len, reverse=True):
            if key in t['name']:
                continue
            pat = re.compile(r'\b' + r'[\s\-–—]+'.join(re.escape(w)
                                                       for w in key.split()) + r'\b', re.I)
            for para in text:
                for m in pat.finditer(para):
                    t['name'][key][m.group(0)].append(('(cross-set match)', para[:120]))

    # field -> canonical value -> [(doc, section, as written)]
    fields = defaultdict(lambda: defaultdict(list))
    names = defaultdict(lambda: defaultdict(list))
    figures = defaultdict(list)          # canonical -> [doc]
    dates = defaultdict(list)

    for doc, t in per_doc.items():
        for label, vals in t['field'].items():
            for v, occ in vals.items():
                for section, written in occ:
                    fields[label][v].append((doc, section, written))
        for key, forms in t['name'].items():
            for f, occ in forms.items():
                for section, _ in occ:
                    names[key][f].append((doc, section))
        for key in t['figure']:
            figures[key].append(doc)
        for key in t['date']:
            dates[key].append(doc)

    conflicts = []
    for label, vals in sorted(fields.items()):
        if len(vals) < 2:
            continue
        # Only a disagreement ACROSS documents is a set-level conflict. Two values in
        # one document is a within-document matter and draft mode's job.
        docs_per_value = {v: {d for d, _, _ in occ} for v, occ in vals.items()}
        if len({d for s in docs_per_value.values() for d in s}) < 2:
            continue
        entry = {'field': label,
                 'values': {v: sorted(f'{Path(d).name} · {s} ("{w}")'
                                      for d, s, w in occ)
                            for v, occ in vals.items()},
                 'direction': None}
        if auth:
            held = [v for v, docs in docs_per_value.items() if auth in docs]
            if len(held) == 1:
                others = sorted(Path(d).name for v, docs in docs_per_value.items()
                                if v != held[0] for d in docs if d != auth)
                entry['direction'] = (
                    f'{Path(auth).name} states {held[0]} — propose changing '
                    f'{", ".join(dict.fromkeys(others))} to match')
            elif len(held) > 1:
                entry['direction'] = (
                    f'ESCALATE — the authority document itself states more than one '
                    f'value for this field')
            else:
                entry['direction'] = (
                    f'ESCALATE — the authority document does not state this field, so '
                    f'no document in the set outranks the others on it')
        conflicts.append(entry)

    variants = []
    for key, forms in sorted(names.items()):
        if len(forms) < 2:
            continue
        if len({d for occ in forms.values() for d, _ in occ}) < 2:
            continue
        entry = {'refers_to': key,
                 'forms': {f: sorted({Path(d).name for d, _ in occ})
                           for f, occ in forms.items()},
                 'direction': None}
        if auth:
            used = [f for f, occ in forms.items() if any(d == auth for d, _ in occ)]
            if len(used) == 1:
                entry['direction'] = (f'{Path(auth).name} writes it "{used[0]}" — '
                                      f'propose that form everywhere')
        variants.append(entry)

    # Singletons are restricted to **labelled fields** stated in exactly one document,
    # and exclude anything already reported as a conflict.
    #
    # Reporting every unique figure and date instead produced eight findings across
    # three short documents, most of them each document's own version date — which is
    # correctly unique and tells the reader nothing. Labelled fields are the values
    # that were *supposed* to be cross-checkable, so a label appearing in one document
    # only is the finding worth having: "Onboarding window: 45 days, stated nowhere
    # else" is a gap; "Version 1.4 · 03 February 2025" is not.
    in_conflict = {c['field'] for c in conflicts}
    singletons = []
    for label, vals in sorted(fields.items()):
        if label in in_conflict:
            continue
        docs = {d for occ in vals.values() for d, _, _ in occ}
        if len(docs) == 1:
            v = sorted(vals)
            singletons.append({'kind': 'field', 'value': f'{label} = {", ".join(v)}',
                               'only_in': Path(next(iter(docs))).name})

    return {'documents': [Path(p).name for p in paths],
            'authority': Path(auth).name if auth else None,
            'conflicts': conflicts, 'variants': variants, 'singletons': singletons}


def report_set(res: dict) -> int:
    print(f'{len(res["documents"])} document(s): {", ".join(res["documents"])}')
    print(f'authority: {res["authority"] or "NONE GIVEN — findings carry no direction"}')
    print()

    if res['conflicts']:
        print(f'CONFLICT — {len(res["conflicts"])} field(s) disagree across the set:')
        for c in res['conflicts']:
            print(f'  "{c["field"]}"')
            for v, where in c['values'].items():
                print(f'      {v}')
                for w in where:
                    print(f'          {w}')
            print(f'      → {c["direction"] or "no authority given; a person must decide"}')
        print()
    else:
        print('No field-level disagreements found across the set.')
        print()

    if res['variants']:
        print(f'VARIANT — {len(res["variants"])} name(s) written differently '
              f'in different documents:')
        for v in res['variants']:
            print(f'  {v["refers_to"]}')
            for f, docs in v['forms'].items():
                print(f'      "{f}"  in: {", ".join(docs)}')
            if v['direction']:
                print(f'      → {v["direction"]}')
        print()

    if res['singletons']:
        print(f'UNVERIFIED — {len(res["singletons"])} fact(s) appear in exactly one '
              f'document, so nothing in the set can corroborate them:')
        for s in res['singletons'][:40]:
            print(f'  [{s["kind"]}] {s["value"]}  only in: {s["only_in"]}')
        if len(res['singletons']) > 40:
            print(f'  ... and {len(res["singletons"]) - 40} more (see --json)')
        print('\nThese are not defects. They are the part of the set this run could '
              'not check, and they must not be counted as clean.\n')

    if not res['authority']:
        print('INCOMPLETE  no --authority given. Disagreements were found but none '
              'carries a proposed direction, so none is actionable.')
        return 1
    return 1 if res['conflicts'] else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('draft', nargs='?')
    ap.add_argument('--set', nargs='*', dest='docset', default=[],
                    help='SET MODE: the family of related documents to cross-check '
                         'against each other.')
    ap.add_argument('--authority', default=None,
                    help='SET MODE: which document in --set outranks the others. '
                         'Without it, disagreements are reported with no proposed '
                         'direction and the run exits non-zero — an audit that cannot '
                         'say which document to change is not actionable.')
    ap.add_argument('--sources', nargs='*', default=[])
    ap.add_argument('--exempt', nargs='*', default=[],
                    help='Values this run authored rather than drew from a source — '
                         'the document date, the validity date, the version label. '
                         'They are by definition in no source document, so without '
                         'this they are reported as unsourced and bury the real '
                         'findings. Pass the surface forms exactly as written.')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()

    if a.docset:
        if a.draft:
            sys.exit('give either a DRAFT (draft mode) or --set (set mode), not both')
        if len(a.docset) < 2:
            sys.exit('--set needs at least two documents; one document has nothing to '
                     'be cross-checked against')
        res = audit_set(a.docset, a.authority)
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=2, sort_keys=True),
                                    encoding='utf-8')
        sys.exit(report_set(res))

    if not a.draft:
        sys.exit('give a DRAFT (draft mode) or --set (set mode)')

    draft = Path(a.draft)
    table = collect(draft)
    src = source_keys(a.sources) if a.sources else None

    report = {'draft': str(draft), 'sources': list(a.sources),
              'variants': [], 'unsourced': [], 'counts': {}}

    # Finding 1a — one value, written two ways. £5M and £5,000,000; "Apex Advisory"
    # and "Apex advisory". A proofreading matter, but the expensive kind.
    for kind in ('figure', 'date', 'name'):
        for key, forms in sorted(table[kind].items()):
            if len(forms) > 1:
                report['variants'].append({
                    'kind': kind, 'refers_to': key,
                    'forms': {f: sorted({s for s, _ in occ}) for f, occ in forms.items()},
                })

    # Finding 1b — one named field, two different values. This is the real
    # contradiction, and the labelled "Field: value" shape is the only one where it
    # can be established mechanically: elsewhere the document does not say what the
    # number refers to, so the units table below is offered for a reader instead.
    report['conflicts'] = []
    for label, vals in sorted(table['field'].items()):
        if len(vals) > 1:
            report['conflicts'].append({
                'field': label,
                'values': {v: sorted({f'{s} ("{w}")' for s, w in occ})
                           for v, occ in vals.items()},
            })

    report['units'] = [
        {'unit': u, 'values': {v: sorted({s for s, _ in occ}) for v, occ in vals.items()}}
        for u, vals in sorted(table['unit'].items()) if len(vals) > 1
    ]

    # Finding 2 — in the draft, in no source. Only meaningful with sources given.
    exempt = {norm_date(e) for e in a.exempt} | {e.strip().casefold() for e in a.exempt}
    report['exempt'] = list(a.exempt)
    if src is not None:
        for kind in ('figure', 'date'):
            for key, forms in sorted(table[kind].items()):
                if key in exempt or any(f.strip().casefold() in exempt
                                        or norm_date(f) in exempt for f in forms):
                    continue
                if key not in src[kind]:
                    report['unsourced'].append({
                        'kind': kind, 'value': key,
                        'as_written': sorted(forms),
                        'sections': sorted({s for occ in forms.values() for s, _ in occ}),
                    })

    report['counts'] = {k: len(v) for k, v in table.items()}

    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2, sort_keys=True),
                                encoding='utf-8')

    print(f'{draft.name}: ' + ', '.join(f'{v} distinct {k}s'
                                        for k, v in report['counts'].items() if v))
    print()

    if report['conflicts']:
        print(f'CONFLICT — {len(report["conflicts"])} field(s) given more than one value:')
        for c in report['conflicts']:
            print(f'  "{c["field"]}"')
            for val, where in c['values'].items():
                print(f'      {val}  in: {"; ".join(where)}')
        print('\nThese are contradictions, not variants. Take the value from the '
              'source; do not pick the one that reads better.\n')

    if report['variants']:
        print(f'VARIANT — {len(report["variants"])} item(s) written more than one way:')
        for v in report['variants']:
            print(f'  [{v["kind"]}] {v["refers_to"]}')
            for form, secs in v['forms'].items():
                print(f'      "{form}"  in: {"; ".join(secs)}')
        print()

    if report['units']:
        print(f'REVIEW — {len(report["units"])} unit(s) carry more than one value. '
              f'Some of these are correct (a before-and-after pair shares its unit); '
              f'read them, do not assume:')
        for u in report['units']:
            vals = ', '.join(f'{v} [{"; ".join(w)}]' for v, w in u['values'].items())
            print(f'  {u["unit"]}: {vals}')
        print()

    if not (report['conflicts'] or report['variants'] or report['units']):
        print('No contradictions and no repeated units across sections.')
        print()

    if src is None:
        print('NOT CHECKED  no --sources given, so nothing was verified against a '
              'source. Every figure in this draft is unverified.')
        print('\nConsistency table written.' if a.json else '')
        return 0

    if report['unsourced']:
        print(f'UNSOURCED — {len(report["unsourced"])} figure(s)/date(s) in the draft '
              f'appear in no supplied source:')
        for u in report['unsourced']:
            print(f'  [{u["kind"]}] {u["value"]}  as written: {", ".join(u["as_written"])}')
            print(f'      in: {"; ".join(u["sections"])}')
        print('\nEach of these was written rather than supplied. Report them to the '
              'owner and get a source, or remove the claim. Do not choose a value.')
        sys.exit(1)

    print('Every figure and date in the draft traces to a supplied source.')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
