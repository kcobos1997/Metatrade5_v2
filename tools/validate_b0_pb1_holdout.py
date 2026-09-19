"""Frozen Phase 3 temporal validation. Offline, standard library, no trading."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / 'docs/research/B0_PB1_TEMPORAL_VALIDATION_PROTOCOL.md'
START_NY = '2026-08-15T00:00:00-04:00'
END_NY = '2026-11-01T00:00:00-04:00'
START_UTC = datetime.fromisoformat(START_NY).astimezone(timezone.utc)
END_UTC = datetime.fromisoformat(END_NY).astimezone(timezone.utc)
FROZEN_SHA256 = {
    'XAUUSD_Intraday_Signal_Scanner.mq5': 'd7fc26b645f3f18b9b6f570f46672794fe877f95be21021fea5a9d7b985095ec',
    'XAUUSD_Intraday_Signal_Scanner.ex5': 'ac85ea60579d767ede143d320880db49f2038fe3e2848c694170241c5241eadd',
    'tools/analyze_scanner.py': 'b3637d1a8e03a73c7233d8fddf8cd4a2e09737847b51102b0e588120c9b20751',
    'tools/analyze_signal_outcomes.py': '22c22d36b33c3eb18d9881a5f0119d83c9374eab32f4898c37878e5c82afbb11',
    'tools/analyze_signal_robustness.py': '88d3d6ea109b3ce14ebe3e1350ef0b6d60a1dcbd627992584758d5c4f6f453cc',
}
# Read only from the discovery run's configuration, not its outcomes.
# Deliberately NOT extended by assuming the broker stays at UTC+3.
BROKER_SCHEDULE = '2026.06.01 00:00|2026.09.01 00:00|180'
POLICY = {
    'version': 'B0_PB1_TEMPORAL_V1', 'timezone': 'America/New_York',
    'start_inclusive': START_NY, 'end_exclusive': END_NY,
    'module': 'B0+PB1', 'directions': ['BUY', 'SELL'],
    'primary_minutes': 60, 'secondary_minutes': 120,
    'point_size': '0.01', 'spread_model': 'ENTRY_SPREAD_CONSTANT',
    'spread_factors': ['1.00', '2.00'], 'bootstrap_reps': 2000,
    'permutations': 10000, 'seed': 20260919, 'alpha': 0.05,
    'minimum_signals': 20, 'minimum_ny_days': 10,
    'scanner_parameters': [50, 3, 3, 2, 8, 12],
    'trim_each_tail': 'floor(N/10)', 'multiplicity': 'single primary; no Holm',
}
OUTPUT_NAMES = ('holdout_summary.csv', 'holdout_signals.csv', 'holdout_manifest.json')
SUMMARY_COLUMNS = ('horizon_minutes', 'role', 'spread_factor', 'subset', 'metric',
    'n_total', 'n_complete', 'n_days', 'mean', 'median', 'p25', 'p75',
    'positive_proportion', 'trimmed_mean_10', 'winsorized_mean_10',
    'trim_each_tail_n', 'bootstrap_low95', 'bootstrap_high95',
    'loo_mean_min', 'loo_mean_max', 'most_influential_id', 'permutation_p_one_sided')
SIGNAL_COLUMNS = ('sample_id', 'module', 'direction', 'day', 'decision_server',
    'horizon_minutes', 'spread_factor', 'status', 'missing_timestamps',
    'first_bar_open', 'last_bar_open', 'end_exclusive', 'bar_count',
    'entry_bid', 'entry_ask', 'scenario_ask', 'close_return_points',
    'inverse_close_return_points', 'paired_delta_points', 'mfe_points', 'mae_points',
    'nonoverlap_first', 'nonoverlap_last')


class HoldoutError(ValueError):
    """Invalid input/protocol or unopened temporal lock; no statistical verdict."""


def require(condition, message):
    if not condition:
        raise HoldoutError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def utc_now():
    return datetime.now(timezone.utc)


def check_window(start=START_NY, end=END_NY):
    # Exact strings intentionally prevent alternate windows or timezone assumptions.
    require(start == START_NY and end == END_NY,
            'FROZEN_WINDOW: fechas distintas o superpuestas con descubrimiento prohibidas')
    now = utc_now()
    require(now.tzinfo is not None and now.utcoffset() is not None, 'Reloj sin zona UTC')
    require(now >= END_UTC,
            'WINDOW_OPEN: no leer ni calcular resultados antes de 2026-11-01 00:00 America/New_York (04:00 UTC)')


def verify_frozen_code():
    for name, expected in FROZEN_SHA256.items():
        require(sha256(ROOT / name) == expected, 'FROZEN_HASH_MISMATCH: ' + name)


def dependencies():
    # Hash validation precedes executing/importing the frozen dependency chain.
    verify_frozen_code()
    return importlib.import_module('tools.analyze_signal_robustness')


def parse_schedule(value):
    intervals = []
    for item in value.split(';'):
        fields = item.split('|')
        require(len(fields) == 3, 'Calendario broker invalido')
        try:
            start, end = (datetime.strptime(x, '%Y.%m.%d %H:%M').replace(tzinfo=timezone.utc)
                          for x in fields[:2])
            offset = int(fields[2])
        except ValueError:
            raise HoldoutError('Calendario broker invalido') from None
        require(start < end and -840 <= offset <= 840 and
                (not intervals or start >= intervals[-1][1]), 'Calendario broker solapado/invalido')
        intervals.append((start, end, offset))
    return intervals


def schedule_covers_window(intervals):
    cursor = START_UTC
    for start, end, _ in intervals:
        if end <= cursor:
            continue
        if start > cursor:
            return False
        cursor = end
        if cursor >= END_UTC:
            return True
    return False


def expected_slots():
    """Conservative collection completeness check, not a broker holiday calendar."""
    result = set()
    day = datetime(2026, 8, 15, tzinfo=timezone.utc)
    end = datetime(2026, 11, 1, tzinfo=timezone.utc)
    while day < end:
        if day.weekday() < 5:
            result.update(int(day.timestamp()) + minute * 60 for minute in range(8*60, 12*60, 5))
        day += timedelta(days=1)
    return result


def inspect_source(path, scanner):
    """Validate fixed settings and real UTC/NY linkage, without outcomes."""
    slots = set()
    intervals = parse_schedule(BROKER_SCHEDULE)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        require(reader.fieldnames is not None and len(reader.fieldnames) == len(scanner.COLUMNS)
                and set(reader.fieldnames) == set(scanner.COLUMNS), 'Columnas scanner-v1 invalidas')
        for raw in reader:
            require(None not in raw and all(x is not None for x in raw.values()), 'Fila CSV invalida')
            scanner.identity_metadata(raw['identity'], reader.line_num)
            parts = raw['identity'].split('|')
            require([int(x) for x in parts[7:13]] == POLICY['scanner_parameters'], 'FROZEN_PARAMETERS: scanner cambiado')
            schedule = bytes.fromhex(parts[13]).decode('utf-16-be')
            require(schedule == BROKER_SCHEDULE, 'FROZEN_PARAMETERS: BrokerUtcSchedule cambiado')
            symbol = bytes.fromhex(parts[3]).decode('utf-16-be')
            require('XAUUSD' in symbol.upper(), 'Simbolo fuera del protocolo XAUUSD')
            values = scanner.typed_row(raw, reader.line_num)
            accepted = any(raw[lane+'_reason'] == 'ACCEPT_DIAGNOSTIC' for lane in scanner.LANES)
            utc = values['decision_utc']
            if not utc:
                require(not accepted, 'Senal aceptada sin hora UTC verificable')
                continue
            instant = datetime.fromtimestamp(utc, timezone.utc)
            matches = [offset for a, b, offset in intervals if a <= instant < b
                       and values['decision_server'] == utc + offset*60]
            require(matches == [values['server_offset_minutes']], 'Conversion broker/UTC incompatible')
            if START_UTC <= instant < END_UTC:
                # This particular window ends before the 2026 NY fallback at 06:00 UTC.
                require(values['ny_offset_minutes'] == -240 and values['decision_ny'] == utc-4*3600,
                        'Conversion UTC/NY incompatible')
                if raw['data_status'] == 'OK' and raw['session'] == 'IN':
                    slots.add(values['decision_ny'])
            elif accepted:
                raise HoldoutError('OUTSIDE_HOLDOUT: senal de descubrimiento o fuera de ventana')
    expected = expected_slots()
    return {'expected_session_slots': len(expected), 'valid_session_slots': len(slots & expected),
            'missing_session_slots': len(expected - slots),
            'collection_complete': expected <= slots}


def scenarios(signals, market, entries, robust):
    """Only two predeclared horizons/costs; exclude signal and end-boundary bars."""
    outcomes = robust.outcomes
    point = Decimal(POLICY['point_size'])
    result = {}
    with localcontext() as ctx:
        ctx.prec = 40
        for minutes in (60, 120):
            for factor in POLICY['spread_factors']:
                rows = []
                for signal in signals:
                    decision = signal['decision_server']
                    entry = entries[decision]
                    require(entry['delay_seconds'] == '0' and int(entry['observed_server']) == decision,
                            'Cotizacion tardia: causalidad incompatible')
                    bid, ask, spread = (outcomes.decimal_number(entry[k]) for k in ('bid', 'ask', 'spread_points'))
                    require(bid > 0 and ask >= bid and spread >= 0 and
                            abs(ask-bid-spread*point) <= point*Decimal('0.000001'), 'Spread/precios incompatibles')
                    scenario_ask = bid+(ask-bid)*Decimal(factor)
                    real = outcomes.horizon_result(market, decision, minutes, signal['direction'], bid, scenario_ask, point)
                    inverse = outcomes.horizon_result(market, decision, minutes,
                        'SELL' if signal['direction'] == 'BUY' else 'BUY', bid, scenario_ask, point)
                    row = dict(sample_id=signal['signal_id'], module=signal['module'], direction=signal['direction'],
                        day=signal['decision_ny_text'][:10], decision_server=decision,
                        horizon_minutes=minutes, spread_factor=factor, entry_bid=str(bid), entry_ask=str(ask),
                        scenario_ask=str(scenario_ask), **real)
                    for metric in outcomes.METRICS:
                        row[metric] = float(real[metric]) if real[metric] is not None else None
                    row['inverse_close_return_points'] = (float(inverse['close_return_points'])
                        if inverse['close_return_points'] is not None else None)
                    row['paired_delta_points'] = (float(real['close_return_points']-inverse['close_return_points'])
                        if real['status'] == 'COMPLETE' else None)
                    rows.append(row)
                for reverse, name in ((False, 'nonoverlap_first'), (True, 'nonoverlap_last')):
                    # Select BEFORE removing incomplete horizons, using timestamps only.
                    chosen = {r['sample_id'] for r in robust.nonoverlap(rows, minutes, reverse)}
                    for row in rows:
                        row[name] = int(row['sample_id'] in chosen)
                result[minutes, factor] = rows
    return result


def summarize(all_scenarios, robust):
    summaries = []
    for (minutes, factor), rows in all_scenarios.items():
        complete = [r for r in rows if r['status'] == 'COMPLETE']
        seed = robust.stable_seed(POLICY['seed'], f'PHASE3|{minutes}')
        # Reuse the same resampled days across costs and metrics.
        ci = robust.day_bootstrap(complete, POLICY['bootstrap_reps'], seed) if minutes == 60 else {}
        p = robust.paired_permutation(complete, POLICY['permutations'], seed)[0] if minutes == 60 and factor == '1.00' else None
        for subset, selected in (
                ('ALL', rows), ('NONOVERLAP_FIRST', [r for r in rows if r['nonoverlap_first']]),
                ('NONOVERLAP_LAST', [r for r in rows if r['nonoverlap_last']])):
            valid = [r for r in selected if r['status'] == 'COMPLETE']
            for metric in robust.METRICS:
                is_primary = minutes == 60 and metric in ('close_return_points', 'paired_delta_points')
                row = dict(horizon_minutes=minutes, role='PRIMARY' if is_primary else 'SECONDARY_DESCRIPTIVE',
                    spread_factor=factor, subset=subset, metric=metric, n_total=len(selected),
                    n_complete=len(valid), n_days=len({r['day'] for r in valid}),
                    **robust.describe([r[metric] for r in valid]))
                if subset == 'ALL':
                    if metric in ci:
                        row.update(bootstrap_low95=ci[metric][0], bootstrap_high95=ci[metric][1])
                    row.update(robust.leave_one_out(valid, metric)[1])
                    if metric == 'paired_delta_points':
                        row['permutation_p_one_sided'] = p
                summaries.append(row)
    return summaries


def primary_verdict(summary, collection_complete=True):
    lookup = {(r['horizon_minutes'], r['spread_factor'], r['subset'], r['metric']): r for r in summary}
    counts = []
    for factor in ('1.00', '2.00'):
        row = lookup.get((60, factor, 'ALL', 'close_return_points'))
        require(row is not None, 'PRIMARY_60_COUNTS_INVALID: falta escenario primario')
        values = tuple(row.get(key) for key in ('n_total', 'n_complete', 'n_days'))
        require(all(type(value) is int for value in values) and
                0 <= values[2] <= values[1] <= values[0],
                'PRIMARY_60_COUNTS_INVALID: conteos primarios invalidos')
        counts.append(values)
    # Costs cannot change the population, available bars or complete NY days.
    require(counts[0] == counts[1], 'PRIMARY_60_COUNTS_INCONSISTENT: spread x1 y x2 difieren')
    base = lookup[60, '1.00', 'ALL', 'close_return_points']
    reasons = []
    if any(n_complete != n_total for n_total, n_complete, _ in counts):
        reasons.append('PRIMARY_60_HORIZON_INCOMPLETE')
    if not collection_complete:
        reasons.append('INCOMPLETE_COLLECTION')
    if base['n_complete'] < 20 or base['n_days'] < 10:
        reasons.append('FEWER_THAN_20_COMPLETE_SIGNALS_OR_10_NY_DAYS')
    if reasons:
        return {'status': 'INCONCLUSIVE', 'reasons': reasons, 'criteria': {}}
    criteria = {}
    positive = lambda x: x is not None and x > 0
    for factor in ('1.00', '2.00'):
        row = lookup[60, factor, 'ALL', 'close_return_points']
        for stat in ('mean', 'median', 'trimmed_mean_10', 'winsorized_mean_10', 'loo_mean_min', 'bootstrap_low95'):
            criteria[f'{factor}:ALL:{stat}'] = positive(row.get(stat))
        for subset in ('NONOVERLAP_FIRST', 'NONOVERLAP_LAST'):
            criteria[f'{factor}:{subset}:mean'] = positive(lookup[60, factor, subset, 'close_return_points']['mean'])
        paired = lookup[60, factor, 'ALL', 'paired_delta_points']
        for stat in ('mean', 'bootstrap_low95'):
            criteria[f'{factor}:PAIRED:{stat}'] = positive(paired.get(stat))
    p = lookup[60, '1.00', 'ALL', 'paired_delta_points'].get('permutation_p_one_sided')
    criteria['primary_one_sided_p_le_0.05'] = p is not None and 0 <= p <= .05
    failures = [key for key, passed in criteria.items() if not passed]
    return {'status': 'FAIL' if failures else 'PASS', 'reasons': failures, 'criteria': criteria}


def analyze(input_path, output_dir, start=START_NY, end=END_NY):
    check_window(start, end)  # MUST precede file reads, hashing inputs or output creation.
    robust = dependencies()
    require(schedule_covers_window(parse_schedule(BROKER_SCHEDULE)),
            'BROKER_SCHEDULE_INCOMPLETE: calendario congelado termina 2026-09-01; requiere evidencia horaria y revision explicita del protocolo')
    source = Path(input_path).resolve()
    target = Path(output_dir)
    require(not target.is_symlink(), 'Destino enlazado prohibido')
    output = target.resolve()
    require(not output.exists(), 'Destino existente: nunca sobrescribir artefactos aceptados')
    require(output != source and output not in source.parents, 'Destino contiene entrada')
    frozen_before = {str(p): sha256(p) for p in (Path(__file__), PROTOCOL)}
    input_hash = sha256(source)
    collection = inspect_source(source, robust.scanner)
    accepted, validation, sensitive = robust.scanner.collect(source)
    signals = [r for r in accepted if r['module'] == 'B0+PB1']
    # Dates are checked on ALL accepted rows, before selecting the primary population.
    market, entries, market_counts = robust.outcomes.reconstruct_market(source, {r['decision_server'] for r in signals})
    all_scenarios = scenarios(signals, market, entries, robust)
    summary = summarize(all_scenarios, robust)
    verdict = primary_verdict(summary, collection['collection_complete'])
    manifest = {'protocol': POLICY, 'broker_schedule': BROKER_SCHEDULE,
        'input_sha256': input_hash, 'frozen_code_sha256': FROZEN_SHA256,
        'validator_sha256': frozen_before[str(Path(__file__))], 'protocol_sha256': frozen_before[str(PROTOCOL)],
        'python_version': sys.version.split()[0], 'window_closed': True,
        'verdict': verdict, 'collection': collection,
        'counts': {'source_rows': validation['total_rows'], 'accepted_in_window': len(accepted),
                   'primary_population': len(signals), **market_counts},
        'coverage': {str(m): {'n_total': len(signals), 'n_complete': sum(r['status'] == 'COMPLETE'
                     for r in all_scenarios[m, '1.00'])} for m in (60, 120)},
        'limitations': ['No proof of edge or executable PnL.', 'No independence guarantee between NY days.',
            'Integrity checks cannot authenticate a broker feed or prove the absence of omitted source records.'],
        'files': [], 'determinism': 'No run timestamp/paths; same input, code and Python; manifest excludes its own hash.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.holdout-stage-', dir=output.parent) as directory:
        stage = Path(directory)
        robust.write_table(stage / OUTPUT_NAMES[0], SUMMARY_COLUMNS, summary)
        robust.write_table(stage / OUTPUT_NAMES[1], SIGNAL_COLUMNS,
                           [row for rows in all_scenarios.values() for row in rows])
        manifest['files'] = [{'name': name, 'sha256': sha256(stage / name)} for name in OUTPUT_NAMES[:-1]]
        (stage / OUTPUT_NAMES[-1]).write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        for path in stage.iterdir():
            content = path.read_text(encoding='utf-8').casefold()
            require(not any(token.casefold() in content for token in sensitive if token), 'Salida contiene identidad sensible')
        require(sha256(source) == input_hash, 'Entrada cambiada durante validacion')
        verify_frozen_code()
        require(all(sha256(p) == digest for p, digest in frozen_before.items()), 'Protocolo/validador cambiado durante validacion')
        require(not output.exists(), 'Destino aparecio durante validacion')
        stage.rename(output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--start-ny', default=START_NY)
    parser.add_argument('--end-ny', default=END_NY)
    args = parser.parse_args(argv)
    try:
        # No --as-of, clock override, seed, module, direction or statistical options.
        check_window(args.start_ny, args.end_ny)
        output = (ROOT / args.output_dir).resolve()
        require(output.parent == ROOT / 'artifacts/scanner_analysis'
                and output.name.startswith('phase3_'), 'Destino debe ser artifacts/scanner_analysis/phase3_<nombre_nuevo>')
        manifest = analyze(ROOT / args.input, output, args.start_ny, args.end_ny)
    except (HoldoutError, ValueError, csv.Error, UnicodeError) as error:
        print('BLOCKED/INVALID: '+str(error), file=sys.stderr)
        return 2
    except OSError:
        print('BLOCKED/INVALID: error de lectura o escritura; sin veredicto.', file=sys.stderr)
        return 3
    print(manifest['verdict']['status'])
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
