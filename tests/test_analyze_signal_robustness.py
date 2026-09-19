"""Robustness methods: known values, blocked resampling, causal bounds and byte reproducibility."""
import csv
from decimal import Decimal as D
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from tools import analyze_signal_robustness as robust
import test_analyze_signal_outcomes as fixtures


def row(index,stamp=600,value=10,day='2026-06-10'):
    return dict(sample_id=f'SIG-{index:06}',decision_server=stamp,day=day,module='B0',direction='BUY',
                status='COMPLETE',**{metric:float(value) for metric in robust.METRICS})


def table(path):
    with path.open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))


class MethodTests(unittest.TestCase):
    def test_trim_and_winsor_are_ten_percent_each_tail(self):
        result=robust.describe([-1000]+list(range(1,19))+[1000])
        self.assertEqual(result['trim_each_tail_n'],2)
        self.assertEqual(result['trimmed_mean_10'],9.5)
        self.assertEqual(result['winsorized_mean_10'],9.5)
        self.assertEqual(result['median'],9.5)
        self.assertEqual(result['p25'],4.75)
        self.assertEqual(result['positive_proportion'],19/20)

    def test_empty_and_small_samples_are_explicit(self):
        self.assertIsNone(robust.describe([])['mean'])
        self.assertEqual(robust.describe([3])['trim_each_tail_n'],0)
        self.assertEqual(robust.day_bootstrap([row(1)],100,1)['close_return_points'],(None,None,0))
        self.assertEqual(robust.paired_permutation([row(1)],100,1),(None,None))
        self.assertIsNone(robust.leave_one_out([row(1)],'close_return_points')[1]['loo_mean_min'])

    def test_interval_clusters_transitive_and_touching_boundaries(self):
        rows=[row(1,600),row(2,1200),row(3,1800),row(4,2700)]
        info,stats=robust.clusters(rows,15)
        self.assertEqual(stats,dict(overlapping_signals=3,overlap_pairs=2,clusters=2,largest_cluster=3))
        self.assertEqual(info['SIG-000002']['direct_overlaps'],2)
        self.assertEqual(info['SIG-000001']['cluster_id'],info['SIG-000003']['cluster_id'])
        self.assertNotEqual(info['SIG-000003']['cluster_id'],info['SIG-000004']['cluster_id'])

    def test_nonoverlap_both_orders_never_uses_outcomes(self):
        rows=[row(i,t,value=(-1)**i*10000) for i,t in enumerate((600,900,1500,1800),1)]
        first=robust.nonoverlap(rows,15)
        last=robust.nonoverlap(rows,15,True)
        self.assertEqual([r['decision_server'] for r in first],[600,1500])
        self.assertEqual([r['decision_server'] for r in last],[900,1800])
        for subset in (first,last):
            self.assertTrue(all(a['decision_server']+900<=b['decision_server'] for a,b in zip(subset,subset[1:])))
        for r in rows:r['close_return_points']*=-1
        self.assertEqual([r['sample_id'] for r in first],[r['sample_id'] for r in robust.nonoverlap(rows,15)])

    def test_bootstrap_whole_day_preserves_within_day_cancellation(self):
        rows=[row(1,value=-100),row(2,value=100),row(3,value=-500,day='2026-06-11'),row(4,value=500,day='2026-06-11')]
        for interval in robust.day_bootstrap(rows,200,42).values():self.assertEqual(interval,(0,0,200))
        self.assertEqual(robust.paired_permutation(rows,200,42),(1,1))

    def test_bootstrap_matches_independent_day_resampling(self):
        rows=[row(1,value=2),row(2,value=4),row(3,value=20,day='2026-06-11')]
        rng=random.Random(5);samples=[];equal=[]
        for _ in range(300):
            draw=rng.choices(range(2),k=2)
            samples.append(sum((6,20)[i] for i in draw)/sum((2,1)[i] for i in draw))
            equal.append(sum((3,20)[i] for i in draw)/2)
        self.assertEqual(robust.day_bootstrap(rows,300,5)['close_return_points'],(robust.quantile(samples,.025),robust.quantile(samples,.975),300))
        self.assertEqual(robust.day_bootstrap(rows,300,5,True)['close_return_points'],(robust.quantile(equal,.025),robust.quantile(equal,.975),300))

    def test_permutation_detects_consistent_difference_and_is_seeded(self):
        rows=[row(i,value=10,day=f'2026-06-{i+1:02}') for i in range(20)]
        result=robust.paired_permutation(rows,2000,42)
        self.assertEqual(result,robust.paired_permutation(rows,2000,42))
        self.assertLess(result[0],.01)
        self.assertGreater(result[0],0)
        for r in rows:r['paired_delta_points']=-10
        self.assertEqual(robust.paired_permutation(rows,2000,42)[0],1)

    def test_holm_adjustment(self):
        self.assertEqual(robust.holm([.01,.04,.03,None]),[.03,.06,.06,None])

    def test_loo_identifies_one_signal_driving_positive_mean(self):
        rows=[row(1,value=-1),row(2,value=-1),row(3,value=100)]
        details,stats=robust.leave_one_out(rows,'close_return_points')
        self.assertEqual(stats['most_influential_id'],'SIG-000003')
        self.assertEqual(stats['loo_mean_min'],-1)
        self.assertEqual(next(r for r in details if r['sample_id']=='SIG-000003')['sign_flip'],1)

    def test_causal_bounds_inverse_and_spread_costs(self):
        signals=[dict(signal_id='S1',decision_server=600,signal_open_server=300,direction='BUY',module='B0',decision_ny_text='2026-06-10 09:00:00'),
                 dict(signal_id='S2',decision_server=600,signal_open_server=300,direction='SELL',module='PB1',decision_ny_text='2026-06-10 09:00:00')]
        market={t:tuple(map(D,('100','104','97','102'))) for t in range(600,7800,300)}
        market[300]=tuple(map(D,('100','99999','1','100')))
        market[7800]=tuple(map(D,('100','99999','1','100')))
        entries={600:dict(bid='100',ask='100.10',spread_points='10',delay_seconds='0',observed_server='600')}
        scenarios=robust.scenario_rows(signals,market,entries,D('.01'))
        for h in robust.HORIZONS:
            for factor in robust.FACTORS:
                buy,sell=scenarios[h,factor]
                self.assertAlmostEqual(buy['close_return_points'],200-10*float(factor))
                self.assertAlmostEqual(sell['close_return_points'],-200-10*float(factor))
                self.assertEqual(buy['inverse_close_return_points'],sell['close_return_points'])
                self.assertEqual(buy['paired_delta_points'],400)
                self.assertEqual(sell['paired_delta_points'],-400)
                self.assertEqual(buy['mfe_points'],400-10*float(factor))
                self.assertEqual(sell['mfe_points'],300-10*float(factor))
                self.assertEqual(buy['first_bar_open'],600)
                self.assertEqual(buy['end_exclusive'],600+h*60)
        del market[600]
        self.assertEqual(robust.scenario_rows(signals,market,entries,D('.01'))[15,'1.00'][0]['status'],'INCOMPLETE')

    def test_manual_labels_never_assigned_to_unreviewed(self):
        signals=[dict(signal_id=f'S{i}',module='B0',direction='BUY') for i in range(3)]
        reviewed=[dict(sample_id='S0',module='B0',context_class='RANGE')]
        definitions=robust.definitions(signals,reviewed)
        self.assertEqual(next(g[3] for g in definitions if g[2]=='B0 RANGE'),{'S0'})
        self.assertEqual(next(g[3] for g in definitions if g[0]=='ALL_266' and g[1]=='TOTAL'),{'S0','S1','S2'})
        self.assertTrue(all('context_class' not in r for r in signals))

    def test_module_contrast_uses_common_day_draws(self):
        rows=[]
        for i in range(4):
            a=row(i*2,value=i*100,day=f'2026-06-{i+1:02}');a['module']='B0'
            b=row(i*2+1,value=i*100+10,day=a['day']);b['module']='B0+PB1'
            rows.extend([a,b])
        self.assertEqual(robust.module_contrast(rows,'B0',100,9),(10,10,10,100))

    def test_candidate_rejects_positive_mean_with_negative_robust_checks(self):
        summary=[]
        for factor in ('1.00','2.00'):
            for subset in ('ALL','NONOVERLAP_FIRST','NONOVERLAP_LAST','DAY_EQUAL'):
                summary.append(dict(population='ALL_266',group='TOTAL',group_value='ALL',horizon_minutes=15,spread_factor=factor,subset=subset,
                    metric='close_return_points',mean=100,median=10,trimmed_mean_10=10,winsorized_mean_10=10,loo_mean_min=1,bootstrap_low95=1,n_complete=30,n_days=20))
        summary.append(dict(population='ALL_266',group='TOTAL',group_value='ALL',horizon_minutes=15,spread_factor='1.00',subset='ALL',metric='paired_delta_points',bootstrap_low95=1,permutation_p_holm=.01))
        self.assertEqual(robust.evaluate_candidates(summary)[0]['candidate'],'CANDIDATE_FOR_INDEPENDENT_VALIDATION')
        for field,subset in [('median','ALL'),('trimmed_mean_10','ALL'),('mean','NONOVERLAP_FIRST'),('mean','NONOVERLAP_LAST'),('loo_mean_min','ALL')]:
            target=next(r for r in summary if r['spread_factor']=='2.00' and r['subset']==subset and r['metric']=='close_return_points')
            original=target[field];target[field]=-1
            self.assertEqual(robust.evaluate_candidates(summary)[0]['candidate'],'NOT_CANDIDATE')
            target[field]=original


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.OutcomeTests.setUpClass()
    @classmethod
    def tearDownClass(cls):fixtures.OutcomeTests.tearDownClass()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.paths=[self.root/name for name in ('scanner.csv','sample.csv','annotations.csv')]
        for path,data in zip(self.paths,(fixtures.OutcomeTests.source_bytes,fixtures.OutcomeTests.sample_bytes,fixtures.OutcomeTests.annotation_bytes)):path.write_bytes(data)
        self.output=self.root/'robustness'
        self.phase1=self.root/'phase1';self.phase1.mkdir()
        for name in robust.outcomes.OUTPUT_NAMES:(self.phase1/name).write_bytes(b'accepted artifact')
    def tearDown(self):self.temp.cleanup()
    def run_analysis(self):
        return robust.analyze(*self.paths,self.output,bootstrap_reps=100,permutations=100,phase1_dir=self.phase1,expected_signals=50)

    def test_pipeline_byte_reproduction_integrity_and_all_scenarios(self):
        before={p:p.read_bytes() for p in self.paths+list(self.phase1.iterdir())}
        manifest=self.run_analysis()
        first={p.name:p.read_bytes() for p in self.output.iterdir()}
        self.run_analysis()
        self.assertEqual(first,{p.name:p.read_bytes() for p in self.output.iterdir()})
        self.assertEqual(set(first),set(robust.OUTPUT_NAMES))
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
        rows=table(self.output/'robustness_summary.csv')
        self.assertEqual({r['spread_factor'] for r in rows},set(robust.FACTORS))
        total=[r for r in rows if r['population']=='ALL_266' and r['group']=='TOTAL' and r['subset']=='ALL' and r['metric']=='close_return_points']
        self.assertEqual(len(total),16)
        self.assertTrue(all(r['n_complete']=='50' for r in total))
        influence=table(self.output/'signal_influence.csv')
        canonical=[r for r in influence if r['population']=='ALL_266' and r['group']=='TOTAL' and r['horizon_minutes']=='15' and r['spread_factor']=='1.00' and r['metric']=='close_return_points']
        self.assertEqual(len(canonical),50)
        self.assertTrue(all(int(r['first_bar_open'])==int(r['decision_server']) for r in canonical))
        for item in manifest['files']:self.assertEqual(item['sha256'],robust.scanner.source_sha256(self.output/item['name']))
        self.assertTrue(all('context_class' not in r for r in canonical))

    def test_production_count_requires_266(self):
        with self.assertRaisesRegex(robust.ValidationError,'266'):
            robust.analyze(*self.paths,self.output,bootstrap_reps=100,permutations=100)
        self.assertFalse(self.output.exists())

    def test_accepted_phase1_cannot_be_destination(self):
        self.output=self.phase1
        with self.assertRaises(robust.ValidationError):self.run_analysis()
        self.assertTrue(all(p.read_bytes()==b'accepted artifact' for p in self.phase1.iterdir()))

    def test_invalid_reviews_abort_without_publication(self):
        annotations=table(self.paths[2]);annotations[0]['reviewer_decision']='PENDING'
        robust.scanner.write_csv(self.paths[2],tuple(annotations[0]),annotations)
        with self.assertRaises(robust.ValidationError):self.run_analysis()
        self.assertFalse(self.output.exists())

    def test_conflicting_canonical_bar_is_rejected(self):
        rows=table(self.paths[0]);parts=rows[1]['m5_window'].split(';');bar=parts[0].split(':');bar[2]=str(D(bar[2])+D('.01'));parts[0]=':'.join(bar)
        rows[1]['m5_window']=';'.join(parts);rows[1]['checksum']=robust.scanner.checksum(rows[1])
        robust.scanner.write_csv(self.paths[0],robust.scanner.COLUMNS,rows)
        with self.assertRaisesRegex(robust.ValidationError,'OHLC conflictivos'):self.run_analysis()

    def test_incomplete_horizons_remain_missing_in_summaries(self):
        signals,_,_=robust.scanner.collect(self.paths[0])
        market,entries,_=robust.outcomes.reconstruct_market(self.paths[0],{r['decision_server'] for r in signals})
        del market[signals[0]['decision_server']]
        scenarios=robust.scenario_rows(signals,market,entries,D('.01'))
        summary,influence,_,_=robust.assemble(scenarios,[('ALL_266','TOTAL','ALL',{r['signal_id'] for r in signals})],100,100,42)
        first=next(r for r in influence if r['sample_id']==signals[0]['signal_id'] and r['horizon_minutes']==15 and r['metric']=='close_return_points')
        self.assertEqual(first['status'],'INCOMPLETE');self.assertIsNone(first['value'])
        total=next(r for r in summary if r['subset']=='ALL' and r['metric']=='close_return_points' and r['horizon_minutes']==15 and r['spread_factor']=='1.00')
        valid=[r['close_return_points'] for r in scenarios[15,'1.00'] if r['status']=='COMPLETE']
        self.assertEqual(total['n_complete'],len(valid));self.assertEqual(total['mean'],math.fsum(valid)/len(valid))


class RealRobustnessTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('ROBUSTNESS_REAL_TEST')=='1','Set ROBUSTNESS_REAL_TEST=1 and the three explicit source paths')
    def test_real_266_and_phase1_preservation(self):
        paths=[Path(os.environ[k]) for k in ('SCANNER_CSV_PATH','SCANNER_SAMPLE_PATH','SCANNER_ANNOTATIONS_PATH')]
        phase1=ROOT/'artifacts/scanner_analysis/smoke_20260610_20260814_v2_outcomes'
        before={p:robust.scanner.source_sha256(p) for p in paths+list(phase1.iterdir())}
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'robustness'
            result=robust.analyze(*paths,output,bootstrap_reps=100,permutations=100,phase1_dir=phase1)
            self.assertEqual(result['validation']['signals'],266)
            self.assertEqual(result['validation']['reviewed'],50)
            self.assertEqual(result['validation']['unannotated'],216)
            for coverage in result['coverage'].values():self.assertEqual(coverage['n_total'],266)
        self.assertEqual(before,{p:robust.scanner.source_sha256(p) for p in before})


if __name__=='__main__':unittest.main()
