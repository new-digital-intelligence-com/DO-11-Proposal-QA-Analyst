#!/usr/bin/env python3
"""Append-only record of what was audited, when, and what came of it.

    audit_log.py --path STORE status  --set NAME
    audit_log.py --path STORE record  --set NAME --documents N --findings N \
                     --applied N [--declined N] [--unverified N] [--note TEXT]
    audit_log.py --path STORE dismiss --set NAME --finding KEY --reason TEXT
    audit_log.py --path STORE hash    FILE [FILE ...]

Why an audit needs a memory at all: the second run of any audit re-finds everything the
first run found and nobody fixed. Without a record of what was already raised and
dismissed, every run's report is the same report, and a report that never changes stops
being read — which is the failure mode of every consistency process that has ever been
abandoned.

`dismiss` is therefore not a convenience. A finding a person looked at and decided not to
act on is a *decision*, and it belongs in the log next to the fixes. `status` prints
dismissals so the next run can separate "new" from "raised and declined in March".

Append-only, one JSONL file per audited set. Never rewrites a line: a log that can be
edited is a log that can be made to agree with whatever the last run wanted to say.
"""
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path


def is_store(p: Path) -> bool:
    """A directory, or a path that looks like one. Mirrors sync_index.py so the two
    behave the same when a pack points them at a folder rather than a file."""
    return p.is_dir() or (not p.suffix and not p.exists()) or str(p).endswith('/')


def set_file(path: Path, name: str) -> Path:
    if not is_store(path):
        return path
    path.mkdir(parents=True, exist_ok=True)
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in name)
    return path / f'{safe}.jsonl'


def read(fp: Path) -> list:
    if not fp.exists():
        return []
    out = []
    for i, line in enumerate(fp.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # One corrupt line must not hide the rest of the history.
            out.append({'_unreadable': line[:120], '_line': i})
    return out


def append(fp: Path, rec: dict) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    rec['at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with fp.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, sort_keys=True) + '\n')


def file_hash(paths) -> dict:
    out = {}
    for p in paths:
        h = hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
        out[Path(p).name] = h
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=False, default='audit-log')
    sub = ap.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('status'); s.add_argument('--set', required=True, dest='name')
    r = sub.add_parser('record')
    r.add_argument('--set', required=True, dest='name')
    r.add_argument('--documents', type=int, required=True)
    r.add_argument('--findings', type=int, required=True)
    r.add_argument('--applied', type=int, required=True)
    r.add_argument('--declined', type=int, default=0)
    r.add_argument('--unverified', type=int, default=0)
    r.add_argument('--state', default=None, help='hash of the set at audit time')
    r.add_argument('--note', default='')
    d = sub.add_parser('dismiss')
    d.add_argument('--set', required=True, dest='name')
    d.add_argument('--finding', required=True)
    d.add_argument('--reason', required=True)
    d.add_argument('--by', default=None)
    # A waiver is not a dismissal. Dismissing says "this is not a finding after all";
    # waiving says "this IS a finding and we are shipping anyway". The second needs a
    # named person against it, because it transfers the risk to them — which is the
    # entire mechanism by which a quality gate survives deadline pressure.
    w = sub.add_parser('waive')
    w.add_argument('--set', required=True, dest='name')
    w.add_argument('--finding', required=True)
    w.add_argument('--by', required=True,
                   help='The named person accepting the risk. Not a role, not "the '
                        'team" — a person.')
    w.add_argument('--reason', required=True)
    h = sub.add_parser('hash'); h.add_argument('files', nargs='+')
    a = ap.parse_args()

    if a.cmd == 'hash':
        print(json.dumps(file_hash(a.files), indent=2, sort_keys=True))
        return

    fp = set_file(Path(a.path), a.name)

    if a.cmd == 'status':
        recs = read(fp)
        if not recs:
            print(json.dumps({'set': a.name, 'file': str(fp), 'runs': 0,
                              'first_audit': True,
                              'note': 'no history — this is a first audit, so every '
                                      'finding is new and none can be compared against '
                                      'a previous run'}, indent=2))
            return
        runs = [x for x in recs if x.get('kind') == 'run']
        dismissed = [x for x in recs if x.get('kind') == 'dismiss']
        waived = [x for x in recs if x.get('kind') == 'waive']
        print(json.dumps({
            'set': a.name, 'file': str(fp), 'runs': len(runs),
            'last_run': runs[-1] if runs else None,
            'dismissed_findings': [
                {'finding': x['finding'], 'reason': x['reason'],
                 'by': x.get('by'), 'at': x['at']}
                for x in dismissed],
            # Listed separately and never merged with dismissals. A waived blocker is
            # an open defect that was shipped; on the next run it is still a finding,
            # and the log's job is to say who owns it.
            'waived_blockers': [
                {'finding': x['finding'], 'by': x['by'], 'reason': x['reason'],
                 'at': x['at']} for x in waived],
            'unreadable_lines': [x for x in recs if '_unreadable' in x],
        }, indent=2, sort_keys=True))
        return

    if a.cmd == 'record':
        if a.findings and a.applied + a.declined > a.findings:
            sys.exit(f'applied ({a.applied}) + declined ({a.declined}) exceeds findings '
                     f'({a.findings}) — the numbers do not describe one run')
        append(fp, {'kind': 'run', 'set': a.name, 'documents': a.documents,
                    'findings': a.findings, 'applied': a.applied,
                    'declined': a.declined, 'unverified': a.unverified,
                    'state': a.state, 'note': a.note})
        print(json.dumps({'recorded': str(fp), 'set': a.name,
                          'findings': a.findings, 'applied': a.applied}, indent=2))
        return

    if a.cmd == 'dismiss':
        append(fp, {'kind': 'dismiss', 'set': a.name, 'finding': a.finding,
                    'reason': a.reason, 'by': a.by})
        print(json.dumps({'dismissed': a.finding, 'file': str(fp)}, indent=2))
        return

    if a.cmd == 'waive':
        generic = {'the team', 'management', 'the director', 'sales', 'us', 'we',
                   'tbd', 'n/a', 'na', '-', 'someone'}
        if a.by.strip().casefold() in generic:
            sys.exit(f'--by "{a.by}" is a role or a group, not a person. A waiver that '
                     f'names nobody transfers the risk to nobody, which is the same as '
                     f'no waiver at all.')
        append(fp, {'kind': 'waive', 'set': a.name, 'finding': a.finding,
                    'by': a.by, 'reason': a.reason})
        print(json.dumps({'waived': a.finding, 'by': a.by, 'file': str(fp),
                          'note': 'This blocker remains an open defect. It will be '
                                  'reported again on the next run, attributed to '
                                  f'{a.by}.'}, indent=2))


if __name__ == '__main__':
    main()
