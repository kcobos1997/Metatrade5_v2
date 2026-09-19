"""Deterministic offline outcomes for exactly 50 reviewed scanner signals; no trading."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation, localcontext
import html
import itertools
import json
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
if __package__:
    from . import analyze_scanner as scanner
else:
    import analyze_scanner as scanner

VERSION = '1.0'
HORIZONS = (15, 30, 60, 120)
EXPECTED_SIGNALS = 50
SPREAD_MODEL = 'ENTRY_SPREAD_CONSTANT'
OUTPUT_NAMES = ('signal_outcomes.csv', 'outcome_summary.csv', 'signal_outcome_report.html', 'outcome_manifest.json')
CLASSIFICATIONS = {
    'chart_quality': ('CLEAR', 'MIXED', 'POOR'),
    'signal_alignment': ('ALIGNED', 'UNCLEAR', 'MISALIGNED'),
    'context_class': ('TREND', 'RANGE', 'TRANSITION', 'UNCLEAR'),
    'reviewer_decision': ('VALID', 'QUESTIONABLE', 'REJECTED'),
}
ANNOTATION_COLUMNS = ('sample_id', 'signal_open_server_text', 'bar_time_epoch', 'decision_ny_text',
                      'direction', 'module', 'status', 'validation_errors', *CLASSIFICATIONS, 'reviewer_notes')
METRICS = ('mfe_points', 'mae_points', 'close_return_points')
STATISTICS = ('mean', 'median', 'p25', 'p75')
GROUPS = ((), ('module',), ('direction',), ('reviewer_decision',), ('signal_alignment',),
          ('context_class',), ('module', 'context_class'), ('reviewer_decision', 'context_class'))
LEVELS = {'module': ('B0', 'PB1', 'B0+PB1'), 'direction': ('BUY', 'SELL'), **CLASSIFICATIONS}
SUMMARY_COLUMNS = ('group_by', 'group_value', 'group_value_2', 'horizon_minutes', 'n_total', 'n_complete',
                   'n_incomplete') + tuple(f'{metric}_{stat}' for metric in METRICS for stat in STATISTICS) + ('positive_close_proportion',)
require = scanner.require
ValidationError = scanner.ValidationError


def decimal_number(value, line=0, field='precio') -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(line, f'número inválido en {field}') from None
    require(result.is_finite(), line, f'número no finito en {field}')
    return result


def read_table(path: Path, required: tuple) -> tuple[list[str], list[dict]]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        require(len(fields) == len(set(fields)) and set(required) <= set(fields), 1,
                'cabecera incompleta o duplicada')
        rows = []
        for row in reader:
            require(None not in row and all(v is not None for v in row.values()), reader.line_num,
                    'número de campos incorrecto')
            rows.append(row)
    return fields, rows


def join_reviews(sample_path: Path, annotations_path: Path) -> tuple[list[str], list[dict], dict]:
    """Strict one-to-one join, preserving sample file order and original annotation strings."""
    sample_fields, samples = read_table(sample_path, scanner.REDUCED_COLUMNS + scanner.REVIEW_COLUMNS)
    annotation_fields, annotations = read_table(annotations_path, ANNOTATION_COLUMNS)
    require(len(samples) == EXPECTED_SIGNALS, 0, 'la muestra debe contener exactamente 50 señales')
    require(len(annotations) == EXPECTED_SIGNALS, 0, 'las anotaciones deben contener exactamente 50 señales')
    sample_ids = [r['signal_id'] for r in samples]
    annotation_ids = [r['sample_id'] for r in annotations]
    for ids in (sample_ids, annotation_ids):
        require(all(value.strip() for value in ids) and len(set(ids)) == EXPECTED_SIGNALS, 0,
                'sample_id vacío o duplicado')
    require(set(sample_ids) == set(annotation_ids), 0, 'unión sample_id no es uno a uno')
    annotation_map = {r['sample_id']: r for r in annotations}
    joined = []
    for line, sample in enumerate(samples, 2):
        annotation = annotation_map[sample['signal_id']]
        for field, options in CLASSIFICATIONS.items():
            require(annotation[field] in options, line, f'{field} vacío, PENDING o desconocido')
        require(bool(annotation['reviewer_notes'].strip()), line, 'reviewer_notes vacío')
        require(annotation['status'] == 'OK' and not annotation['validation_errors'].strip(), line,
                'anotación contiene errores de validación')
        if 'completed' in annotation:
            require(annotation['completed'].lower() == 'true', line, 'anotación no completada')
        stamp = scanner.integer(sample['signal_open_server'], line, 'signal_open_server')
        decision = scanner.integer(sample['decision_server'], line, 'decision_server')
        require(stamp > 0 and stamp % 300 == 0 and decision == stamp+300, line, 'entrada no alineada con señal M5')
        require(scanner.integer(annotation['bar_time_epoch'], line, 'bar_time_epoch') == stamp and
                annotation['signal_open_server_text'] == sample['signal_open_server_text'] == scanner.timestamp_text(stamp),
                line, 'timestamps de señal no coinciden')
        require(sample['decision_server_text'] == scanner.timestamp_text(decision), line, 'timestamp decisión no coincide')
        require(sample['decision_ny_text'] == annotation['decision_ny_text'] ==
                scanner.timestamp_text(scanner.integer(sample['decision_ny'], line, 'decision_ny')), line, 'timestamp NY no coincide')
        for field in ('direction', 'module'):
            require(annotation[field] == sample[field] and sample[field] in LEVELS[field], line,
                    f'{field} no coincide entre muestra y anotaciones')
        # Any other shared field must agree. No silent precedence for colliding columns.
        for field in set(sample) & set(annotation):
            require(sample[field] == annotation[field], line, f'campo compartido incompatible: {field}')
        joined.append({**sample, **annotation})
    fields = list(dict.fromkeys(sample_fields + annotation_fields))
    counts = {'sample_rows':len(samples), 'annotation_rows':len(annotations), 'joined_signals':len(joined),
              'unique_sample_ids':len(set(sample_ids)), 'duplicate_ids':0, 'annotation_validation_errors':0,
              'classification_counts':{field:dict(sorted(Counter(r[field] for r in joined).items())) for field in CLASSIFICATIONS}}
    return fields, joined, counts


def parse_window(value: str, decision: int, line: int = 0) -> list[tuple]:
    """Decode each observed bar even across session gaps; continuity is a horizon property."""
    if not value:
        return []
    result = []
    for item in value.split(';'):
        fields = item.split(':')
        require(len(fields) == 5, line, 'formato m5_window inválido')
        stamp = scanner.integer(fields[0], line, 'm5_window.time')
        scanner.timestamp_text(stamp, line)
        require(stamp > 0 and stamp % 300 == 0 and stamp+300 <= decision, line,
                'barra M5 abierta, futura o no alineada')
        opening, high, low, close = (decimal_number(v, line, 'm5_window.OHLC') for v in fields[1:])
        require(min(opening, high, low, close) > 0 and high >= max(opening, close) and
                low <= min(opening, close), line, 'OHLC no positivo o incoherente')
        require(not result or stamp > result[-1][0], line, 'ventana M5 desordenada o duplicada')
        result.append((stamp, opening, high, low, close))
    return result


def reconstruct_market(input_path: Path, decisions: set[int]) -> tuple[dict, dict, dict]:
    """Called after scanner.collect has validated every source row and checksum."""
    bars, entries = {}, {}
    occurrences = duplicates = empty = 0
    with input_path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        for raw in reader:
            decision = scanner.integer(raw['decision_server'], reader.line_num, 'decision_server')
            window = parse_window(raw['m5_window'], decision, reader.line_num)
            if not window:
                require(raw['data_status'] == 'DATA_M5', reader.line_num, 'ventana vacía sin DATA_M5')
                empty += 1
            for stamp, *prices in window:
                prices = tuple(prices)
                occurrences += 1
                if stamp in bars:
                    require(bars[stamp] == prices, reader.line_num,
                            f'OHLC conflictivos para timestamp {stamp} ({scanner.timestamp_text(stamp)})')
                    duplicates += 1
                else:
                    bars[stamp] = prices
            if decision in decisions:
                require(decision not in entries, reader.line_num, 'decisión de entrada duplicada')
                entries[decision] = {field:raw[field] for field in
                                     ('bid', 'ask', 'spread_points', 'delay_seconds', 'observed_server')}
    require(set(entries) == decisions, 0, 'falta una decisión de entrada en el original')
    return bars, entries, {'canonical_m5_bars':len(bars), 'bar_occurrences':occurrences,
                           'identical_bar_repetitions':duplicates, 'conflicting_bars':0, 'empty_windows':empty}


def validate_sample_source(rows: list[dict], signals: list[dict]) -> None:
    accepted = {row['signal_id']:row for row in signals}
    for line, row in enumerate(rows, 2):
        require(row['signal_id'] in accepted, line, 'signal_id no existe entre aceptaciones originales')
        source = accepted[row['signal_id']]
        for field in scanner.REDUCED_COLUMNS:
            value = source[field]
            if isinstance(value, int):
                equal = scanner.integer(row[field], line, field) == value
            elif isinstance(value, float):
                equal = scanner.finite(row[field], line, field) == value
            else:
                equal = row[field] == value
            require(equal, line, f'muestra no coincide con original: {field}')


def horizon_result(bars: dict, decision: int, minutes: int, direction: str,
                   bid: Decimal, ask: Decimal, point: Decimal) -> dict:
    require(minutes in HORIZONS and direction in ('BUY','SELL'), 0, 'horizonte o dirección inválidos')
    expected = tuple(range(decision, decision+minutes*60, 300))
    missing = [stamp for stamp in expected if stamp not in bars]
    result = {'status':'INCOMPLETE' if missing else 'COMPLETE', 'bar_count':len(expected)-len(missing),
              'missing_timestamps':';'.join(map(str, missing)),
              'missing_server_text':';'.join(scanner.timestamp_text(stamp) for stamp in missing),
              'first_bar_open':expected[0], 'last_bar_open':expected[-1],
              'end_exclusive':decision+minutes*60, **{metric:None for metric in METRICS}}
    if missing:
        return result
    window = [bars[stamp] for stamp in expected]  # Exact interval; signal and end boundary are excluded.
    with localcontext() as ctx:
        ctx.prec = 40
        maximum, minimum, last_close = max(b[1] for b in window), min(b[2] for b in window), window[-1][3]
        if direction == 'BUY':
            mfe, mae, close_return = max(Decimal(0), maximum-ask)/point, max(Decimal(0), ask-minimum)/point, (last_close-ask)/point
        else:
            spread = ask-bid
            mfe, mae, close_return = max(Decimal(0), bid-(minimum+spread))/point, max(Decimal(0), maximum+spread-bid)/point, (bid-(last_close+spread))/point
        result.update(zip(METRICS, (mfe, mae, close_return)))
    return result


def compute_outcomes(rows: list[dict], bars: dict, entries: dict, point: Decimal) -> tuple[list[str], list[dict]]:
    computed = ('entry_bid', 'entry_ask', 'entry_price', 'entry_spread_points', 'entry_spread_price', 'point_size', 'spread_model')
    horizon_fields = ('status','bar_count','missing_timestamps','missing_server_text','first_bar_open','last_bar_open','end_exclusive',*METRICS)
    added = list(computed) + [f'h{minutes}_{field}' for minutes in HORIZONS for field in horizon_fields]
    results = []
    for line, original in enumerate(rows, 2):
        require(not set(added) & set(original), line, 'colonnes calculées déjà présentes dans les entrées')
        row = dict(original)
        decision = int(row['decision_server'])
        source = entries[decision]
        # An observed quote after the decision would not support the requested entry model.
        require(source['delay_seconds'] == '0' and int(source['observed_server']) == decision,
                line, 'cotización de entrada tardía: no disponible exactamente en decision_server')
        bid, ask, spread_points = (decimal_number(source[key], line, key) for key in ('bid','ask','spread_points'))
        require(point > 0 and bid > 0 and ask >= bid and spread_points >= 0, line, 'precio, spread o point-size inválido')
        with localcontext() as ctx:
            ctx.prec = 40
            spread_price = ask-bid
            # Scanner double serialization can leave sub-point noise. No quote is adjusted.
            require(abs(spread_price-spread_points*point) <= point*Decimal('0.000001'), line,
                    'point-size incompatible con spread observado')
        row.update(entry_bid=bid, entry_ask=ask, entry_price=ask if row['direction']=='BUY' else bid,
                   entry_spread_points=spread_points, entry_spread_price=spread_price, point_size=point, spread_model=SPREAD_MODEL)
        for minutes in HORIZONS:
            values = horizon_result(bars, decision, minutes, row['direction'], bid, ask, point)
            row.update({f'h{minutes}_{key}':value for key,value in values.items()})
        results.append(row)
    return added, results


def quantile(values: list[Decimal], proportion: Decimal) -> Decimal:
    ordered = sorted(values)
    position = (len(ordered)-1)*proportion
    lower = int(position)
    upper = min(lower+1, len(ordered)-1)
    return ordered[lower] + (ordered[upper]-ordered[lower])*(position-lower)


def summarize(outcomes: list[dict]) -> list[dict]:
    summaries = []
    with localcontext() as ctx:
        ctx.prec = 40
        for grouping in GROUPS:
            combinations = itertools.product(*(LEVELS[field] for field in grouping)) if grouping else [()]
            for values in combinations:
                rows = [r for r in outcomes if all(r[field] == value for field,value in zip(grouping,values))]
                for minutes in HORIZONS:
                    complete = [r for r in rows if r[f'h{minutes}_status'] == 'COMPLETE']
                    summary = dict(group_by=' × '.join(grouping) or 'TOTAL', group_value=values[0] if values else 'ALL',
                                   group_value_2=values[1] if len(values)>1 else '', horizon_minutes=minutes,
                                   n_total=len(rows), n_complete=len(complete), n_incomplete=len(rows)-len(complete))
                    for metric in METRICS:
                        numbers = [r[f'h{minutes}_{metric}'] for r in complete]
                        stats = (sum(numbers)/len(numbers), quantile(numbers,Decimal('.5')),
                                 quantile(numbers,Decimal('.25')), quantile(numbers,Decimal('.75'))) if numbers else (None,)*4
                        summary.update(zip((f'{metric}_{stat}' for stat in STATISTICS), stats))
                    summary['positive_close_proportion'] = Decimal(sum(r[f'h{minutes}_close_return_points'] > 0 for r in complete))/len(complete) if complete else None
                    summaries.append(summary)
    return summaries


def cell(value) -> str:
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return format(value, 'f') if value else '0'
    return str(value)


def write_csv(path: Path, columns, rows) -> None:
    scanner.write_csv(path, tuple(columns), [{key:cell(row.get(key)) for key in columns} for row in rows])


def report_html(summaries: list[dict], counts: dict, coverage: dict, hashes: dict) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    def display(value):
        if value is None:
            return '—'
        if isinstance(value, Decimal):
            return f'{value:.2f}'
        return esc(value)
    columns = ('group_value','group_value_2','horizon_minutes','n_total','n_complete',
               'mfe_points_mean','mae_points_mean','close_return_points_mean','close_return_points_median','positive_close_proportion')
    labels = ('Grupo','Contexto','Min','N total','N completo','MFE media','MAE media','Cierre medio','Cierre mediana','Cierre > 0')
    sections = []
    titles = {'TOTAL':'Resumen general','module':'Módulos B0, PB1 y B0+PB1','context_class':'Contexto visual',
              'reviewer_decision':'Decisión visual','direction':'BUY y SELL','signal_alignment':'Alineación',
              'module × context_class':'Módulo y contexto','reviewer_decision × context_class':'Decisión y contexto'}
    for group, title in titles.items():
        body = []
        for row in summaries:
            if row['group_by'] != group:
                continue
            values = [display(row[col]) if col != 'positive_close_proportion' else
                      ('—' if row[col] is None else f'{row[col]*100:.1f}%') for col in columns]
            if row['n_complete'] < 10:
                values[4] += ' <span class="small">muestra pequeña</span>'
            body.append('<tr>'+''.join(f'<td>{v}</td>' for v in values)+'</tr>')
        sections.append(f'<section><h2>{esc(title)}</h2><div class="scroll"><table><thead><tr>'+''.join(f'<th>{label}</th>' for label in labels)+
                        '</tr></thead><tbody>'+''.join(body)+'</tbody></table></div></section>')
    coverage_rows = ''.join(f'<tr><td>{minutes} min</td><td>{coverage[str(minutes)]["n_complete"]}/50</td><td>{coverage[str(minutes)]["n_incomplete"]}</td></tr>' for minutes in HORIZONS)
    audit = '<ul>'+''.join(f'<li>{esc(key)}: {esc(value)}</li>' for key,value in counts.items() if isinstance(value,int))+'</ul>'
    source_list = '<ul>'+''.join(f'<li>{esc(role)}: {esc(item["name"])}<br><code>{esc(item["sha256"])}</code></li>' for role,item in hashes.items())+'</ul>'
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'">'
            '<title>XAUUSD resultados posteriores</title><style>body{font:16px Segoe UI,Arial,sans-serif;margin:0;background:#101a28;color:#eaf1fa}'
            'main{max-width:1400px;margin:auto;padding:24px}h1,h2{color:#9dccff}p,li{line-height:1.6}.warning{background:#45361e;padding:16px;border-left:5px solid #efb85a}'
            'table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px;border-bottom:1px solid #3d4c60;text-align:right}th{background:#243851}td:first-child,th:first-child{text-align:left}'
            '.scroll{overflow:auto}.small{display:block;color:#efb85a;font-size:12px}section{margin:28px 0}code{overflow-wrap:anywhere}</style></head><body><main>'
            '<h1>XAUUSD: resultados posteriores de 50 señales revisadas</h1>'
            '<p class="warning"><strong>No es un backtest ni una estimación de rentabilidad.</strong> Son excursiones de precio y retornos firmados al cierre en puntos. '
            'No interpretar estas métricas como beneficios ejecutables ni usarlas todavía para elegir SL, TP, riesgo o reglas de ejecución.</p>'
            '<p>Se conservan las 50 señales, incluidas QUESTIONABLE y REJECTED. Cada horizonte usa únicamente aperturas M5 '
            'en [decision_server, decision_server + horizonte). Se excluye completamente la vela de señal.</p>'
            '<h2>Integridad y cobertura</h2><p>Validaciones aprobadas: unión uno a uno, revisión completa, coincidencia con el scanner, '
            'checksums de origen, OHLC válidos y sin contradicciones. Hashes de entradas conservados.</p>'+audit+
            '<table><thead><tr><th>Horizonte</th><th>Completas</th><th>Incompletas</th></tr></thead><tbody>'+coverage_rows+'</tbody></table>'
            '<h2>Modelo ENTRY_SPREAD_CONSTANT</h2><p>Entrada BUY al ask observado; salida analítica con OHLC bid. '
            'Entrada SELL al bid observado; OHLC ask aproximado como OHLC bid futuro + (ask − bid) de entrada constante. '
            'point_size = 0.01. Se comprueba su compatibilidad con el spread registrado. No se modelan spread futuro real, '
            'comisiones, slippage, swaps, liquidez, ejecuciones ni trayectorias intrabar.</p>'
            '<p>BUY: MFE = max(0, high máximo − ask) / point; MAE = max(0, ask − low mínimo) / point; cierre = (close final − ask) / point. '
            'SELL: MFE = max(0, bid − low ask mínimo) / point; MAE = max(0, high ask máximo − bid) / point; cierre = (bid − close ask final) / point.</p>'
            '<p class="warning">Muestra pequeña y estratificada, con horizontes y señales que pueden solaparse. No se asume independencia ni representatividad '
            'de frecuencias reales. Un grupo con menos de 10 horizontes completos se marca como pequeño; no es un umbral de selección ni optimización. '
            'Estas comparaciones son descriptivas y no demuestran capacidad predictiva de la revisión.</p>'
            '<p>Horizontes incompletos: métricas vacías y exclusión únicamente de su propio resumen. Los vacíos no cuentan como ceros. '
            'Promedios y proporciones usan n_complete. El CSV de resumen contiene además medianas y percentiles 25/75 de las tres métricas '
            '(interpolación lineal con posición (n−1)·p). Se muestran todos los grupos predefinidos, incluidos los vacíos. HTML redondeado solo para presentación.</p>'+
            ''.join(sections)+'<h2>Entradas verificadas</h2>'+source_list+'</main></body></html>')


def analyze(input_path: Path, sample_path: Path, annotations_path: Path, output_dir: Path,
            point_size='0.01') -> dict:
    point = decimal_number(point_size, field='point-size')
    require(point == Decimal('0.01'), 0, 'este protocolo exige --point-size 0.01')
    paths = {role:Path(path).resolve() for role,path in
             (('scanner',input_path),('sample',sample_path),('annotations',annotations_path))}
    require(len(set(paths.values())) == 3, 0, 'las tres entradas deben ser archivos diferentes')
    output_arg = Path(output_dir)
    require(not output_arg.is_symlink(), 0, 'destino no puede ser un enlace')
    output = output_arg.resolve()
    require(all(output != path and output not in path.parents for path in paths.values()), 0, 'entrada dentro del destino')
    if output.exists():
        require(output.is_dir() and all(p.name in OUTPUT_NAMES and p.is_file() and not p.is_symlink() for p in output.iterdir()),
                0, 'destino contiene archivos ajenos')
    hashes = {role:{'name':path.name,'sha256':scanner.source_sha256(path)} for role,path in paths.items()}
    fields, joined, counts = join_reviews(paths['sample'], paths['annotations'])
    accepted, validation, sensitive = scanner.collect(paths['scanner'])
    validate_sample_source(joined, accepted)
    bars, entries, bar_counts = reconstruct_market(paths['scanner'], {int(r['decision_server']) for r in joined})
    added, outcomes = compute_outcomes(joined, bars, entries, point)
    summaries = summarize(outcomes)
    coverage = {str(m):{'n_total':len(outcomes), 'n_complete':sum(r[f'h{m}_status']=='COMPLETE' for r in outcomes),
                        'n_incomplete':sum(r[f'h{m}_status']=='INCOMPLETE' for r in outcomes)} for m in HORIZONS}
    counts.update(bar_counts, scanner_rows=validation['total_rows'], scanner_identities=validation['identity_count'],
                  accepted_signal_bars=validation['unique_signal_bars'], matched_original_signals=len(joined),
                  source_checksums_validated=validation['total_rows'], authorized_trades=0, source_ohlc_conflicts=0,
                  sampled_entries_with_delay=0, input_hashes_verified=3)
    manifest = {'analyzer_version':VERSION, 'python_version':sys.version.split()[0], 'inputs':hashes,
                'parameters':{'point_size':cell(point),'horizons_minutes':list(HORIZONS),'expected_signals':50,
                              'spread_model':SPREAD_MODEL,'quantiles':'linear (n-1)*p','decimal_precision':40,
                              'spread_consistency_tolerance_points':'0.000001','small_group_warning_n_complete_below':10},
                'validation_counts':counts, 'coverage':coverage, 'files':[],
                'manifest_hash_note':'Self SHA-256 excluded to avoid circular self-hashing; files lists the other three outputs.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Existing project publication protocol: stage all outputs, then swap the directory.
    with tempfile.TemporaryDirectory(prefix='.outcome-stage-', dir=output.parent) as directory:
        stage = Path(directory).resolve()
        require(stage.parent == output.parent and stage != output, 0, 'directorio temporal fuera del destino previsto')
        write_csv(stage/OUTPUT_NAMES[0], fields+added, outcomes)
        write_csv(stage/OUTPUT_NAMES[1], SUMMARY_COLUMNS, summaries)
        (stage/OUTPUT_NAMES[2]).write_text(report_html(summaries, counts, coverage, hashes),encoding='utf-8',newline='\n')
        manifest['files'] = [{'name':name,'sha256':scanner.source_sha256(stage/name)} for name in OUTPUT_NAMES[:-1]]
        (stage/OUTPUT_NAMES[3]).write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
        for path in stage.iterdir():
            text = path.read_text(encoding='utf-8').casefold()
            require(not any(token.casefold() in text for token in sensitive if token), 0, 'output contendría un token sensible')
        require(all(scanner.source_sha256(path)==hashes[role]['sha256'] for role,path in paths.items()),
                0, 'una entrada cambió durante el análisis')
        scanner.publish_directory(stage,output)
    return manifest


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--sample',required=True)
    parser.add_argument('--annotations',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--point-size',required=True)
    args=parser.parse_args(argv)
    try:
        output=scanner.repository_path(args.output_dir).resolve()
        require(output.parent==scanner.ARTIFACT_ROOT.resolve() and bool(re.fullmatch(r'[A-Za-z0-9_-]+',output.name)),
                0,'output-dir debe ser artifacts/scanner_analysis/<experimento>')
        manifest=analyze(scanner.repository_path(args.input),scanner.repository_path(args.sample),
                         scanner.repository_path(args.annotations),output,args.point_size)
    except (ValidationError,csv.Error,UnicodeError) as error:
        print('ERROR: '+(str(error) if isinstance(error,ValidationError) else 'CSV o codificación inválidos'),file=sys.stderr)
        return 2
    except OSError:
        print('ERROR: no se pudo leer una entrada o publicar los resultados.',file=sys.stderr)
        return 3
    print('OK: 50 señales conservadas; '+', '.join(f'{m} min: {manifest["coverage"][str(m)]["n_complete"]}/50 completas' for m in HORIZONS))
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
