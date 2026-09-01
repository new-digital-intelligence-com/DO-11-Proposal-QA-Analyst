#!/usr/bin/env python3
"""Check that stated totals equal their columns and that dated milestones cohere.

    totals_and_dates.py FILE [FILE ...] [--as-of YYYY-MM-DD] [--json OUT.json]

The mechanical half of a document review. Two questions a reader cannot be expected to
answer by eye, and which are wrong in real documents often enough to be worth a script:

  1. **Does a row labelled Total actually equal the column above it?** A pricing table
     whose total is right and whose payment schedule sums to something else is the
     classic pre-submission defect — a figure the client will add up themselves.

  2. **Do the dated milestones make sense in order?** A phase that ends before it
     starts, a milestone before the contract date, a schedule whose last date is in the
     past. Date arithmetic is exactly the kind of thing that survives four human reviews.

It reports arithmetic, not judgement. A mismatch is stated with both numbers and the
difference; nothing is corrected, and no missing figure is inferred. A table it cannot
parse is reported as unchecked rather than skipped, because "no findings" and "not
looked at" must not produce the same output.

In core/scripts: any employee reviewing a document with money or dates in it needs this,
and none of them owns it.
"""
import argparse, json, re, sys, zipfile
from datetime import date
from pathlib import Path

from defusedxml import minidom

CURRENCY = '£$€¥'
NUM = re.compile(rf'^[\s{CURRENCY}]*'
                 r'(?P<neg>\()?'
                 r'(?P<val>\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)'
                 r'\)?'
                 r'\s*(?P<pct>%)?\s*$')

TOTAL_WORDS = ('total', 'sum', 'subtotal', 'sub-total', 'grand total', 'summe',
               'gesamt', 'tcv', 'total contract value')

MONTHS = {m[:3].lower(): i for i, m in enumerate(
    'January February March April May June July August September October November '
    'December'.split(), 1)}

DATE = re.compile(
    r'\b(?P<d1>\d{1,2})[./-](?P<m1>\d{1,2})[./-](?P<y1>\d{2,4})\b'
    r'|\b(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2})\b'
    r'|\b(?P<d3>\d{1,2})\s+(?P<mn3>[A-Za-z]{3,9})\.?,?\s+(?P<y3>\d{4})\b'
    r'|\b(?P<mn4>[A-Za-z]{3,9})\.?\s+(?P<d4>\d{1,2}),?\s+(?P<y4>\d{4})\b'
)

START = ('start', 'begin', 'commence', 'from', 'kickoff', 'kick-off', 'effective')
END = ('end', 'finish', 'complete', 'completion', 'until', 'to', 'delivery', 'go-live',
       'golive', 'handover', 'close')


def parse_date(m) -> date | None:
    g = m.groupdict()
    try:
        if g['y1']:
            y = int(g['y1']); y += 2000 if y < 100 else 0
            return date(y, int(g['m1']), int(g['d1']))       # day-first; flagged below
        if g['y2']:
            return date(int(g['y2']), int(g['m2']), int(g['d2']))
        if g['y3']:
            mo = MONTHS.get(g['mn3'][:3].lower())
            return date(int(g['y3']), mo, int(g['d3'])) if mo else None
        if g['y4']:
            mo = MONTHS.get(g['mn4'][:3].lower())
            return date(int(g['y4']), mo, int(g['d4'])) if mo else None
    except (ValueError, TypeError):
        return None
    return None


def to_number(text: str) -> float | None:
    """Parse a cell as a number, handling both decimal conventions.

    '1.234,56' and '1,234.56' are the same amount written two ways, and a document
    written by two people contains both. Deciding by which separator comes last is the
    only rule that gets both right without being told the locale.
    """
    m = NUM.match(text.strip())
    if not m:
        return None
    raw = m.group('val')
    last_comma, last_dot = raw.rfind(','), raw.rfind('.')
    if last_comma > last_dot:
        raw = raw.replace('.', '').replace(' ', '').replace(',', '.')
    else:
        raw = raw.replace(',', '').replace(' ', '')
    try:
        v = float(raw)
    except ValueError:
        return None
    return -v if m.group('neg') else v


def cell_text(tc) -> str:
    return ' '.join(t.firstChild.nodeValue or ''
                    for t in tc.getElementsByTagName('w:t') if t.firstChild).strip()


def docx_tables(path: Path):
    """Every table as a list of rows of cell strings, plus unparseable ones counted."""
    with zipfile.ZipFile(path) as z:
        dom = minidom.parseString(z.read('word/document.xml').decode('utf-8', 'replace'))
    out = []
    for tbl in dom.getElementsByTagName('w:tbl'):
        rows = []
        for tr in tbl.getElementsByTagName('w:tr'):
            # Only direct cells — a nested table's cells would otherwise be read as
            # belonging to the outer row and shift every column.
            cells = [tc for tc in tr.getElementsByTagName('w:tc')
                     if tc.parentNode is tr]
            rows.append([cell_text(tc) for tc in cells])
        if rows:
            out.append(rows)
    return out


def docx_paragraphs(path: Path):
    with zipfile.ZipFile(path) as z:
        xml = z.read('word/document.xml').decode('utf-8', 'replace')
    for chunk in re.split(r'</w:p>', xml):
        t = re.sub(r'<[^>]+>', '', ''.join(
            re.findall(r'<w:t(?:\s[^>]*)?>(.*?)</w:t>', chunk, re.S)))
        t = (t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
              .replace('&quot;', '"').replace('&apos;', "'"))
        if t.strip():
            yield t.strip()


def check_tables(path: Path, tol: float = 0.01) -> tuple:
    """Findings, cross-table total observations, and a count of unchecked tables.

    Two different things are looked for, and they carry different weight:

      - a total that disagrees with its own column: arithmetic, always wrong
      - the same total label carrying different values in different tables: possibly
        wrong, possibly a per-section subtotal doing its job

    The second cannot be decided by the script, but it must not be silent either — a
    pricing table totalling 412,300 and a payment schedule totalling 230,900 is the
    single most common pre-submission defect there is, and both tables add up
    perfectly on their own. Reported as an observation for a reviewer, not a finding.
    """
    findings, unchecked, stated_totals = [], 0, []
    for ti, rows in enumerate(docx_tables(path), 1):
        width = max(len(r) for r in rows)
        total_rows = [i for i, r in enumerate(rows)
                      if r and any(w in (r[0] or '').casefold() for w in TOTAL_WORDS)]
        if not total_rows:
            unchecked += 1
            continue
        for tr in total_rows:
            label = rows[tr][0]
            for col in range(1, width):
                stated = to_number(rows[tr][col]) if col < len(rows[tr]) else None
                if stated is None:
                    continue
                stated_totals.append({'label': re.sub(r'\s+', ' ', label).strip(),
                                      'value': stated, 'table': ti, 'column': col + 1})
                above = []
                for i in range(tr):
                    if col >= len(rows[i]):
                        continue
                    # A row that is itself a total must not be added into a grand
                    # total, or every table with a subtotal reports a false mismatch.
                    if any(w in (rows[i][0] or '').casefold() for w in TOTAL_WORDS):
                        continue
                    v = to_number(rows[i][col])
                    if v is not None:
                        above.append(v)
                if len(above) < 2:
                    continue
                got = round(sum(above), 2)
                if abs(got - stated) > tol:
                    findings.append({
                        'kind': 'total_mismatch', 'document': path.name,
                        'where': f'table {ti}, row "{label}", column {col + 1}',
                        'detail': f'stated {stated:,.2f} but the {len(above)} values '
                                  f'above it sum to {got:,.2f} — a difference of '
                                  f'{stated - got:,.2f}',
                        'propose': 'recheck the column; the stated total and the '
                                   'lines do not agree',
                    })

    # Same total label, different values, in different tables.
    by_label = {}
    for t in stated_totals:
        by_label.setdefault(t['label'].casefold(), []).append(t)
    observations = []
    for label, items in sorted(by_label.items()):
        vals = {round(i['value'], 2) for i in items}
        if len(vals) > 1 and len({i['table'] for i in items}) > 1:
            observations.append({
                'label': items[0]['label'],
                'values': [{'value': i['value'], 'table': i['table']} for i in items],
            })
    return findings, unchecked, observations


def check_dates(path: Path, as_of: date | None) -> tuple:
    findings, ambiguous, seen = [], [], []
    for para in docx_paragraphs(path):
        low = para.casefold()
        for m in DATE.finditer(para):
            d = parse_date(m)
            if d is None:
                continue
            if m.groupdict()['y1']:
                ambiguous.append({'document': path.name, 'text': m.group(0),
                                  'read_as': d.isoformat()})
            role = ('start' if any(w in low for w in START) else
                    'end' if any(w in low for w in END) else None)
            seen.append({'date': d, 'role': role, 'where': para[:110]})

        # A start and an end in the same paragraph is the pair worth checking.
        ds = [parse_date(m) for m in DATE.finditer(para)]
        ds = [d for d in ds if d]
        if len(ds) == 2 and any(w in low for w in START) and any(w in low for w in END):
            if ds[1] < ds[0]:
                findings.append({
                    'kind': 'date_order', 'document': path.name,
                    'where': para[:110],
                    'detail': f'ends {ds[1].isoformat()}, before it starts '
                              f'{ds[0].isoformat()}',
                    'propose': 'correct one of the two dates',
                })

    if as_of and seen:
        future = [s for s in seen if s['date'] >= as_of]
        if not future:
            latest = max(seen, key=lambda s: s['date'])
            findings.append({
                'kind': 'all_dates_past', 'document': path.name,
                'where': latest['where'],
                'detail': f'every date in the document is before {as_of.isoformat()}; '
                          f'the latest is {latest["date"].isoformat()}',
                'propose': 'confirm the schedule is still the one being offered',
            })
    return findings, ambiguous


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--as-of', default=None)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()

    as_of = date.fromisoformat(a.as_of) if a.as_of else None
    findings, ambiguous, unreadable, unchecked, observations = [], [], [], 0, []

    for p in a.files:
        path = Path(p)
        if path.suffix.lower() not in ('.docx', '.dotx'):
            unreadable.append({'document': path.name,
                               'why': f'{path.suffix or "no extension"} is not read by '
                                      f'this check — tables and dates are read from '
                                      f'.docx only'})
            continue
        try:
            tf, unc, obs = check_tables(path)
            df, amb = check_dates(path, as_of)
        except Exception as e:
            unreadable.append({'document': path.name, 'why': f'{type(e).__name__}: {e}'})
            continue
        findings += tf + df
        ambiguous += amb
        unchecked += unc
        for o in obs:
            o['document'] = path.name
        observations += obs

    res = {'findings': findings, 'ambiguous_dates': ambiguous,
           'cross_table_totals': observations,
           'unreadable': unreadable, 'tables_without_a_total': unchecked}
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2, sort_keys=True),
                                encoding='utf-8')

    if unreadable:
        print(f'NOT CHECKED  {len(unreadable)} document(s):')
        for u in unreadable:
            print(f'  {u["document"]}: {u["why"]}')
        print()

    if ambiguous:
        print(f'ASSUMPTION  {len(ambiguous)} numeric date(s) read day-first '
              f'(03/04/2026 = 3 April):')
        for x in ambiguous:
            print(f'  {x["document"]}: "{x["text"]}" → {x["read_as"]}')
        print()

    if unchecked:
        print(f'COVERAGE  {unchecked} table(s) had no row labelled as a total, so '
              f'nothing in them could be recomputed.')
        print()

    if observations:
        print(f'REVIEW  {len(observations)} total label(s) carry different values in '
              f'different tables. Decide whether they are supposed to agree — a '
              f'per-section subtotal legitimately differs; a payment schedule that '
              f'does not sum to the contract value does not:')
        for o in observations:
            vals = ', '.join(f'{v["value"]:,.2f} (table {v["table"]})'
                             for v in o['values'])
            print(f'  {o["document"]}  "{o["label"]}": {vals}')
        print()

    if not findings:
        print('Arithmetic checks passed: every stated total agrees with its column, '
              'and no date sequence is contradictory.')
        if observations:
            print('The REVIEW items above still need a human decision.')
        return

    for f in findings:
        print(f'[{f["kind"]}]  {f["document"]}')
        print(f'    {f["detail"]}')
        print(f'    in: {f["where"]}')
        print(f'    → {f["propose"]}')
    print(f'\n{len(findings)} arithmetic finding(s). Nothing has been changed.')
    sys.exit(1)


if __name__ == '__main__':
    main()
