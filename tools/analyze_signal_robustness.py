"""Deterministic offline robustness of 266 scanner signals; no trading or optimization."""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal, localcontext
import csv
import hashlib
import html
import itertools
import json
import math
from pathlib import Path
import random
import re
import sys
import tempfile

sys.dont_write_bytecode = True
if __package__:
    from . import analyze_signal_outcomes as outcomes
else:
    import analyze_signal_outcomes as outcomes
scanner = outcomes.scanner
require = scanner.require
ValidationError = scanner.ValidationError
HORIZONS = outcomes.HORIZONS
FACTORS = ('1.00', '1.25', '1.50', '2.00')
METRICS = ('close_return_points', 'mfe_points', 'mae_points', 'paired_delta_points')
OUTPUT_NAMES = ('robustness_summary.csv', 'signal_influence.csv', 'overlap_clusters.csv',
                'robustness_report.html', 'robustness_manifest.json')
SUMMARY_COLUMNS = ('population','group','group_value','horizon_minutes','spread_factor','subset','day','metric',
    'unit','n_total','n_complete','n_days','mean','median','p25','p75','positive_proportion','trimmed_mean_10',
    'winsorized_mean_10','trim_each_tail_n','bootstrap_low95','bootstrap_high95','bootstrap_reps_valid',
    'loo_mean_min','loo_mean_max','max_abs_mean_shift','most_influential_id','permutation_p_one_sided',
    'permutation_p_two_sided','permutation_p_holm','overlapping_signals','overlap_pairs','clusters','largest_cluster',
    'candidate','candidate_failures')
INFLUENCE_COLUMNS = ('population','group','group_value','horizon_minutes','spread_factor','metric','sample_id',
    'day','direction','module','decision_server','status','missing_timestamps','first_bar_open','last_bar_open',
    'end_exclusive','entry_bid','entry_ask','scenario_ask','point_size','spread_model','value','inverse_value',
    'n_complete','full_mean','leave_one_out_mean','mean_shift','abs_mean_shift','rank_abs_shift','sign_flip',
    'nonoverlap_first','nonoverlap_last')
CLUSTER_COLUMNS = ('population','group','group_value','horizon_minutes','sample_id','decision_server','end_exclusive',
    'day','status','cluster_id','cluster_start','cluster_end_exclusive','cluster_size','direct_overlaps',
    'nonoverlap_first','nonoverlap_last')


def stable_seed(seed, label):
    return int.from_bytes(hashlib.sha256(f'{seed}|{label}'.encode('utf-8')).digest()[:8], 'big')


def quantile(values, p):
    ordered = sorted(values)
    position = (len(ordered)-1)*p
    lower = math.floor(position)
    return ordered[lower] + (ordered[min(lower+1,len(ordered)-1)]-ordered[lower])*(position-lower)


def describe(values):
    if not values:
        return {key:None for key in ('mean','median','p25','p75','positive_proportion','trimmed_mean_10','winsorized_mean_10','trim_each_tail_n')}
    ordered = sorted(values)
    n, k = len(ordered), len(ordered)//10
    trimmed = ordered[k:n-k]
    winsorized = [ordered[k]]*k + trimmed + [ordered[n-k-1]]*k
    return dict(mean=math.fsum(ordered)/n, median=quantile(ordered,.5),p25=quantile(ordered,.25),p75=quantile(ordered,.75),
                positive_proportion=sum(x>0 for x in ordered)/n,trimmed_mean_10=math.fsum(trimmed)/len(trimmed),
                winsorized_mean_10=math.fsum(winsorized)/n,trim_each_tail_n=k)


def nonoverlap(rows, minutes, reverse=False):
    """Greedy selections use timestamps only, never realized prices or annotations."""
    ordered = sorted(rows,key=lambda r:(r['decision_server'],r['sample_id']),reverse=reverse)
    selected = []
    boundary = math.inf if reverse else -math.inf
    for row in ordered:
        start, end = row['decision_server'], row['decision_server']+minutes*60
        eligible = end <= boundary if reverse else start >= boundary
        if eligible:
            selected.append(row)
            boundary = start if reverse else end
    return sorted(selected,key=lambda r:(r['decision_server'],r['sample_id']))


def clusters(rows, minutes):
    ordered = sorted(rows,key=lambda r:(r['decision_server'],r['sample_id']))
    components = []
    boundary = -math.inf
    for row in ordered:
        start = row['decision_server']
        if start >= boundary:
            components.append([])
        components[-1].append(row)
        boundary = max(boundary,start+minutes*60)
    info = {}
    pairs = overlapping = 0
    for index, component in enumerate(components,1):
        for row in component:
            degree = sum(other['sample_id'] != row['sample_id'] and
                         abs(other['decision_server']-row['decision_server']) < minutes*60 for other in component)
            pairs += degree
            overlapping += degree > 0
            info[row['sample_id']] = dict(cluster_id=f'H{minutes}-C{index:04d}',cluster_start=component[0]['decision_server'],
                cluster_end_exclusive=component[-1]['decision_server']+minutes*60,cluster_size=len(component),direct_overlaps=degree)
    return info,dict(overlapping_signals=overlapping,overlap_pairs=pairs//2,clusters=len(components),
                     largest_cluster=max(map(len,components),default=0))


def day_bootstrap(rows, reps, seed, equal_days=False):
    """Resample whole NY entry days, sharing the resampled days across metrics."""
    grouped = defaultdict(list)
    for row in rows: grouped[row['day']].append(row)
    days = sorted(grouped)
    samples = {metric:[] for metric in METRICS}
    if len(days)<2:
        return {metric:(None,None,0) for metric in METRICS}
    counts = [len(grouped[day]) for day in days]
    totals = [[math.fsum(row[metric] for row in grouped[day]) for metric in METRICS] for day in days]
    if equal_days:
        totals = [[x/n for x in total] for total,n in zip(totals,counts)]
        counts = [1]*len(days)
    rng = random.Random(seed)
    for _ in range(reps):
        indices = rng.choices(range(len(days)),k=len(days))
        denominator = sum(counts[i] for i in indices)
        for j,metric in enumerate(METRICS):
            samples[metric].append(math.fsum(totals[i][j] for i in indices)/denominator)
    return {metric:(quantile(values,.025),quantile(values,.975),len(values)) for metric,values in samples.items()}


def paired_permutation(rows, reps, seed):
    """Swap real/inverted labels jointly within each NY day, preserving dependence."""
    grouped = defaultdict(list)
    for row in rows: grouped[row['day']].append(row['paired_delta_points'])
    if len(grouped)<2: return None,None
    totals = [math.fsum(grouped[day]) for day in sorted(grouped)]
    observed = math.fsum(totals)
    rng = random.Random(seed)
    one = two = 0
    tolerance = 1e-9*max(1,abs(observed))
    for _ in range(reps):
        simulated = math.fsum(value if rng.getrandbits(1) else -value for value in totals)
        one += simulated >= observed-tolerance
        two += abs(simulated) >= abs(observed)-tolerance
    return (one+1)/(reps+1),(two+1)/(reps+1)


def holm(p_values):
    valid = sorted((p,index) for index,p in enumerate(p_values) if p is not None)
    result = [None]*len(p_values)
    running = 0.0
    for rank,(p,index) in enumerate(valid):
        running = max(running,min(1.0,p*(len(valid)-rank)))
        result[index] = running
    return result


def leave_one_out(rows, metric):
    values = [row[metric] for row in rows]
    n = len(values)
    if n<2: return [],dict(loo_mean_min=None,loo_mean_max=None,max_abs_mean_shift=None,most_influential_id='')
    total, mean = math.fsum(values),math.fsum(values)/n
    details = []
    for row in rows:
        estimate = (total-row[metric])/(n-1)
        shift = estimate-mean
        details.append(dict(sample_id=row['sample_id'],value=row[metric],full_mean=mean,leave_one_out_mean=estimate,
                            mean_shift=shift,abs_mean_shift=abs(shift),sign_flip=int(mean*estimate<=0 and mean!=estimate)))
    ranked = sorted(details,key=lambda r:(-r['abs_mean_shift'],r['sample_id']))
    for rank,row in enumerate(ranked,1): row['rank_abs_shift']=rank
    return details,dict(loo_mean_min=min(r['leave_one_out_mean'] for r in details),
                        loo_mean_max=max(r['leave_one_out_mean'] for r in details),max_abs_mean_shift=ranked[0]['abs_mean_shift'],
                        most_influential_id=ranked[0]['sample_id'])


def scenario_rows(signals, market, entries, point):
    _, baseline = outcomes.compute_outcomes(signals,market,entries,point)
    scenarios = {}
    with localcontext() as ctx:
        ctx.prec = 40
        for minutes in HORIZONS:
            for factor in FACTORS:
                result=[]
                for signal in baseline:
                    decision = int(signal['decision_server'])
                    bid,ask = signal['entry_bid'],signal['entry_ask']
                    adjusted_ask = bid+(ask-bid)*Decimal(factor)
                    real = outcomes.horizon_result(market,decision,minutes,signal['direction'],bid,adjusted_ask,point)
                    inverse = outcomes.horizon_result(market,decision,minutes,'SELL' if signal['direction']=='BUY' else 'BUY',bid,adjusted_ask,point)
                    row = dict(sample_id=signal['signal_id'],module=signal['module'],direction=signal['direction'],decision_server=decision,
                               day=signal['decision_ny_text'][:10],status=real['status'],missing_timestamps=real['missing_timestamps'],
                               first_bar_open=real['first_bar_open'],last_bar_open=real['last_bar_open'],end_exclusive=real['end_exclusive'],
                               entry_bid=str(bid),entry_ask=str(ask),scenario_ask=str(adjusted_ask),point_size=str(point),spread_model=outcomes.SPREAD_MODEL)
                    for metric in METRICS[:3]:
                        row[metric] = float(real[metric]) if real[metric] is not None else None
                        row['inverse_'+metric] = float(inverse[metric]) if inverse[metric] is not None else None
                    row['paired_delta_points'] = float(real['close_return_points']-inverse['close_return_points']) if real['status']=='COMPLETE' else None
                    result.append(row)
                scenarios[minutes,factor]=result
    return scenarios


def definitions(signals, reviewed):
    groups=[('ALL_266','TOTAL','ALL',{r['signal_id'] for r in signals})]
    for module in ('B0','PB1','B0+PB1'):
        groups.append(('ALL_266','module',module,{r['signal_id'] for r in signals if r['module']==module}))
    for direction in ('BUY','SELL'):
        groups.append(('ALL_266','direction',direction,{r['signal_id'] for r in signals if r['direction']==direction}))
    for module,direction in itertools.product(('B0','PB1','B0+PB1'),('BUY','SELL')):
        groups.append(('ALL_266','module_direction',f'{module} {direction}',{r['signal_id'] for r in signals if r['module']==module and r['direction']==direction}))
    groups.extend([('REVIEWED_50','TOTAL','ALL',{r['sample_id'] for r in reviewed}),
                   ('REVIEWED_50','manual_context','B0 RANGE',{r['sample_id'] for r in reviewed if r['module']=='B0' and r['context_class']=='RANGE'}),
                   ('REVIEWED_50','manual_context','B0 other contexts',{r['sample_id'] for r in reviewed if r['module']=='B0' and r['context_class']!='RANGE'})])
    return groups


def module_contrast(rows, comparison, reps, seed):
    """Shared day resamples for B0+PB1 minus an isolated module; no independent CIs subtraction."""
    modules = ('B0+PB1',comparison)
    data = {module:defaultdict(list) for module in modules}
    for row in rows:
        if row['module'] in modules and row['status']=='COMPLETE':data[row['module']][row['day']].append(row['close_return_points'])
    days=sorted(set(data[modules[0]])|set(data[modules[1]]))
    counts=[[len(data[module][day]) for module in modules] for day in days]
    sums=[[math.fsum(data[module][day]) for module in modules] for day in days]
    if len(days)<2 or any(sum(c[j] for c in counts)==0 for j in range(2)):return None,None,None,0
    observed = math.fsum(s[0] for s in sums)/sum(c[0] for c in counts)-math.fsum(s[1] for s in sums)/sum(c[1] for c in counts)
    rng=random.Random(seed);replicates=[]
    for _ in range(reps):
        indices=rng.choices(range(len(days)),k=len(days))
        n=[sum(counts[i][j] for i in indices) for j in range(2)]
        if min(n)>0:replicates.append(math.fsum(sums[i][0] for i in indices)/n[0]-math.fsum(sums[i][1] for i in indices)/n[1])
    return observed,quantile(replicates,.025) if replicates else None,quantile(replicates,.975) if replicates else None,len(replicates)


def assemble(scenarios, groups, bootstrap_reps, permutations, seed):
    summary=[];influence=[];cluster_rows=[];permutation_targets=[]
    for population,group,value,ids in groups:
        for minutes in HORIZONS:
            basic=dict(population=population,group=group,group_value=value,horizon_minutes=minutes)
            initial=[r for r in scenarios[minutes,'1.00'] if r['sample_id'] in ids]
            info,dependency=clusters(initial,minutes)
            first_ids={r['sample_id'] for r in nonoverlap(initial,minutes)}
            last_ids={r['sample_id'] for r in nonoverlap(initial,minutes,True)}
            for row in initial:
                cluster_rows.append(dict(basic,**{k:row[k] for k in ('sample_id','decision_server','end_exclusive','day','status')},
                    **info[row['sample_id']],nonoverlap_first=int(row['sample_id'] in first_ids),nonoverlap_last=int(row['sample_id'] in last_ids)))
            complete=[r for r in initial if r['status']=='COMPLETE']
            perm=paired_permutation(complete,permutations,stable_seed(seed,f'{population}|{group}|{value}|{minutes}|perm'))
            for factor in FACTORS:
                rows=[r for r in scenarios[minutes,factor] if r['sample_id'] in ids]
                completed=[r for r in rows if r['status']=='COMPLETE']
                label=f'{population}|{group}|{value}|{minutes}|bootstrap'
                intervals=day_bootstrap(completed,bootstrap_reps,stable_seed(seed,label))
                equal_intervals=day_bootstrap(completed,bootstrap_reps,stable_seed(seed,label),True)
                daily=defaultdict(list)
                for row in rows:daily[row['day']].append(row)
                daily_means=[]
                for day in sorted(daily):
                    present=[r for r in daily[day] if r['status']=='COMPLETE']
                    if present:daily_means.append(dict(day=day,**{m:math.fsum(r[m] for r in present)/len(present) for m in METRICS}))
                subsets=[('ALL','',rows),('NONOVERLAP_FIRST','',[r for r in rows if r['sample_id'] in first_ids]),
                         ('NONOVERLAP_LAST','',[r for r in rows if r['sample_id'] in last_ids]),('DAY_EQUAL','',daily_means)]
                subsets.extend(('DAY',day,daily[day]) for day in sorted(daily))
                for subset,day,selected in subsets:
                    present=selected if subset=='DAY_EQUAL' else [r for r in selected if r['status']=='COMPLETE']
                    for metric in METRICS:
                        stat=describe([r[metric] for r in present])
                        record=dict(basic,spread_factor=factor,subset=subset,day=day,metric=metric,unit='days' if subset=='DAY_EQUAL' else 'signals',
                                    n_total=len(selected),n_complete=len(present),n_days=len({r['day'] for r in present}),**stat,
                                    candidate='',candidate_failures='',**dependency)
                        if subset in ('ALL','DAY_EQUAL'):
                            lo,hi,valid=(intervals if subset=='ALL' else equal_intervals)[metric]
                            record.update(bootstrap_low95=lo,bootstrap_high95=hi,bootstrap_reps_valid=valid)
                        if subset=='ALL':
                            details,loo=leave_one_out(present,metric);record.update(loo)
                            lookup={r['sample_id']:r for r in details}
                            for row in selected:
                                detail=lookup.get(row['sample_id'],dict(value=row[metric],full_mean=stat['mean']))
                                influence.append(dict(basic,spread_factor=factor,metric=metric,**{k:row[k] for k in ('sample_id','day','direction','module','decision_server','status','missing_timestamps','first_bar_open','last_bar_open','end_exclusive','entry_bid','entry_ask','scenario_ask','point_size','spread_model')},
                                    **{k:v for k,v in detail.items() if k!='sample_id'},n_complete=len(present),
                                    inverse_value=row.get('inverse_'+metric),nonoverlap_first=int(row['sample_id'] in first_ids),nonoverlap_last=int(row['sample_id'] in last_ids)))
                            if metric=='paired_delta_points':
                                record.update(permutation_p_one_sided=perm[0],permutation_p_two_sided=perm[1])
                                if factor=='1.00':permutation_targets.append(record)
                        summary.append(record)
    # 12 population groups * 4 horizons = 48 hypotheses; manual subset separate.
    for population in ('ALL_266','REVIEWED_50'):
        targets=[r for r in permutation_targets if r['population']==population]
        adjusted=holm([r['permutation_p_one_sided'] for r in targets])
        correction={(r['group'],r['group_value'],r['horizon_minutes']):p for r,p in zip(targets,adjusted)}
        for row in summary:
            if row['population']==population and row['subset']=='ALL' and row['metric']=='paired_delta_points':
                row['permutation_p_holm']=correction[row['group'],row['group_value'],row['horizon_minutes']]
    for minutes in HORIZONS:
        for other in ('B0','PB1'):
            estimate,lo,hi,valid=module_contrast(scenarios[minutes,'1.00'],other,bootstrap_reps,stable_seed(seed,f'H1|{minutes}|{other}'))
            selected=[r for r in scenarios[minutes,'1.00'] if r['module'] in ('B0+PB1',other)]
            summary.append(dict(population='ALL_266',group='module_contrast',group_value=f'B0+PB1 minus {other}',horizon_minutes=minutes,
                spread_factor='1.00',subset='CONTRAST',day='',metric='close_mean_difference_points',unit='signals',
                n_total=len(selected),n_complete=sum(r['status']=='COMPLETE' for r in selected),n_days=len({r['day'] for r in selected if r['status']=='COMPLETE'}),
                mean=estimate,bootstrap_low95=lo,bootstrap_high95=hi,bootstrap_reps_valid=valid))
    candidates=evaluate_candidates(summary)
    return summary,influence,cluster_rows,candidates


def evaluate_candidates(summary):
    lookup={(r['population'],r['group'],r['group_value'],r['horizon_minutes'],r['spread_factor'],r['subset'],r['metric']):r for r in summary}
    decisions=[]
    for row in summary:
        if row.get('subset')!='ALL' or row['metric']!='close_return_points' or row['spread_factor']!='1.00':continue
        prefix=tuple(row[k] for k in ('population','group','group_value','horizon_minutes'))
        failures=[]
        def positive(value,label):
            if value is None or value<=0:failures.append(label)
        for factor in ('1.00','2.00'):
            for subset in ('ALL','NONOVERLAP_FIRST','NONOVERLAP_LAST','DAY_EQUAL'):
                check=lookup[(*prefix,factor,subset,'close_return_points')]
                for stat in ('mean','median','trimmed_mean_10','winsorized_mean_10'):
                    positive(check[stat],f'{factor}:{subset}:{stat}')
            positive(lookup[(*prefix,factor,'ALL','close_return_points')].get('loo_mean_min'),f'{factor}:LOO_min')
        positive(row.get('bootstrap_low95'),'mean_CI_low')
        paired=lookup[(*prefix,'1.00','ALL','paired_delta_points')]
        positive(paired.get('bootstrap_low95'),'paired_CI_low')
        if paired.get('permutation_p_holm') is None or paired['permutation_p_holm']>.05:failures.append('paired_Holm_p_gt_0.05')
        if row['n_complete']<20 or row['n_days']<10:failures.append('fewer_than_20_signals_or_10_days')
        if row['population']!='ALL_266':failures.append('manual_subset_exploratory_only')
        row['candidate']='CANDIDATE_FOR_INDEPENDENT_VALIDATION' if not failures else 'NOT_CANDIDATE'
        row['candidate_failures']=';'.join(failures)
        decisions.append({**dict(zip(('population','group','group_value','horizon_minutes'),prefix)),
                          'candidate':row['candidate'],'failures':failures})
    return decisions


def hypotheses(summary,candidates):
    contrasts=[r for r in summary if r['subset']=='CONTRAST']
    h1_positive=[r for r in contrasts if r['bootstrap_low95'] is not None and r['bootstrap_low95']>0]
    total_pairs=[r for r in summary if r['population']=='ALL_266' and r['group']=='TOTAL' and r['subset']=='ALL' and r['spread_factor']=='1.00' and r['metric']=='paired_delta_points']
    directional=[r['horizon_minutes'] for r in total_pairs if r['mean']>0 and r.get('bootstrap_low95') is not None and r['bootstrap_low95']>0 and r['permutation_p_holm']<=.05]
    stable=[r for r in candidates if r['candidate']=='CANDIDATE_FOR_INDEPENDENT_VALIDATION']
    return {'H1':{'statement':'B0+PB1 more stable than isolated modules','positive_module_contrasts_out_of_8':len(h1_positive),
                  'assessment':'No general stable advantage established; inspect contrasts and candidate gates.' if len(h1_positive)<8 else 'Exploratory mean contrasts positive; stability and independent validation still required.'},
            'H2':{'statement':'Emitted direction outperforms inverted direction','total_horizons_passing_clustered_tests':directional,
                  'assessment':'Exploratory evidence only at listed horizons; no overall edge claim.'},
            'H3':{'statement':'Outcomes survive extremes, overlap and spread costs','candidate_configurations':stable,
                  'assessment':'Candidates require independent validation; a positive mean alone never qualifies.'},
            'B0_RANGE':{'population':'REVIEWED_50 only','assessment':'No extrapolation to 266 without a pre-defined causal classifier.'}}


def render_report(summary,manifest):
    esc=lambda x:html.escape(str(x),quote=True)
    def number(x):return '—' if x is None or x=='' else f'{x:.3f}' if isinstance(x,float) else esc(x)
    def table(rows,fields):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(label)+'</th>' for _,label in fields)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+number(row.get(key))+'</td>' for key,_ in fields)+'</tr>' for row in rows)+'</tbody></table></div>'
    base=[r for r in summary if r['subset']=='ALL' and r['metric']=='close_return_points' and r['spread_factor']=='1.00']
    fields=[('group_value','Grupo'),('horizon_minutes','Min'),('n_complete','N'),('n_days','Días'),('mean','Media'),('median','Mediana'),('trimmed_mean_10','Recorte 10%'),('winsorized_mean_10','Winsor 10%'),('bootstrap_low95','IC95 bajo'),('bootstrap_high95','IC95 alto'),('loo_mean_min','LOO mínimo'),('candidate','Evaluación')]
    sections=[]
    for group,title in [('TOTAL','Total'),('module','Módulos'),('direction','Dirección'),('module_direction','Módulo × dirección')]:
        sections.append('<h2>'+title+'</h2>'+table([r for r in base if r['population']=='ALL_266' and r['group']==group],fields))
    pairs=[r for r in summary if r['population']=='ALL_266' and r['subset']=='ALL' and r['metric']=='paired_delta_points' and r['spread_factor']=='1.00']
    sections.append('<h2>Dirección real menos invertida</h2>'+table(pairs,[('group_value','Grupo'),('horizon_minutes','Min'),('n_complete','N'),('mean','Delta medio'),('median','Delta mediano'),('bootstrap_low95','IC95 bajo'),('bootstrap_high95','IC95 alto'),('permutation_p_one_sided','p unilateral'),('permutation_p_two_sided','p bilateral'),('permutation_p_holm','p Holm')]))
    sections.append('<h2>H1: B0+PB1 menos módulos aislados</h2>'+table([r for r in summary if r['subset']=='CONTRAST'],[('group_value','Contraste'),('horizon_minutes','Min'),('mean','Diferencia media'),('bootstrap_low95','IC95 bajo'),('bootstrap_high95','IC95 alto')]))
    stress=[r for r in summary if r['population']=='ALL_266' and r['metric']=='close_return_points' and r['group'] in ('TOTAL','module') and r['subset'] in ('ALL','NONOVERLAP_FIRST','NONOVERLAP_LAST','DAY_EQUAL')]
    sections.append('<h2>Costes, no solapamiento y medias diarias</h2>'+table(stress,[('group_value','Grupo'),('horizon_minutes','Min'),('spread_factor','Spread ×'),('subset','Subconjunto'),('unit','Unidad N'),('n_complete','N'),('mean','Media'),('median','Mediana'),('trimmed_mean_10','Recorte'),('loo_mean_min','LOO mínimo')]))
    sections.append('<h2>B0 + RANGE: solo las 50 revisadas</h2><p>No se imputa contexto ni ninguna clasificación manual a las otras 216 señales.</p>'+table([r for r in base if r['population']=='REVIEWED_50'],fields))
    dep=table([r for r in base if r['population']=='ALL_266' and r['group']=='TOTAL'],[('horizon_minutes','Min'),('n_total','Señales'),('overlapping_signals','Con solapamiento'),('overlap_pairs','Pares'),('clusters','Clusters'),('largest_cluster','Mayor cluster')])
    h=manifest['hypotheses']
    conclusions=f'<ul><li>H1: {h["H1"]["positive_module_contrasts_out_of_8"]}/8 contrastes con límite inferior positivo. Esto no prueba mayor estabilidad.</li><li>H2: horizontes totales con delta positivo, IC95 positivo y p Holm ≤ 0,05: {esc(h["H2"]["total_horizons_passing_clustered_tests"])}.</li><li>H3: {len(h["H3"]["candidate_configurations"])} configuraciones pasan todos los criterios de candidata.</li></ul>'
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
      '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'">'
      '<title>XAUUSD fase 2 robustez</title><style>body{font:15px Segoe UI,Arial;background:#101a28;color:#edf3fa;margin:0}main{max-width:1700px;margin:auto;padding:24px}h1,h2{color:#a4ceff}p,li{line-height:1.6}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid #435268;text-align:right}th{background:#24354c}td:first-child{text-align:left}.scroll{overflow:auto;margin:15px 0 30px}.warning{background:#483820;border-left:5px solid #f0c273;padding:14px}code{overflow-wrap:anywhere}</style></head><body><main>'
      '<h1>XAUUSD: fase 2 de robustez de 266 señales</h1><p class="warning">Análisis retrospectivo exploratorio en puntos. No es un backtest, PnL monetario ni prueba de edge. No diseña entradas, SL, TP o ejecución. Los artefactos aceptados de las 50 señales permanecen intactos.</p>'
      f'<p>{manifest["validation"]["signals"]} señales únicas, 4 horizontes, 4 escenarios de spread. Semilla {manifest["parameters"]["seed"]}; {manifest["parameters"]["bootstrap_reps"]} remuestras por día NY y {manifest["parameters"]["permutations"]} permutaciones pareadas por día.</p>'
      '<h2>Hipótesis y evaluación</h2>'+conclusions+
      '<p>Una candidata exige signo positivo en media, mediana, recorte y winsorización; también en ambos subconjuntos no solapados y medias diarias, con spread actual y ×2. Ninguna eliminación individual puede volver negativa la media. Además: al menos 20 señales y 10 días, IC95 de media y delta real−inversa por encima de cero, y p unilateral Holm ≤0,05. No se considera edge; requiere datos independientes.</p>'
      '<h2>Dependencia temporal</h2>'+dep+
      '<p>Intervalos semiabiertos [decisión, decisión+horizonte). Clusters: componentes conexas de intervalos que se intersectan; tocar extremos no es solaparse. Subconjuntos desde inicio y final usan solo timestamps. DAY conserva cada día; DAY_EQUAL da el mismo peso a cada media diaria, no suma PnL.</p>'
      '<h2>Métodos y límites</h2><p>Se reutilizan velas M5 canónicas, exclusión de la señal y ENTRY_SPREAD_CONSTANT. BUY entra en ask; SELL usa bid y aproxima ask futuro. En costes se fija bid y ask escenario = bid + spread observado × factor, para ambas direcciones. Una inversión usa exactamente las mismas barras y costes.</p>'
      '<p>Recorte y winsorización: floor(0,10·N) por cada cola. Percentiles lineales (N−1)p. Bootstrap percentil 95% remuestrea días NY completos, preservando dependencia intradía y ponderación por señal; DAY_EQUAL remuestrea medias diarias. Menos de dos días: sin IC ni prueba. Dependencia entre días no resuelta.</p>'
      '<p>Permutación: intercambia real/invertida para todas las señales de un día a la vez, suponiendo intercambiabilidad/simetría de deltas por día. Corrección Monte Carlo (1+extremos)/(B+1). Holm en 48 pruebas de población completa y una familia aparte de 12 pruebas manuales. IC individuales y contrastes H1 no simultáneos. Selección retrospectiva, grupos pequeños y multiplicidad limitan la inferencia.</p>'
      '<p>MFE/MAE, percentiles, proporciones, IC, resultados diarios y LOO completos figuran en los CSV. INCOMPLETE se excluye solo de su horizonte sin convertirse en cero. Grupos pequeños y recortes que eliminan cero observaciones requieren cautela. No se conocen spread futuro real, costes de ejecución ni orden intrabar.</p>'+
      ''.join(sections)+'</main></body></html>')


def write_table(path,columns,rows):
    def value(x):
        if x is None:return ''
        if isinstance(x,float):
            require(math.isfinite(x),0,'estadística no finita')
            return format(x,'.12g') if x else '0'
        return str(x)
    scanner.write_csv(path,columns,[{key:value(row.get(key)) for key in columns} for row in rows])


def analyze(input_path,sample_path,annotations_path,output_dir,point_size='0.01',bootstrap_reps=2000,permutations=10000,seed=20260919,phase1_dir=None,expected_signals=266):
    require(bootstrap_reps>=100 and permutations>=100,0,'se requieren al menos 100 remuestras/permutaciones')
    point=outcomes.decimal_number(point_size)
    require(point==Decimal('.01'),0,'point-size debe ser 0.01')
    paths={k:Path(v).resolve() for k,v in [('scanner',input_path),('sample',sample_path),('annotations',annotations_path)]}
    require(len(set(paths.values()))==3,0,'entradas deben ser distintas')
    arg=Path(output_dir);require(not arg.is_symlink(),0,'destino enlazado')
    output=arg.resolve()
    require(all(output!=p and output not in p.parents for p in paths.values()),0,'entrada dentro del destino')
    if output.exists():require(output.is_dir() and all(p.name in OUTPUT_NAMES and p.is_file() and not p.is_symlink() for p in output.iterdir()),0,'destino contiene archivos ajenos')
    protected={}
    if phase1_dir is not None:
        phase1=Path(phase1_dir).resolve()
        require(output!=phase1 and output not in phase1.parents and phase1 not in output.parents,0,'destino invade fase 1')
        protected={phase1/name:scanner.source_sha256(phase1/name) for name in outcomes.OUTPUT_NAMES}
    hashes={role:{'name':path.name,'sha256':scanner.source_sha256(path)} for role,path in paths.items()}
    signals,validation,sensitive=scanner.collect(paths['scanner'])
    require(len(signals)==expected_signals,0,f'se requieren exactamente {expected_signals} señales aceptadas')
    _,reviewed,review_counts=outcomes.join_reviews(paths['sample'],paths['annotations'])
    outcomes.validate_sample_source(reviewed,signals)
    market,entries,bar_counts=outcomes.reconstruct_market(paths['scanner'],{int(r['decision_server']) for r in signals})
    scenarios=scenario_rows(signals,market,entries,point)
    groups=definitions(signals,reviewed)
    summary,influence,cluster_rows,candidates=assemble(scenarios,groups,bootstrap_reps,permutations,seed)
    coverage={str(m):{'n_total':len(signals),'n_complete':sum(r['status']=='COMPLETE' for r in scenarios[m,'1.00'])} for m in HORIZONS}
    manifest={'version':'1.0','python_version':sys.version.split()[0],'inputs':hashes,
        'protected_phase1_sha256':{p.name:v for p,v in protected.items()},
        'parameters':{'point_size':str(point),'horizons':list(HORIZONS),'spread_factors':list(FACTORS),'spread_model':outcomes.SPREAD_MODEL,
            'bootstrap_reps':bootstrap_reps,'permutations':permutations,'seed':seed,'day':'decision_ny calendar date',
            'bootstrap':'whole days with replacement, percentile 95%, ratio sums/counts; equal-day variant separate',
            'permutation':'paired day-block sign flips; +1 correction; Holm families 48 all / 12 reviewed',
            'trim':'floor(n*0.10) per tail','nonoverlap':'earliest first and latest first; timestamps only',
            'arithmetic':'Decimal 40 for prices; binary64 statistics; CSV 12 significant digits'},
        'coverage':coverage,'validation':dict(signals=len(signals),reviewed=review_counts['joined_signals'],unannotated=len(signals)-len(reviewed),
            original_rows=validation['total_rows'],**bar_counts),
        'hypotheses':hypotheses(summary,candidates),'candidates':candidates,
        'code_sha256':{p.name:scanner.source_sha256(p) for p in (Path(__file__),Path(outcomes.__file__),Path(scanner.__file__))},
        'output_row_counts':{'summary':len(summary),'influence':len(influence),'clusters':len(cluster_rows)},
        'files':[],'self_hash':'Manifest excluded from its own hash list; no wall-clock timestamp.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.robustness-stage-',dir=output.parent) as directory:
        stage=Path(directory).resolve();require(stage.parent==output.parent and stage!=output,0,'directorio temporal incorrecto')
        write_table(stage/OUTPUT_NAMES[0],SUMMARY_COLUMNS,summary)
        write_table(stage/OUTPUT_NAMES[1],INFLUENCE_COLUMNS,influence)
        write_table(stage/OUTPUT_NAMES[2],CLUSTER_COLUMNS,cluster_rows)
        (stage/OUTPUT_NAMES[3]).write_text(render_report(summary,manifest),encoding='utf-8',newline='\n')
        manifest['files']=[{'name':name,'sha256':scanner.source_sha256(stage/name)} for name in OUTPUT_NAMES[:-1]]
        (stage/OUTPUT_NAMES[4]).write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
        for p in stage.iterdir():
            text=p.read_text(encoding='utf-8').casefold()
            require(not any(token.casefold() in text for token in sensitive if token),0,'output contendría un token sensible')
        require(all(scanner.source_sha256(p)==hashes[k]['sha256'] for k,p in paths.items()),0,'entrada cambió durante el análisis')
        require(all(scanner.source_sha256(p)==v for p,v in protected.items()),0,'artefacto de fase 1 cambió')
        scanner.publish_directory(stage,output)
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('input','sample','annotations','output-dir','phase1-dir'):parser.add_argument('--'+field,required=True)
    parser.add_argument('--point-size',default='0.01')
    parser.add_argument('--bootstrap-reps',type=int,default=2000)
    parser.add_argument('--permutations',type=int,default=10000)
    parser.add_argument('--seed',type=int,default=20260919)
    args=parser.parse_args(argv)
    try:
        output=scanner.repository_path(args.output_dir).resolve()
        require(output.parent==scanner.ARTIFACT_ROOT.resolve() and bool(re.fullmatch(r'[A-Za-z0-9_-]+',output.name)),0,'output-dir debe ser artifacts/scanner_analysis/<experimento>')
        result=analyze(scanner.repository_path(args.input),scanner.repository_path(args.sample),scanner.repository_path(args.annotations),output,
            args.point_size,args.bootstrap_reps,args.permutations,args.seed,scanner.repository_path(args.phase1_dir))
    except (ValidationError,csv.Error,UnicodeError) as error:
        print('ERROR: '+(str(error) if isinstance(error,ValidationError) else 'CSV o codificación inválidos'),file=sys.stderr);return 2
    except OSError:
        print('ERROR: no se pudo leer una entrada o publicar las salidas.',file=sys.stderr);return 3
    print(f'OK: {result["validation"]["signals"]} señales; cobertura {result["coverage"]}; candidatas {len(result["hypotheses"]["H3"]["candidate_configurations"])}.')
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
