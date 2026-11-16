#!/usr/bin/env python3
"""Independent retained-byte Gate3 audit; standard library only.

This program does not import the application's or validation_lab's parsers,
normalizers, arithmetic, source catalog, or verifier. The externally supplied
contract digest binds the selected corpus; it is not learned from input records.
A valid digest establishes byte identity, not publisher authenticity.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import sys
import zipfile

LABELS = (
    'Treasury General Account (TGA) Opening Balance',
    'Total TGA Deposits (Table II)',
    'Total TGA Withdrawals (Table II) (-)',
    'Treasury General Account (TGA) Closing Balance',
)
SEC_COLUMNS = ('SETTLEMENT DATE', 'CUSIP', 'SYMBOL', 'QUANTITY (FAILS)', 'DESCRIPTION', 'PRICE')
TRANSITION = '2022-04-18'


class AuditError(ValueError):
    """A selected corpus or semantic constraint was not satisfied."""


class InputUnavailable(AuditError):
    """A required original input is unavailable; no replacement is synthesized."""


def require(condition, message):
    if not condition:
        raise AuditError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(data):
    return json.loads(data, object_pairs_hook=no_duplicate_keys)


def bound_bytes(root, entry):
    relative = Path(entry['path'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe corpus path')
    path = root / relative
    if not path.exists():
        raise InputUnavailable(f'missing original raw input: {relative}')
    require(path.is_file() and not path.is_symlink(), f'nonregular raw input: {relative}')
    require(path.resolve().is_relative_to(root.resolve()), 'corpus path escaped root')
    require(path.stat().st_size == entry['bytes'], f'byte size changed: {relative}')
    raw = path.read_bytes()
    require(sha(raw) == entry['sha256'], f'raw digest changed: {relative}')
    return raw


def integer(text):
    require(isinstance(text, str) and re.fullmatch(r'-?(0|[1-9][0-9]*)', text) is not None,
            f'not an explicit integer amount: {text!r}')
    return int(text)


def modern_equation(rows, date):
    """Read precisely four Table I identities; NULL close column is deliberate."""
    require(date >= TRANSITION, 'modern mapping is not valid before transition')
    require(len(rows) == 4, 'modern day must contain exactly four rows')
    values, identities = [], []
    for line, label in enumerate(LABELS, 1):
        selected = [r for r in rows if r.get('src_line_nbr') == str(line)]
        require(len(selected) == 1, f'missing/duplicate source line {line}')
        row = selected[0]
        require(row.get('record_date') == date and row.get('table_nbr') == 'I'
                and row.get('table_nm') == 'Operating Cash Balance'
                and row.get('sub_table_name') == 'Cash Balance Details'
                and row.get('account_type') == label, f'wrong row identity at line {line}')
        require(row.get('close_today_bal') == 'null', 'incorrect post-transition close column')
        values.append(integer(row.get('open_today_bal')))
        identities.append([date, 'I', str(line), label, 'Cash Balance Details'])
    opening, deposits, withdrawals, closing = values
    require(min(values) >= 0, 'unexpected negative aggregate balance/flow')
    residual = opening + deposits - withdrawals - closing
    return {'record_date': date, 'opening': opening, 'deposits': deposits,
            'withdrawals': withdrawals, 'closing': closing, 'calculated_closing': opening + deposits - withdrawals,
            'residual_million_usd': residual, 'strict_equal': residual == 0,
            'research_only_within_two': abs(residual) <= 2, 'source_identities': identities}


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)

    def normalized_text(self):
        return ' '.join(' '.join(self.text).split())


def parse_sec_text(text, require_trailers=True):
    lines = text.splitlines()
    require(lines and tuple(lines[0].split('|')) == SEC_COLUMNS, 'SEC header mismatch')
    trailer = None
    if require_trailers:
        require(len(lines) >= 4, 'SEC missing financial rows/trailers')
        count = re.fullmatch(r'Trailer record count ([0-9]+)', lines[-2])
        quantity = re.fullmatch(r'Trailer total quantity of shares ([0-9]+)', lines[-1])
        require(count is not None and quantity is not None, 'SEC trailer format/order')
        trailer = [int(count.group(1)), int(quantity.group(1))]
        lines = lines[:-2]
    rows = list(csv.DictReader(lines, delimiter='|'))
    require(rows, 'empty SEC corpus')
    identities = [(r.get('SETTLEMENT DATE'), r.get('CUSIP')) for r in rows]
    issues, symbol_warnings, missing_price = [], [], 0
    for index, row in enumerate(rows, 2):
        problems = []
        if set(row) != set(SEC_COLUMNS) or None in row.values():
            problems.append('COLUMNS')
        try:
            require(re.fullmatch(r'[0-9]{8}', row.get('SETTLEMENT DATE', '')) is not None, 'date width')
            datetime.datetime.strptime(row['SETTLEMENT DATE'], '%Y%m%d')
        except (ValueError, TypeError):
            problems.append('DATE')
        if re.fullmatch(r'[A-Z0-9]{9}', row.get('CUSIP', '')) is None:
            problems.append('CUSIP')
        if re.fullmatch(r'[0-9]+', row.get('QUANTITY (FAILS)', '')) is None:
            problems.append('QUANTITY')
        if row.get('PRICE') == '.':
            missing_price += 1
        elif re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', row.get('PRICE', '')) is None:
            problems.append('PRICE')
        symbol = row.get('SYMBOL', '')
        if not 1 <= len(symbol) <= 10:
            symbol_warnings.append({'line': index, 'identity': list(identities[index - 2]), 'symbol': symbol})
        if problems:
            issues.append({'line': index, 'problems': problems})
    duplicates = [list(k) for k, count in collections.Counter(identities).items() if count != 1]
    if trailer is not None:
        require(trailer[0] == len(rows), 'SEC trailer row count mismatch')
        require(all('QUANTITY' not in x['problems'] for x in issues), 'SEC invalid quantity before trailer sum')
        require(trailer[1] == sum(int(r['QUANTITY (FAILS)']) for r in rows), 'SEC trailer quantity mismatch')
    return {'rows': rows, 'identities': identities, 'issues': issues, 'symbol_warnings': symbol_warnings,
            'missing_prices': missing_price, 'duplicates': duplicates, 'trailer': trailer}


def audit(root, contract):
    expected = contract['expected']
    entries = contract['files']
    paths = [e['path'] for e in entries]
    require(len(paths) == len(set(paths)) == 18, 'selected corpus inventory changed')
    raw = {e['path']: bound_bytes(root, e) for e in entries}
    documents = {}
    for entry in entries:
        if entry['kind'] == 'DOCUMENT':
            doc = Document()
            doc.feed(raw[entry['path']].decode())
            documents[Path(entry['path']).stem] = doc
    quotes = {
        'nearest_million': ('treasury-dts-documentation', 'All figures are rounded to the nearest million.'),
        'transition': ('treasury-dts-documentation', 'the closing balance today column values will be null from April 18, 2022 onwards'),
        'transition_mapping': ('treasury-dts-documentation', 'Please reference the TGA Closing Balance value within the Type of Account column to find the closing balance values within the opening balance columns.'),
        'treasury_rights': ('treasury-about', 'The data on this site is available to copy, adapt, redistribute, or otherwise use for non-commercial and commercial purposes.'),
        'sec_outstanding': ('sec-ftd-documentation', 'The values of total fails-to-deliver shares represent the aggregate net balance of shares that failed to be delivered as of a particular settlement date.'),
        'sec_not_daily': ('sec-ftd-documentation', 'The figure is not a daily amount of fails, but a combined figure that includes both new fails on the reporting day as well as existing fails.'),
        'sec_no_age': ('sec-ftd-documentation', 'the age of fails cannot be determined by looking at these numbers.'),
    }
    for key, (document, quote) in quotes.items():
        require(quote in documents[document].normalized_text(), f'official documentation quote absent: {key}')
    treasury = {}
    treasury_total, table_i_total, table_ii_total = 0, 0, 0
    for entry in entries:
        if entry['kind'] != 'TREASURY':
            continue
        payload = read_json(raw[entry['path']])
        rows = payload['data']
        require(len(rows) == entry['rows'] == payload['meta']['count'] == payload['meta']['total-count'], 'Treasury row count')
        require(payload['meta']['total-pages'] == 1, 'Treasury unexpected pagination')
        ids = [[r[k] for k in entry['identity_fields']] for r in rows]
        require(len({tuple(x) for x in ids}) == len(ids), 'duplicate Treasury identity')
        require(sha(canonical(ids)) == entry['ordered_identity_sha256'], 'Treasury ordered record IDs changed')
        treasury[(entry['period'], entry['table'])] = rows
        treasury_total += len(rows)
        if entry['table'] == 'operating_cash_balance':
            table_i_total += len(rows)
        else:
            table_ii_total += len(rows)
    days, legacy, flow_checks, periods = [], [], [], []
    for period in ('2019-01', '2022-04', '2024-01', '2025-01', '2026-11'):
        balance_rows = treasury[(period, 'operating_cash_balance')]
        transaction_rows = treasury[(period, 'deposits_withdrawals_operating_cash')]
        dates = sorted({r['record_date'] for r in balance_rows})
        require(set(dates) == {r['record_date'] for r in transaction_rows}, 'Table I/II dates differ')
        periods.append({'period': period, 'table_i_rows': len(balance_rows), 'table_ii_rows': len(transaction_rows), 'dates': dates})
        for date in dates:
            rows = [r for r in balance_rows if r['record_date'] == date]
            if date < TRANSITION:
                require(not any(r['account_type'] in LABELS for r in rows), 'unexpected modern row before transition')
                legacy.append({'record_date': date, 'status': 'NOT_RUN', 'reason': 'LEGACY_FOUR_TOTALS_ABSENT'})
                continue
            result = modern_equation(rows, date)
            days.append(result)
            for field, kind in [('deposits', 'Deposits'), ('withdrawals', 'Withdrawals')]:
                candidates = [r for r in transaction_rows if r['record_date'] == date
                              and r['account_type'] == 'Treasury General Account Total ' + kind
                              and r['transaction_type'] == kind and r['table_nbr'] == 'II']
                require(len(candidates) == 1, f'missing/duplicate Table II total {date} {kind}')
                row = candidates[0]
                value = integer(row['transaction_today_amt'])
                require(value == result[field], f'Table I/II mismatch {date} {kind}')
                flow_checks.append({'record_date': date, 'field': field, 'source_line': row['src_line_nbr'], 'amount': value})
    counts = {str(k): v for k, v in sorted(collections.Counter(x['residual_million_usd'] for x in days).items())}
    require(treasury_total == expected['treasury_rows'] and table_i_total == expected['table_i_rows'] and table_ii_total == expected['table_ii_rows'], 'Treasury totals')
    require(len(days) == expected['modern_days'] and len(legacy) == expected['legacy_not_run'] and len(days) + len(legacy) == expected['days'], 'day inventory')
    require(counts == expected['residual_counts'] and sum(d['strict_equal'] for d in days) == expected['strict_exact'], 'arithmetic differs from historical observations')
    require(len(flow_checks) == expected['flow_checks'], 'flow inventory')
    historical = read_json(raw['analysis-02/results/direct-days.json'])
    require(len(historical) == len(days) + len(legacy) and len({r['record_date'] for r in historical}) == len(historical), 'historical direct roster')
    for day in days:
        old = next(x for x in historical if x['record_date'] == day['record_date'])
        for field in ('opening', 'deposits', 'withdrawals', 'closing', 'residual_million_usd'):
            require(old[field] == day[field], f'historical arithmetic mismatch {day["record_date"]} {field}')
    sample = contract['selected_example']
    sample_payload = read_json(raw[sample['path']])['data']
    selected = [sample_payload[int(pointer.rsplit('/', 1)[1])] for pointer in sample['pointers']]
    require([r['src_line_nbr'] for r in selected] == sample['source_lines'], 'sample source lines')
    require([r['open_today_bal'] for r in selected] == sample['open_today_bal'], 'sample literal amounts')
    require([r['close_today_bal'] for r in selected] == sample['close_today_bal'], 'sample transition column')
    require(all(r['record_date'] == sample['date'] for r in selected), 'sample date')
    residual_oracle_results = []
    for case in contract['research_residual_oracle']:
        changed = [dict(r) for r in selected]
        changed[3]['open_today_bal'] = str(case['closing'])
        result = modern_equation(changed, sample['date'])
        require(result['residual_million_usd'] == case['residual']
                and result['strict_equal'] == case['strict_equal']
                and result['research_only_within_two'] == case['within_two'], 'independent literal residual oracle')
        residual_oracle_results.append({'classification': 'REAL_PLUS_SYNTHETIC_INJECTION_RESEARCH_BOUNDARY', **case, 'actual': result['residual_million_usd']})
    sec, source_rows = [], {}
    for entry in entries:
        if entry['kind'] != 'SEC':
            continue
        url = entry['url']
        href = '/' + url.split('sec.gov/', 1)[1]
        require(url in documents['sec-ftd-documentation'].links or href in documents['sec-ftd-documentation'].links, 'SEC exact ZIP link absent from original official landing page')
        with zipfile.ZipFile(io.BytesIO(raw[entry['path']])) as archive:
            require(archive.namelist() == [entry['member']], 'SEC unexpected ZIP member')
            info = archive.infolist()[0]
            require(not info.is_dir() and info.file_size < 10_000_000 and '/' not in info.filename, 'SEC unsafe/big member')
            body = archive.read(info)
        parsed = parse_sec_text(body.decode('utf-8-sig'))
        require(len(parsed['rows']) == entry['rows'], 'SEC row count')
        require(sha(canonical(parsed['identities'])) == entry['ordered_identity_sha256'], 'SEC ordered identities changed')
        require(not parsed['issues'] and not parsed['duplicates'], 'SEC invalid rows or duplicate security identity')
        for row in parsed['rows']:
            source_rows[(entry['sha256'], row['SETTLEMENT DATE'], row['CUSIP'])] = row
        sec.append({'path': entry['path'], 'sha256': entry['sha256'], 'zip_member': entry['member'],
                    'rows': len(parsed['rows']), 'missing_prices': parsed['missing_prices'],
                    'symbol_warnings': parsed['symbol_warnings'], 'trailer': parsed['trailer'],
                    'duplicates': parsed['duplicates'], 'official_link': url})
    require(sum(s['rows'] for s in sec) == expected['sec_rows'], 'SEC row total')
    require(sum(s['missing_prices'] for s in sec) == expected['sec_missing_prices'], 'SEC missing price total')
    require(sum(len(s['symbol_warnings']) for s in sec) == expected['sec_symbol_warnings'], 'SEC symbol exception total')
    injections = read_json(raw['analysis-02/results/ftd-injections.json'])
    require(len(injections) == expected['injection_cases'] and len({c['case_id'] for c in injections}) == len(injections), 'injection case roster')
    confusion = collections.Counter({'TP': 0, 'FP': 0, 'TN': 0, 'FN': 0})
    origins, family_counts = set(), collections.Counter()
    for case in injections:
        original = case['original_row']
        key = (case['source_file']['sha256'], original['SETTLEMENT DATE'], original['CUSIP'])
        require(key in source_rows and source_rows[key] == original, 'injection original source identity/row changed')
        origins.add(key)
        family_counts[case['family']] += 1
        require(sha(case['input'].encode()) == case['input_sha256'], 'injection input hash')
        parsed = parse_sec_text(case['input'], require_trailers=False)
        detected = bool(parsed['issues'] or parsed['duplicates'] or parsed['symbol_warnings'])
        label = ('TP' if detected else 'FN') if case['injected'] else ('FP' if detected else 'TN')
        require(case['detected'] == detected and case['classification'] == label, 'independent injection classification mismatch')
        confusion[label] += 1
    require(len(origins) == expected['injection_distinct_source_rows'] and dict(confusion) == expected['injection_confusion'], 'injection denominators')
    require(set(family_counts.values()) == {60} and len(family_counts) == 6, 'injection family inventory')
    return {'format': 'gate3-independent-public-audit-v1', 'status': 'PASS', 'data_class': 'REAL_PUBLIC_DIRECT',
            'treasury': {'rows': treasury_total, 'table_i_rows': table_i_total, 'table_ii_rows': table_ii_total,
                         'periods': periods, 'modern_days': days, 'strict_exact': sum(x['strict_equal'] for x in days),
                         'residual_counts': counts, 'legacy_not_run': legacy, 'flow_checks': flow_checks},
            'sec': sec, 'injections': {'data_class': 'REAL_PLUS_SYNTHETIC_INJECTION', 'cases': len(injections),
                                     'distinct_source_rows': len(origins), 'source_identities': [list(x) for x in sorted(origins)],
                                     'confusion': dict(confusion), 'families': dict(family_counts), 'natural_precision_recall': 'NOT_MEASURABLE'},
            'research_residual_boundaries': residual_oracle_results,
            'documentation_quotes': {k: {'document': v[0], 'verbatim_quote': v[1]} for k, v in quotes.items()},
            'input_proofs': [{'path': e['path'], 'bytes': e['bytes'], 'sha256': e['sha256']} for e in entries],
            'dependencies': {'imports_production_or_research_helpers': False, 'overlap': 'Python standard library; same publisher bytes and externally selected corpus. No independent publisher capture or institution truth.'},
            'claims': {'REAL_PUBLIC_ADAPTED': 'Historical authored single-source construction; zero independent counterparties.',
                       'publication_vintage': 'UNKNOWN', 'operational_tolerance_approval': 'NOT_AVAILABLE',
                       'natural_error_ground_truth': 'NOT_AVAILABLE', 'raw_sec_redistribution_permission': 'NOT_VERIFIED'},
            'limitations': contract['assurance_limits']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--expected-contract-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.output.exists(), 'output must be new; preserve prior attempts')
    blob = args.contract.read_bytes()
    require(sha(blob) == args.expected_contract_sha256, 'externally chosen contract digest mismatch')
    contract = read_json(blob)
    try:
        result = audit(args.raw_root, contract)
    except InputUnavailable as error:
        result = {'format': 'gate3-independent-public-audit-v1', 'status': 'NOT_RUN', 'reason': str(error)}
    result['contract'] = {'sha256': sha(blob), 'path': str(args.contract), 'bytes': len(blob)}
    result['execution'] = {'argv': sys.argv, 'interpreter': sys.executable, 'version': sys.version,
                           'script': str(Path(__file__).resolve()), 'script_sha256': sha(Path(__file__).read_bytes()),
                           'cwd': str(Path.cwd()), 'imports': {name: str(module.__file__) for name, module in sorted(sys.modules.items()) if getattr(module, '__file__', None)}}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'output': str(args.output)}))
    if result['status'] == 'NOT_RUN':
        raise SystemExit(3)


if __name__ == '__main__':
    main()
