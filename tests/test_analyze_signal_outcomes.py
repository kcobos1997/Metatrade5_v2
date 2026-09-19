"""Known-price fixtures, strict 50-row joins, integrity and deterministic outcome publication."""
import csv
from collections import Counter
from decimal import Decimal as D
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tools import analyze_signal_outcomes as outcome
from test_render_signal_review import source_row
scanner=outcome.scanner


def write(path,columns,rows):
    scanner.write_csv(path,tuple(columns),rows)


def load(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


class OutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory()
        cls.fixture_root=Path(cls.fixture.name)
        source=cls.fixture_root/'scanner.csv'
        rows=[]
        lanes=(('b0_buy',),('pb1_sell',),('b0_buy','pb1_buy'),('b0_sell',),('pb1_buy',),('b0_sell','pb1_sell'))
        count=0
        for day in range(2):
            for index in range(60):
                selected=5 <= index < 30
                row=source_row(day*288+index,lanes[count%6] if selected else ())
                if selected: count+=1
                hour=(int(row['decision_ny'])%86400)//3600
                row['session']='IN' if 8<=hour<12 else 'OUT'
                row['checksum']=scanner.checksum(row)
                rows.append(row)
        write(source,scanner.COLUMNS,rows)
        signals,_,_=scanner.collect(source)
        cls.source_bytes=source.read_bytes()
        samples=[dict(r,review_status='PENDING',structure_quality='',signal_quality='',review_notes='') for r in signals]
        sample=cls.fixture_root/'sample.csv'
        write(sample,scanner.REDUCED_COLUMNS+scanner.REVIEW_COLUMNS,samples)
        cls.sample_bytes=sample.read_bytes()
        annotations=[]
        for index,row in enumerate(samples):
            annotations.append(dict(sample_id=row['signal_id'],signal_open_server_text=row['signal_open_server_text'],
                bar_time_epoch=str(row['signal_open_server']),decision_ny_text=row['decision_ny_text'],
                direction=row['direction'],module=row['module'],status='OK',validation_errors='',
                chart_quality='CLEAR',signal_alignment=('ALIGNED','UNCLEAR','MISALIGNED')[index%3],
                context_class=('TREND','RANGE','TRANSITION')[index%3],reviewer_decision=('VALID','QUESTIONABLE','REJECTED')[index%3],
                reviewer_notes='Nota, "revisada"\ncon acento ñ'))
        annotated=cls.fixture_root/'annotations.csv'
        write(annotated,outcome.ANNOTATION_COLUMNS,annotations)
        cls.annotation_bytes=annotated.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.source,self.sample,self.annotations=(self.root/name for name in ('scanner.csv','sample.csv','annotations.csv'))
        for path,data in ((self.source,self.source_bytes),(self.sample,self.sample_bytes),(self.annotations,self.annotation_bytes)):
            path.write_bytes(data)
        self.output=self.root/'outcomes'

    def tearDown(self):
        self.temporary.cleanup()

    def join(self):
        return outcome.join_reviews(self.sample,self.annotations)[1]

    def analyze(self):
        return outcome.analyze(self.source,self.sample,self.annotations,self.output,'0.01')

    def change_annotation(self,field,value,index=0):
        rows=load(self.annotations);rows[index][field]=value
        write(self.annotations,list(rows[0]),rows)

    def test_exact_50_join_order_and_all_decisions_retained(self):
        rows=load(self.annotations);rows.reverse()
        write(self.annotations,list(rows[0]),rows)
        joined=self.join()
        self.assertEqual(len(joined),50)
        self.assertEqual([r['sample_id'] for r in joined],[r['signal_id'] for r in load(self.sample)])
        self.assertEqual({r['reviewer_decision'] for r in joined},{'VALID','QUESTIONABLE','REJECTED'})
        self.assertEqual(joined[0]['reviewer_notes'],'Nota, "revisada"\ncon acento ñ')

    def test_reject_49_or_51_annotations(self):
        rows=load(self.annotations)
        for variant in (rows[:-1],rows+[dict(rows[0])]):
            write(self.annotations,list(rows[0]),variant)
            with self.assertRaisesRegex(outcome.ValidationError,'exactamente 50'):self.join()

    def test_reject_duplicate_ids(self):
        self.change_annotation('sample_id',load(self.annotations)[1]['sample_id'])
        with self.assertRaisesRegex(outcome.ValidationError,'duplicado'):self.join()

    def test_reject_duplicate_sample_ids(self):
        rows=load(self.sample);rows[0]['signal_id']=rows[1]['signal_id']
        write(self.sample,list(rows[0]),rows)
        with self.assertRaisesRegex(outcome.ValidationError,'duplicado'):self.join()

    def test_reject_unmatched_id(self):
        self.change_annotation('sample_id','SIG-999999')
        with self.assertRaisesRegex(outcome.ValidationError,'uno a uno'):self.join()

    def test_reject_blank_pending_unknown_and_errors(self):
        cases=[(field,value) for field in outcome.CLASSIFICATIONS for value in ('','PENDING','UNKNOWN')]
        cases += [('reviewer_notes',' \n'),('status','ERROR'),('status','INCOMPLETE'),('validation_errors','OHLC mismatch')]
        for field,value in cases:
            with self.subTest(field=field,value=value):
                self.annotations.write_bytes(self.annotation_bytes)
                self.change_annotation(field,value)
                with self.assertRaises(outcome.ValidationError):self.join()

    def test_optional_completed_false_rejected(self):
        rows=load(self.annotations)
        for row in rows:row['completed']='false'
        write(self.annotations,list(rows[0]),rows)
        with self.assertRaisesRegex(outcome.ValidationError,'no completada'):self.join()

    def test_reject_direction_module_and_timestamp_mismatches(self):
        for field,value in [('direction','SELL'),('module','PB1'),('bar_time_epoch','1'),
                            ('signal_open_server_text','2026-01-01 00:00:00'),('decision_ny_text','bad')]:
            with self.subTest(field=field):
                self.annotations.write_bytes(self.annotation_bytes)
                self.change_annotation(field,value)
                with self.assertRaises(outcome.ValidationError):self.join()

    def test_source_sample_quote_disagreement(self):
        joined=self.join();joined[0]['ask']='9999'
        accepted,_,_=scanner.collect(self.source)
        with self.assertRaisesRegex(outcome.ValidationError,'ask'):outcome.validate_sample_source(joined,accepted)

    def test_invalid_point_and_late_entry_rejected(self):
        with self.assertRaisesRegex(outcome.ValidationError,'point-size'):
            outcome.analyze(self.source,self.sample,self.annotations,self.output,'1')
        joined=self.join();decision=int(joined[0]['decision_server'])
        entries={decision:dict(bid='100',ask='100.1',spread_points='10',delay_seconds='1',observed_server=str(decision+1))}
        with self.assertRaisesRegex(outcome.ValidationError,'tardía'):
            outcome.compute_outcomes(joined[:1],{},entries,D('.01'))
        entries[decision].update(delay_seconds='0',observed_server=str(decision),spread_points='20')
        with self.assertRaisesRegex(outcome.ValidationError,'spread observado'):
            outcome.compute_outcomes(joined[:1],{},entries,D('.01'))

    def test_invalid_ohlc_finite_positive_consistent(self):
        for values in ('100:NaN:99:100','100:Infinity:99:100','0:101:99:100','100:99:98:100','100:101:101:100'):
            with self.subTest(values=values),self.assertRaises(outcome.ValidationError):
                outcome.parse_window('300:'+values,600)

    def test_conflicting_timestamp_explicit_failure(self):
        rows=load(self.source)
        pieces=rows[1]['m5_window'].split(';')
        fields=pieces[0].split(':');fields[2]=str(D(fields[2])+D('.01'));pieces[0]=':'.join(fields)
        rows[1]['m5_window']=';'.join(pieces);rows[1]['checksum']=scanner.checksum(rows[1])
        write(self.source,scanner.COLUMNS,rows)
        with self.assertRaisesRegex(outcome.ValidationError,'OHLC conflictivos.*timestamp'):
            outcome.reconstruct_market(self.source,set())

    def test_identical_deduplication_and_session_gaps(self):
        bars,_,counts=outcome.reconstruct_market(self.source,set())
        self.assertEqual(counts['bar_occurrences'],len(bars)+counts['identical_bar_repetitions'])
        self.assertGreater(counts['identical_bar_repetitions'],0)
        self.assertEqual(counts['conflicting_bars'],0)
        window=outcome.parse_window('300:100:101:99:100;900:100:101:99:100',1200)
        self.assertEqual([r[0] for r in window],[300,900])

    def test_incomplete_excluded_per_horizon_without_zero_fill(self):
        bars={stamp:(D('100'),D('102'),D('99'),D('101')) for stamp in range(600,7800,300)}
        del bars[1500]  # Outside 15m, inside every larger horizon.
        row=dict(module='B0',direction='BUY',reviewer_decision='REJECTED',signal_alignment='MISALIGNED',context_class='RANGE')
        for m in outcome.HORIZONS:
            row.update({f'h{m}_{key}':value for key,value in outcome.horizon_result(bars,600,m,'BUY',D('100'),D('100.1'),D('.01')).items()})
        self.assertEqual(row['h15_status'],'COMPLETE')
        self.assertEqual(row['h30_missing_timestamps'],'1500')
        self.assertEqual(row['h30_bar_count'],5)
        self.assertIsNone(row['h30_mfe_points'])
        totals=[r for r in outcome.summarize([row]) if r['group_by']=='TOTAL']
        self.assertEqual([r['n_complete'] for r in totals],[1,0,0,0])
        self.assertIsNone(totals[1]['mfe_points_mean'])
        self.assertIsNone(totals[1]['positive_close_proportion'])

    def test_summary_known_statistics_and_empty_groups(self):
        rows=[]
        for number in (D('-2'),D('0'),D('2'),D('4')):
            row=dict(module='B0',direction='BUY',reviewer_decision='VALID',signal_alignment='ALIGNED',context_class='TREND')
            for minutes in outcome.HORIZONS:
                row[f'h{minutes}_status']='COMPLETE'
                for metric in outcome.METRICS:row[f'h{minutes}_{metric}']=number if metric=='close_return_points' else abs(number)
            rows.append(row)
        total=outcome.summarize(rows)[0]
        self.assertEqual(total['close_return_points_mean'],D('1'))
        self.assertEqual(total['close_return_points_median'],D('1'))
        self.assertEqual(total['close_return_points_p25'],D('-.5'))
        self.assertEqual(total['close_return_points_p75'],D('2.5'))
        self.assertEqual(total['positive_close_proportion'],D('.5'))
        empty=next(r for r in outcome.summarize(rows) if r['group_by']=='module' and r['group_value']=='PB1')
        self.assertEqual(empty['n_total'],0)
        self.assertIsNone(empty['mae_points_mean'])

    def test_publication_50_rows_determinism_manifest_and_input_integrity(self):
        inputs=[p.read_bytes() for p in (self.source,self.sample,self.annotations)]
        manifest=self.analyze()
        first={p.name:p.read_bytes() for p in self.output.iterdir()}
        self.analyze()
        self.assertEqual(first,{p.name:p.read_bytes() for p in self.output.iterdir()})
        self.assertEqual(set(first),set(outcome.OUTPUT_NAMES))
        rows=load(self.output/'signal_outcomes.csv')
        self.assertEqual(len(rows),50)
        self.assertEqual([r['sample_id'] for r in rows],[r['signal_id'] for r in load(self.sample)])
        self.assertEqual(inputs,[p.read_bytes() for p in (self.source,self.sample,self.annotations)])
        self.assertEqual(manifest['validation_counts']['joined_signals'],50)
        for m in outcome.HORIZONS:
            self.assertEqual(manifest['coverage'][str(m)]['n_complete'],50)
        for item in manifest['files']:
            self.assertEqual(item['sha256'],scanner.source_sha256(self.output/item['name']))
        for row in rows:
            self.assertEqual(row['entry_price'],row['entry_ask'] if row['direction']=='BUY' else row['entry_bid'])

    def test_invalid_inputs_preserve_previous_output(self):
        self.output.mkdir();sentinel=self.output/outcome.OUTPUT_NAMES[0];sentinel.write_bytes(b'previous')
        self.change_annotation('reviewer_decision','PENDING')
        with self.assertRaises(outcome.ValidationError):self.analyze()
        self.assertEqual(sentinel.read_bytes(),b'previous')

    def test_unrelated_files_and_input_destination_rejected(self):
        self.output.mkdir();(self.output/'keep.txt').write_text('keep')
        with self.assertRaisesRegex(outcome.ValidationError,'ajenos'):self.analyze()
        with self.assertRaisesRegex(outcome.ValidationError,'entrada dentro'):
            outcome.analyze(self.source,self.sample,self.annotations,self.root)
        self.assertEqual((self.output/'keep.txt').read_text(),'keep')

    def test_changed_input_aborts_publication(self):
        original=scanner.source_sha256
        calls=0
        def changed(path):
            nonlocal calls
            if Path(path)==self.sample:
                calls+=1
                if calls>1:return 'different'
            return original(path)
        with mock.patch.object(scanner,'source_sha256',side_effect=changed):
            with self.assertRaisesRegex(outcome.ValidationError,'entrada cambió'):self.analyze()
        self.assertFalse(self.output.exists())

    def test_html_escapes_names_and_no_external_assets(self):
        malicious={'source':{'name':'<img src=x onerror=alert(1)>','sha256':'abc'}}
        coverage={str(m):{'n_complete':0,'n_incomplete':50} for m in outcome.HORIZONS}
        text=outcome.report_html([],{'joined_signals':50},coverage,malicious)
        self.assertNotIn('<img',text)
        self.assertIn('&lt;img',text)
        self.assertNotIn('<script',text)
        self.assertIn('No es un backtest',text)


class FormulaTests(unittest.TestCase):
    def setUp(self):
        self.decision=600
        self.bars={600:tuple(map(D,('100','102','99','101'))),900:tuple(map(D,('101','104','97','99'))),
                   1200:tuple(map(D,('99','103','98','102')))}
        # Enormous extrema on signal and end boundary must be wholly excluded.
        self.bars[300]=tuple(map(D,('100','99999','1','100')))
        self.bars[1500]=tuple(map(D,('100','99999','1','100')))

    def result(self,direction):
        return outcome.horizon_result(self.bars,600,15,direction,D('100'),D('100.1'),D('.01'))

    def test_buy_known_mfe_mae_and_positive_close(self):
        row=self.result('BUY')
        self.assertEqual((row['mfe_points'],row['mae_points'],row['close_return_points']),(D('390'),D('310'),D('190')))

    def test_sell_known_spread_and_negative_close(self):
        row=self.result('SELL')
        self.assertEqual((row['mfe_points'],row['mae_points'],row['close_return_points']),(D('290'),D('410'),D('-210')))

    def test_exact_bounds_and_first_bar_at_decision(self):
        row=self.result('BUY')
        self.assertEqual((row['first_bar_open'],row['last_bar_open'],row['end_exclusive'],row['bar_count']),(600,1200,1500,3))
        del self.bars[600]
        row=self.result('BUY')
        self.assertEqual(row['status'],'INCOMPLETE')
        self.assertEqual(row['missing_timestamps'],'600')
        self.assertIsNone(row['close_return_points'])

    def test_mfe_mae_clamped_to_zero(self):
        for direction,price,expected in [('BUY','90',('0','1010','-1010')),('SELL','110',('0','1010','-1010'))]:
            bars={t:(D(price),)*4 for t in (600,900,1200)}
            row=outcome.horizon_result(bars,600,15,direction,D('100'),D('100.1'),D('.01'))
            self.assertEqual(tuple(row[k] for k in outcome.METRICS),tuple(map(D,expected)))
            self.assertGreaterEqual(row['mfe_points'],0);self.assertGreaterEqual(row['mae_points'],0)

    def test_signed_close_buy_negative_sell_positive(self):
        self.bars[1200]=tuple(map(D,('99','101','98','99')))
        self.assertEqual(self.result('BUY')['close_return_points'],D('-110'))
        self.assertEqual(self.result('SELL')['close_return_points'],D('90'))


class RealOutcomeTests(unittest.TestCase):
    @unittest.skipUnless(all(os.environ.get(key) for key in ('SCANNER_CSV_PATH','SCANNER_SAMPLE_PATH','SCANNER_ANNOTATIONS_PATH')),
                         'Set the three explicit integration paths')
    def test_real_50_reviewed_signals(self):
        paths=[Path(os.environ[k]) for k in ('SCANNER_CSV_PATH','SCANNER_SAMPLE_PATH','SCANNER_ANNOTATIONS_PATH')]
        hashes=[scanner.source_sha256(p) for p in paths]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'outcomes'
            manifest=outcome.analyze(*paths,output,'0.01')
            rows=load(output/outcome.OUTPUT_NAMES[0])
            self.assertEqual(len(rows),50)
            self.assertEqual(len({r['sample_id'] for r in rows}),50)
            self.assertEqual(Counter(r['reviewer_decision'] for r in rows),{'VALID':20,'QUESTIONABLE':23,'REJECTED':7})
            for row in rows:
                for m in outcome.HORIZONS:
                    self.assertEqual(int(row[f'h{m}_first_bar_open']),int(row['decision_server']))
                    self.assertGreater(int(row[f'h{m}_first_bar_open']),int(row['signal_open_server']))
                    self.assertEqual(int(row[f'h{m}_end_exclusive']),int(row['decision_server'])+m*60)
                    if row[f'h{m}_status']=='COMPLETE':
                        self.assertEqual(int(row[f'h{m}_bar_count']),m//5)
                        self.assertGreaterEqual(D(row[f'h{m}_mfe_points']),0)
                        self.assertGreaterEqual(D(row[f'h{m}_mae_points']),0)
            self.assertEqual(manifest['validation_counts']['conflicting_bars'],0)
        self.assertEqual(hashes,[scanner.source_sha256(p) for p in paths])


if __name__=='__main__':
    unittest.main()
