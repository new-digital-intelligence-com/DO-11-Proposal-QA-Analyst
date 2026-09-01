#!/usr/bin/env python3
"""Find sections that have gone out of date, against declared rules.

    staleness.py --rules rules.yaml FILE [FILE ...] [--as-of YYYY-MM-DD] [--json OUT]

Rule-driven on purpose. "Which parts of this document are outdated?" cannot be answered
by reading the document — the answer lives in facts outside it: today's date, which
products were discontinued, what the company is called now, which policy superseded
which. So this script evaluates rules a person wrote, and reports what it could not
evaluate rather than inferring.

Four rule kinds, and nothing else:

  expiry      a date in the document that has passed, by pattern and label
  superseded  a term that has been replaced, with what replaced it
  retired     a term that should no longer appear at all, with what to do instead
  max_age     a document whose stated date is older than a permitted age

rules.yaml:

    as_of: 2026-09-01              # optional; --as-of overrides; today by default

    expiry:
      - label: "valid until"       # matched case-insensitively before the date
        severity: high
      - label: "price valid"
        severity: high

    superseded:
      - old: "Meridian Endpoint Care Basic"
        new: "Meridian Essential"
        since: 2026-06-01
        severity: high
      - old: "0800 555 0100"
        new: "0800 555 0199"
        severity: medium

    retired:
      - term: "NDI Digital GmbH"
        note: "renamed 2025-11; use New Digital Intelligence"
        severity: high

    max_age:
      months: 18
      severity: medium

Exits non-zero if any high-severity finding is present. Exits 2 if the rules file is
empty of rules — an empty rule set produces a clean report over any document, which is
the most misleading output this script could give.
"""
import argparse, json, re, sys, zipfile
from datetime import date
from pathlib import Path

import yaml

_WT = re.compile(r'<w:t(?:\s[^>]*)?>(.*?)</w:t>', re.S)
_PARA = re.compile(r'</w:p>')
_TAG = re.compile(r'<[^>]+>')

MONTHS = {m[:3].lower(): i for i, m in enumerate(
    'January February March April May June July August September October November '
    'December'.split(), 1)}

DATE = re.compile(
    r'\b(?P<d1>\d{1,2})[./-](?P<m1>\d{1,2})[./-](?P<y1>\d{2,4})\b'
    r'|\b(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2})\b'
    r'|\b(?P<d3>\d{1,2})\s+(?P<mn3>[A-Za-z]{3,9})\.?,?\s+(?P<y3>\d{4})\b'
    r'|\b(?P<mn4>[A-Za-z]{3,9})\.?\s+(?P<d4>\d{1,2}),?\s+(?P<y4>\d{4})\b'
)


def paragraphs(path: Path):
    if path.suffix.lower() in ('.docx', '.dotx'):
        with zipfile.ZipFile(path) as z:
            parts = [n for n in z.namelist() if re.fullmatch(
                r'word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml', n)]
            for n in sorted(parts):
                xml = z.read(n).decode('utf-8', 'replace')
                for chunk in _PARA.split(xml):
                    t = _TAG.sub('', ''.join(_WT.findall(chunk)))
                    t = (t.replace('&amp;', '&').replace('&lt;', '<')
                          .replace('&gt;', '>').replace('&quot;', '"')
                          .replace('&apos;', "'"))
                    if t.strip():
                        yield t.strip()
    else:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.strip():
                yield line.strip()


def parse_date(m) -> date | None:
    g = m.groupdict()
    try:
        if g['y1']:
            y = int(g['y1'])
            y += 2000 if y < 100 else 0
            # Ambiguous by design: 03/04/2026 is 3 April in most of Europe and
            # 4 March in the US. Treated as day-first, and flagged in the output so a
            # reader can see the assumption rather than discover it.
            return date(y, int(g['m1']), int(g['d1']))
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


def check(paths, rules: dict, as_of: date) -> dict:
    findings, ambiguous = [], []
    expiry = rules.get('expiry') or []
    superseded = rules.get('superseded') or []
    retired = rules.get('retired') or []
    max_age = rules.get('max_age') or {}

    age_label = str(max_age.get('label', '') or '').casefold()

    for p in paths:
        path = Path(p)
        name = path.name
        newest = None
        labelled_age_date = None
        for para in paragraphs(path):
            low = para.casefold()

            # The document's own version/issue date, when max_age names a label for it.
            # Without a label, max_age falls back to the newest date anywhere in the
            # file — which almost never fires, because a document with a future
            # validity date ("Valid until 31 December 2026") looks brand new by that
            # measure no matter how old its content is. That is how the first run of
            # this script passed a datasheet whose version date was 19 months old.
            if age_label and age_label in low:
                for m in DATE.finditer(para):
                    d = parse_date(m)
                    if d and (labelled_age_date is None or d > labelled_age_date):
                        labelled_age_date = d

            for rule in expiry:
                label = str(rule.get('label', '')).casefold()
                if not label or label not in low:
                    continue
                for m in DATE.finditer(para):
                    d = parse_date(m)
                    if d is None:
                        continue
                    if m.groupdict()['y1']:
                        ambiguous.append({'document': name, 'text': m.group(0),
                                          'read_as': d.isoformat(),
                                          'note': 'numeric date read day-first'})
                    if d < as_of:
                        findings.append({
                            'kind': 'expiry', 'severity': rule.get('severity', 'high'),
                            'document': name, 'where': para[:110],
                            'detail': f'"{rule["label"]}" gives {d.isoformat()}, '
                                      f'which passed {(as_of - d).days} days ago',
                            'propose': 'confirm the new date with the owner, or '
                                       'withdraw the document',
                        })

            for rule in superseded:
                old = str(rule.get('old', ''))
                if old and old.casefold() in low:
                    new = rule.get('new') or '(no replacement stated in the rules)'
                    findings.append({
                        'kind': 'superseded', 'severity': rule.get('severity', 'high'),
                        'document': name, 'where': para[:110],
                        'detail': f'"{old}" was superseded'
                                  + (f' on {rule["since"]}' if rule.get('since') else ''),
                        'propose': f'replace with "{new}"',
                    })

            for rule in retired:
                term = str(rule.get('term', ''))
                if term and term.casefold() in low:
                    findings.append({
                        'kind': 'retired', 'severity': rule.get('severity', 'high'),
                        'document': name, 'where': para[:110],
                        'detail': f'"{term}" should no longer appear'
                                  + (f' — {rule["note"]}' if rule.get('note') else ''),
                        'propose': 'remove or replace per the note',
                    })

            for m in DATE.finditer(para):
                d = parse_date(m)
                if d and (newest is None or d > newest):
                    newest = d

        if max_age.get('months'):
            basis = labelled_age_date or newest
            how = (f'its "{max_age["label"]}" date' if labelled_age_date
                   else 'the latest date anywhere in it')
            if basis:
                months = (as_of.year - basis.year) * 12 + (as_of.month - basis.month)
                if months > int(max_age['months']):
                    findings.append({
                        'kind': 'max_age', 'severity': max_age.get('severity', 'medium'),
                        'document': name, 'where': '(document as a whole)',
                        'detail': f'{how} is {basis.isoformat()}, {months} months old, '
                                  f'against a {max_age["months"]}-month limit',
                        'propose': 'review for currency, or confirm it is still valid',
                    })
                elif age_label and labelled_age_date is None:
                    findings.append({
                        'kind': 'unverified', 'severity': 'low', 'document': name,
                        'where': '(document as a whole)',
                        'detail': f'no date follows "{max_age["label"]}", so its age was '
                                  f'checked against the newest date anywhere instead — '
                                  f'a weaker test',
                        'propose': f'add a "{max_age["label"]}" date, or exempt this '
                                   f'document from the age rule',
                    })
            else:
                findings.append({
                    'kind': 'unverified', 'severity': 'low', 'document': name,
                    'where': '(document as a whole)',
                    'detail': 'no date found anywhere, so its age cannot be checked',
                    'propose': 'add a date, or exempt this document from the age rule',
                })

    order = {'high': 0, 'medium': 1, 'low': 2}
    findings.sort(key=lambda f: (order.get(f['severity'], 3), f['document']))
    return {'as_of': as_of.isoformat(), 'documents': [Path(p).name for p in paths],
            'rules_evaluated': {'expiry': len(expiry), 'superseded': len(superseded),
                                'retired': len(retired),
                                'max_age': bool(max_age.get('months'))},
            'findings': findings, 'ambiguous_dates': ambiguous}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--rules', required=True)
    ap.add_argument('--as-of', default=None)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()

    rules = yaml.safe_load(Path(a.rules).read_text(encoding='utf-8')) or {}
    as_of = (date.fromisoformat(a.as_of) if a.as_of
             else (date.fromisoformat(str(rules['as_of'])) if rules.get('as_of')
                   else date.today()))

    total = sum(len(rules.get(k) or []) for k in ('expiry', 'superseded', 'retired'))
    if not total and not (rules.get('max_age') or {}).get('months'):
        print('FAIL  the rules file declares no rules. Every document would pass, '
              'which reads as "nothing is out of date" rather than "nothing was '
              'checked".')
        sys.exit(2)

    res = check(a.files, rules, as_of)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2, sort_keys=True),
                                encoding='utf-8')

    r = res['rules_evaluated']
    print(f'as of {res["as_of"]} · {len(res["documents"])} document(s) · rules: '
          f'{r["expiry"]} expiry, {r["superseded"]} superseded, {r["retired"]} retired, '
          f'max_age {"on" if r["max_age"] else "off"}')
    print()

    if res['ambiguous_dates']:
        print(f'ASSUMPTION  {len(res["ambiguous_dates"])} numeric date(s) read '
              f'day-first (03/04/2026 = 3 April). Check these if the documents are '
              f'US-formatted:')
        for x in res['ambiguous_dates']:
            print(f'  {x["document"]}: "{x["text"]}" read as {x["read_as"]}')
        print()

    if not res['findings']:
        print('No stale content found against the declared rules. Note the scope: '
              'anything not covered by a rule above was not checked.')
        return

    for f in res['findings']:
        print(f'[{f["severity"].upper():6s}] {f["kind"]}  {f["document"]}')
        print(f'          {f["detail"]}')
        print(f'          in: {f["where"]}')
        print(f'          → {f["propose"]}')
    print()
    highs = sum(1 for f in res['findings'] if f['severity'] == 'high')
    print(f'{len(res["findings"])} finding(s), {highs} high. Nothing has been changed — '
          f'each fix needs approval.')
    if highs:
        sys.exit(1)


if __name__ == '__main__':
    main()
