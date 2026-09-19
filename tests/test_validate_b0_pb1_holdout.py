"""Phase 3 infrastructure tests: artificial data only, never a real holdout CSV."""
import copy
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from tools import validate_b0_pb1_holdout as holdout
from tools import analyze_signal_robustness as robust
import test_analyze_scanner as fixtures

SYNTHETIC_SCHEDULE = '2026.06.01 00:00|2026.12.01 00:00|180'
CLOSED = datetime(2026, 11, 1, 4, tzinfo=timezone.utc)


def artificial_row(ny_stamp, lanes=(), **changes):
    # NY local clock represented by the scanner's arithmetic epoch convention.
    decision = ny_stamp + 7*3600  # NY -4 and artificial broker +3
    parts = fixtures.IDENTITY.split('|')
    parts[13] = SYNTHETIC_SCHEDULE.encode('utf-16-be').hex().upper()
    direction = 'SELL' if lanes and lanes[0].endswith('sell') else 'BUY'
    bid = '104.0' if direction == 'SELL' else '100.0'
    row = fixtures.make_row(0, lanes, identity='|'.join(parts), decision_server=str(decision),
        signal_open_server=str(decision-300), observed_server=str(decision),
        decision_utc=str(ny_stamp+4*3600), observed_utc=str(ny_stamp+4*3600),
        decision_ny=str(ny_stamp), server_offset_minutes='180',
        h1_open_server=str(decision//3600*3600-3600), bid=bid,
        ask=str(Decimal(bid)+Decimal('.10')),
        session='IN' if 8 <= datetime.fromtimestamp(ny_stamp, timezone.utc).hour < 12 else 'OUT')
    # Constant, coherent artificial bid candles; no inconsistent overlapping copies.
    row['m5_window'] = ';'.join(f'{decision-i*300}:102:103:101:102' for i in range(4, 0, -1))
    row.update(changes)
    for lane in robust.scanner.LANES:
        module, emitted = lane.upper().split('_')
        row[lane+'_key'] = f'{row["identity"]}:{row["decision_server"]}:{module}:{emitted}'
        row[lane+'_episode_server'] = str(decision-300 if lane in lanes else 0)
    row['checksum'] = robust.scanner.checksum(row)
    return row


def write_source(path, rows):
    robust.scanner.write_csv(path, robust.scanner.COLUMNS, rows)


def full_collection():
    rows = []
    days = sorted({slot//86400*86400 for slot in holdout.expected_slots()})
    for index, day in enumerate(days):
        # Only the first ten days have B0+PB1: 20 signals, including BUY and SELL.
        for minutes in range(8*60, 14*60+5, 5):
            lanes = ()
            if index < 10 and minutes in (8*60, 10*60):
                direction = 'buy' if minutes == 8*60 else 'sell'
                lanes = ('b0_'+direction, 'pb1_'+direction)
            elif index == 10 and minutes == 9*60:
                lanes = ('b0_buy',)  # Must not join the primary population.
            rows.append(artificial_row(day+minutes*60, lanes))
    return rows


def summary_fixture():
    rows = []
    for horizon in (60, 120):
        for factor in ('1.00', '2.00'):
            for subset in ('ALL', 'NONOVERLAP_FIRST', 'NONOVERLAP_LAST'):
                for metric in robust.METRICS:
                    rows.append(dict(horizon_minutes=horizon, spread_factor=factor,
                        subset=subset, metric=metric, n_total=20, n_complete=20, n_days=10,
                        mean=10., median=9., trimmed_mean_10=9., winsorized_mean_10=9.,
                        bootstrap_low95=2., loo_mean_min=1., permutation_p_one_sided=.01))
    return rows


class TemporalValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = full_collection()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'artificial.csv'

    def run_artificial(self, output='result'):
        # The production CLI has neither of these overrides.
        with mock.patch.object(holdout, 'utc_now', return_value=CLOSED), \
             mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
            return holdout.analyze(self.source, self.folder / output)

    def test_open_window_blocks_before_any_file_read_or_import(self):
        with mock.patch.object(holdout, 'utc_now', return_value=CLOSED-timedelta(microseconds=1)), \
             mock.patch.object(holdout, 'dependencies') as deps, \
             mock.patch.object(Path, 'open', side_effect=AssertionError('No read permitted')):
            with self.assertRaisesRegex(holdout.HoldoutError, 'WINDOW_OPEN'):
                holdout.analyze(self.source, self.folder/'result')
        deps.assert_not_called()
        self.assertFalse((self.folder/'result').exists())

    def test_exact_close_allowed_and_utc_bounds(self):
        with mock.patch.object(holdout, 'utc_now', return_value=CLOSED):
            holdout.check_window()
        self.assertEqual(holdout.END_UTC, CLOSED)
        self.assertEqual(holdout.START_UTC, datetime(2026, 8, 15, 4, tzinfo=timezone.utc))

    def test_clock_must_be_timezone_aware(self):
        with mock.patch.object(holdout, 'utc_now', return_value=datetime(2026, 11, 2)):
            with self.assertRaisesRegex(holdout.HoldoutError, 'zona UTC'):
                holdout.check_window()

    def test_window_changes_discovery_overlap_and_extension_rejected(self):
        for start, end in (('2026-06-10T00:00:00-04:00', holdout.END_NY),
                           (holdout.START_NY, '2026-12-01T00:00:00-05:00'),
                           ('2026-08-16T00:00:00-04:00', holdout.END_NY)):
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(holdout.HoldoutError, 'FROZEN_WINDOW'):
                    holdout.check_window(start, end)

    def test_cli_has_no_clock_or_rule_override(self):
        for option in ('--as-of', '--seed', '--direction', '--module', '--point-size',
                       '--bootstrap-reps', '--spread-model', '--horizon', '--broker-schedule'):
            with self.subTest(option=option), mock.patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    holdout.main(['--input', 'unused.csv', '--output-dir', 'unused', option, 'x'])
                self.assertEqual(error.exception.code, 2)

    def test_frozen_hashes_match_and_each_tamper_is_rejected(self):
        holdout.verify_frozen_code()
        for changed in holdout.FROZEN_SHA256:
            original = holdout.sha256
            def fake_hash(path):
                return '0'*64 if Path(path) == ROOT / changed else original(path)
            with self.subTest(file=changed), mock.patch.object(holdout, 'sha256', side_effect=fake_hash), \
                 mock.patch.object(holdout.importlib, 'import_module') as imported:
                with self.assertRaisesRegex(holdout.HoldoutError, 'FROZEN_HASH_MISMATCH'):
                    holdout.dependencies()
                imported.assert_not_called()

    def test_altered_ex5_bytes_block_before_input_or_verdict(self):
        name = 'XAUUSD_Intraday_Signal_Scanner.ex5'
        expected = holdout.FROZEN_SHA256[name]
        original_hash = holdout.sha256
        altered = self.folder / name
        content = bytearray((ROOT / name).read_bytes())
        content[-1] ^= 1
        altered.write_bytes(content)
        self.assertNotEqual(original_hash(altered), expected)
        def hash_with_altered_ex5(path):
            return original_hash(altered if Path(path) == ROOT / name else path)
        with mock.patch.object(holdout, 'utc_now', return_value=CLOSED), \
             mock.patch.object(holdout, 'sha256', side_effect=hash_with_altered_ex5), \
             mock.patch.object(holdout.importlib, 'import_module') as imported, \
             mock.patch.object(holdout, 'inspect_source') as read, \
             mock.patch.object(holdout, 'primary_verdict') as verdict:
            with self.assertRaisesRegex(holdout.HoldoutError, 'FROZEN_HASH_MISMATCH: .*ex5'):
                holdout.analyze(self.source, self.folder/'out')
            imported.assert_not_called()
            read.assert_not_called()
            verdict.assert_not_called()
        self.assertEqual(original_hash(ROOT / name), expected)
        self.assertFalse((self.folder/'out').exists())

    def test_original_schedule_is_insufficient_and_blocks_before_input(self):
        self.assertFalse(holdout.schedule_covers_window(holdout.parse_schedule(holdout.BROKER_SCHEDULE)))
        with mock.patch.object(holdout, 'utc_now', return_value=CLOSED), \
             mock.patch.object(holdout, 'inspect_source') as read, \
             mock.patch.object(holdout, 'primary_verdict') as verdict:
            with self.assertRaisesRegex(holdout.HoldoutError, 'BROKER_SCHEDULE_INCOMPLETE'):
                holdout.analyze(self.source, self.folder/'out')
            read.assert_not_called()
            verdict.assert_not_called()
        self.assertFalse((self.folder/'out').exists())

    def test_schedule_gaps_overlaps_and_exact_coverage(self):
        self.assertTrue(holdout.schedule_covers_window(holdout.parse_schedule(SYNTHETIC_SCHEDULE)))
        gap = '2026.06.01 00:00|2026.09.01 00:00|180;2026.09.02 00:00|2026.12.01 00:00|180'
        self.assertFalse(holdout.schedule_covers_window(holdout.parse_schedule(gap)))
        with self.assertRaisesRegex(holdout.HoldoutError, 'solapado'):
            holdout.parse_schedule(SYNTHETIC_SCHEDULE+';2026.10.01 00:00|2026.12.31 00:00|120')

    def test_discovery_acceptance_rejected_even_for_isolated_module(self):
        stamp = int(datetime(2026, 8, 14, 9, tzinfo=timezone.utc).timestamp())
        write_source(self.source, [artificial_row(stamp, ('b0_buy',))])
        with mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
            with self.assertRaisesRegex(holdout.HoldoutError, 'OUTSIDE_HOLDOUT'):
                holdout.inspect_source(self.source, robust.scanner)

    def test_exclusive_end_acceptance_rejected(self):
        stamp = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
        write_source(self.source, [artificial_row(stamp, ('b0_buy',), session='OUT')])
        with mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
            with self.assertRaisesRegex(holdout.HoldoutError, 'OUTSIDE_HOLDOUT'):
                holdout.inspect_source(self.source, robust.scanner)

    def test_inclusive_start_nonaccepted_context_and_correct_utc(self):
        stamp = int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp())
        write_source(self.source, [artificial_row(stamp)])
        with mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
            coverage = holdout.inspect_source(self.source, robust.scanner)
        self.assertFalse(coverage['collection_complete'])

    def test_scanner_parameters_and_schedule_changes_rejected(self):
        for index, replacement in ((7, '51'), (8, '4'), (9, '4'), (10, '3'), (11, '9'), (12, '13'), (13, '')):
            row = dict(self.rows[0])
            parts = row['identity'].split('|')
            parts[index] = replacement
            row['identity'] = '|'.join(parts)
            write_source(self.source, [row])
            with self.subTest(index=index), mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
                with self.assertRaisesRegex(holdout.HoldoutError, 'FROZEN_PARAMETERS'):
                    holdout.inspect_source(self.source, robust.scanner)

    def test_inconsistent_ny_and_broker_offsets_rejected(self):
        for key, value in (('ny_offset_minutes', '-300'), ('decision_ny', str(int(self.rows[0]['decision_ny'])+300)),
                           ('server_offset_minutes', '120')):
            row = dict(self.rows[0], **{key:value})
            row['checksum'] = robust.scanner.checksum(row)
            write_source(self.source, [row])
            with self.subTest(key=key), mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
                with self.assertRaisesRegex(holdout.HoldoutError, 'Conversion'):
                    holdout.inspect_source(self.source, robust.scanner)

    def test_bad_checksum_is_rejected(self):
        write_source(self.source, [dict(self.rows[0], checksum='00000000')])
        with mock.patch.object(holdout, 'BROKER_SCHEDULE', SYNTHETIC_SCHEDULE):
            with self.assertRaisesRegex(robust.ValidationError, 'checksum'):
                holdout.inspect_source(self.source, robust.scanner)

    def test_full_synthetic_pipeline_reproducible_and_inputs_unchanged(self):
        write_source(self.source, self.rows)
        before = self.source.read_bytes()
        manifest = self.run_artificial('first')
        again = self.run_artificial('second')
        self.assertEqual(manifest, again)
        self.assertEqual(manifest['verdict']['status'], 'PASS')
        self.assertEqual(manifest['counts']['primary_population'], 20)
        self.assertEqual(manifest['counts']['accepted_in_window'], 21)
        self.assertTrue(manifest['collection']['collection_complete'])
        ex5 = 'XAUUSD_Intraday_Signal_Scanner.ex5'
        self.assertEqual(manifest['frozen_code_sha256'][ex5], holdout.sha256(ROOT / ex5))
        self.assertEqual(before, self.source.read_bytes())
        for name in holdout.OUTPUT_NAMES:
            self.assertEqual((self.folder/'first'/name).read_bytes(), (self.folder/'second'/name).read_bytes())
        for record in manifest['files']:
            self.assertEqual(record['sha256'], holdout.sha256(self.folder/'first'/record['name']))
        with (self.folder/'first'/holdout.OUTPUT_NAMES[1]).open(newline='', encoding='utf-8') as stream:
            results = list(csv.DictReader(stream))
        self.assertEqual(len(results), 80)
        self.assertEqual({r['direction'] for r in results}, {'BUY', 'SELL'})
        self.assertEqual({r['module'] for r in results}, {'B0+PB1'})
        self.assertFalse({'context_class', 'signal_alignment', 'reviewer_decision'} & set(results[0]))
        self.assertEqual({r['horizon_minutes'] for r in results}, {'60', '120'})
        self.assertEqual({r['spread_factor'] for r in results}, {'1.00', '2.00'})
        with self.assertRaisesRegex(holdout.HoldoutError, 'existente'):
            self.run_artificial('first')

    def test_partial_collection_cannot_pass_even_with_enough_signals(self):
        # Remove an IN-session record on the last day, not a horizon needed by any signal.
        last_day = max(holdout.expected_slots())//86400*86400
        rows = [r for r in self.rows if int(r['decision_ny']) != last_day+8*3600]
        write_source(self.source, rows)
        manifest = self.run_artificial()
        self.assertEqual(manifest['verdict']['status'], 'INCONCLUSIVE')
        self.assertEqual(manifest['collection']['missing_session_slots'], 1)
        self.assertEqual(manifest['coverage']['60']['n_complete'], 20)

    def test_primary_pass_and_each_independent_failure_including_costs(self):
        good = summary_fixture()
        self.assertEqual(holdout.primary_verdict(good)['status'], 'PASS')
        for row in good:
            if row['horizon_minutes'] != 60:
                continue
            targets = []
            if row['metric'] == 'close_return_points':
                targets = ['mean'] if row['subset'] != 'ALL' else [
                    'mean', 'median', 'trimmed_mean_10', 'winsorized_mean_10', 'loo_mean_min', 'bootstrap_low95']
            if row['metric'] == 'paired_delta_points' and row['subset'] == 'ALL':
                targets = ['mean', 'bootstrap_low95']
            for stat in targets:
                changed = copy.deepcopy(good)
                changed[good.index(row)][stat] = 0
                with self.subTest(factor=row['spread_factor'], subset=row['subset'], metric=row['metric'], stat=stat):
                    self.assertEqual(holdout.primary_verdict(changed)['status'], 'FAIL')

    def test_one_sided_threshold_no_holm_and_missing_probability(self):
        rows = summary_fixture()
        paired = next(r for r in rows if r['horizon_minutes'] == 60 and r['spread_factor'] == '1.00'
                      and r['subset'] == 'ALL' and r['metric'] == 'paired_delta_points')
        for p, expected in ((.05, 'PASS'), (.050001, 'FAIL'), (None, 'FAIL')):
            paired['permutation_p_one_sided'] = p
            paired['permutation_p_holm'] = 1  # Irrelevant in this single primary hypothesis.
            self.assertEqual(holdout.primary_verdict(rows)['status'], expected)

    def test_minimum_samples_and_days_and_inconclusive_precedence(self):
        for n, days, expected in ((19, 10, 'INCONCLUSIVE'), (20, 9, 'INCONCLUSIVE'),
                                   (20, 10, 'PASS'), (0, 0, 'INCONCLUSIVE')):
            rows = summary_fixture()
            for row in rows:
                row.update(n_total=n, n_complete=n, n_days=days)
            self.assertEqual(holdout.primary_verdict(rows)['status'], expected)
        self.assertEqual(holdout.primary_verdict(summary_fixture(), False)['status'], 'INCONCLUSIVE')

    def test_20_of_21_primary_signals_inconclusive_before_pass_or_fail(self):
        for failing_signs in (False, True):
            rows = summary_fixture()
            for row in rows:
                if row['horizon_minutes'] == 60:
                    row['n_total'] = 21
                    if failing_signs:
                        row.update(mean=-10., bootstrap_low95=-20.)
            with self.subTest(failing_signs=failing_signs):
                result = holdout.primary_verdict(rows)
                self.assertEqual(result, {'status':'INCONCLUSIVE',
                    'reasons':['PRIMARY_60_HORIZON_INCOMPLETE'], 'criteria':{}})

    def test_cost_count_inconsistency_is_invalid_even_when_inconclusive(self):
        for factor in ('1.00', '2.00'):
            for field, value in (('n_complete', 19), ('n_total', 21), ('n_days', 9)):
                rows = summary_fixture()
                row = next(r for r in rows if r['horizon_minutes'] == 60 and
                           r['spread_factor'] == factor and r['subset'] == 'ALL' and
                           r['metric'] == 'close_return_points')
                row[field] = value
                with self.subTest(factor=factor, field=field):
                    with self.assertRaisesRegex(holdout.HoldoutError, 'PRIMARY_60_COUNTS_INCONSISTENT'):
                        holdout.primary_verdict(rows, collection_complete=False)

    def test_invalid_primary_counts_precede_inconclusive(self):
        for field, value in (('n_total', -1), ('n_complete', 21), ('n_days', 21),
                             ('n_complete', None), ('n_total', True)):
            rows = summary_fixture()
            rows[0][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(holdout.HoldoutError, 'PRIMARY_60_COUNTS_INVALID'):
                    holdout.primary_verdict(rows, collection_complete=False)

    def test_invalid_source_precedes_statistical_verdict(self):
        write_source(self.source, [dict(self.rows[0], checksum='00000000')])
        with mock.patch.object(holdout, 'primary_verdict') as verdict:
            with self.assertRaisesRegex(robust.ValidationError, 'checksum'):
                self.run_artificial()
            verdict.assert_not_called()
        self.assertFalse((self.folder/'result').exists())

    def test_missing_primary_or_secondary_bar_through_summary(self):
        # Twenty complete signals on ten days; one more has a missing future bar.
        # Exercise actual horizon calculation and summarization, not only a verdict fixture.
        for missing in (0, 12):
            scenarios = self.small_scenarios()
            for key, rows in scenarios.items():
                template = rows[0]
                rows[:] = [dict(template, sample_id=f'SYN-{i:02}',
                    day=f'2026-08-{17+i//2:02}') for i in range(20)]
            baseline = holdout.primary_verdict(holdout.summarize(scenarios, robust))
            self.assertEqual(baseline['status'], 'PASS')
            for key, extra in self.small_scenarios(missing=missing).items():
                scenarios[key].append(dict(extra[0], sample_id='SYN-20'))
            summary = holdout.summarize(scenarios, robust)
            result = holdout.primary_verdict(summary)
            with self.subTest(missing=missing):
                if missing == 0:
                    self.assertEqual(result['status'], 'INCONCLUSIVE')
                    self.assertIn('PRIMARY_60_HORIZON_INCOMPLETE', result['reasons'])
                    for row in summary:
                        if row['horizon_minutes'] == 60 and row['subset'] == 'ALL':
                            self.assertEqual((row['n_complete'], row['n_total']), (20, 21))
                else:
                    self.assertEqual(result, baseline)

    def test_secondary_results_cannot_rescue_or_veto_primary(self):
        rows = summary_fixture()
        for row in rows:
            if row['horizon_minutes'] == 120:
                row.update(mean=-1e6, median=-1e6, n_complete=0, n_days=0, bootstrap_low95=None)
        self.assertEqual(holdout.primary_verdict(rows)['status'], 'PASS')
        for row in rows:
            if row['horizon_minutes'] == 60 and row['metric'] == 'close_return_points':
                row['mean'] = -1
            elif row['horizon_minutes'] == 120:
                row.update(mean=1e6, median=1e6, n_complete=1000, n_days=100)
        self.assertEqual(holdout.primary_verdict(rows)['status'], 'FAIL')

    def small_scenarios(self, missing=None, delayed=False):
        signal = dict(signal_id='ARTIFICIAL', module='B0+PB1', direction='BUY',
                      decision_server=1800000000, decision_ny_text='2026-08-17 09:00:00')
        t = signal['decision_server']
        market = {t+i*300: tuple(map(Decimal, ('101','103','99','102'))) for i in range(24)}
        market[t-300] = tuple(map(Decimal, ('1','1000000','0.1','999999')))
        market[t+7200] = tuple(map(Decimal, ('1','1000000','0.1','999999')))
        entries = {t:dict(bid='100', ask='100.10', spread_points='10',
                         delay_seconds='1' if delayed else '0', observed_server=str(t+int(delayed)))}
        if missing is not None:
            del market[t+missing*300]
        return holdout.scenarios([signal], market, entries, robust)

    def test_causal_bar_boundaries_signed_close_and_spread_inversion(self):
        all_rows = self.small_scenarios()
        for (minutes, factor), rows in all_rows.items():
            row = rows[0]
            self.assertEqual(row['first_bar_open'], row['decision_server'])
            self.assertEqual(row['last_bar_open'], row['decision_server']+minutes*60-300)
            self.assertEqual(row['bar_count'], minutes//5)
            self.assertEqual(row['close_return_points'], 190 if factor == '1.00' else 180)
            self.assertEqual(row['inverse_close_return_points'], -210 if factor == '1.00' else -220)
            self.assertEqual(row['paired_delta_points'], 400)
            self.assertEqual(row['mfe_points'], 290 if factor == '1.00' else 280)

    def test_incomplete_horizon_is_not_zero_and_secondary_missing_is_independent(self):
        rows = self.small_scenarios(missing=12)
        self.assertEqual(rows[60, '1.00'][0]['status'], 'COMPLETE')
        self.assertEqual(rows[120, '1.00'][0]['status'], 'INCOMPLETE')
        self.assertIsNone(rows[120, '1.00'][0]['close_return_points'])
        self.assertIsNone(rows[120, '1.00'][0]['paired_delta_points'])
        self.assertEqual(rows[120, '1.00'][0]['bar_count'], 23)

    def test_late_quote_rejected(self):
        with self.assertRaisesRegex(holdout.HoldoutError, 'Cotizacion tardia'):
            self.small_scenarios(delayed=True)

    def test_nonoverlap_is_selected_before_missing_outcomes(self):
        rows = [dict(sample_id=str(i), decision_server=i*300, status='INCOMPLETE' if i == 0 else 'COMPLETE') for i in range(3)]
        self.assertEqual([r['sample_id'] for r in robust.nonoverlap(rows, 60)], ['0'])
        self.assertEqual([r['sample_id'] for r in robust.nonoverlap(rows, 60, True)], ['2'])

    def test_day_grouping_not_individual_sign_flips(self):
        # Twenty perfectly dependent observations from one day do not create 20 independent units.
        rows = [dict(day='2026-08-17', **{metric:10. for metric in robust.METRICS}) for _ in range(20)]
        self.assertEqual(robust.paired_permutation(rows, 10000, 20260919), (None, None))
        self.assertEqual(robust.day_bootstrap(rows, 2000, 20260919)['close_return_points'], (None, None, 0))

    def test_empty_primary_population_is_inconclusive(self):
        all_scenarios = {(m, factor): [] for m in (60, 120) for factor in ('1.00', '2.00')}
        summary = holdout.summarize(all_scenarios, robust)
        self.assertEqual(holdout.primary_verdict(summary)['status'], 'INCONCLUSIVE')
        self.assertTrue(all(row['mean'] is None for row in summary))

    def test_frozen_resampling_only_primary_and_no_holm(self):
        scenarios = self.small_scenarios()
        with mock.patch.object(robust, 'holm', side_effect=AssertionError('No Holm')), \
             mock.patch.object(robust, 'day_bootstrap', wraps=robust.day_bootstrap) as bootstrap, \
             mock.patch.object(robust, 'paired_permutation', wraps=robust.paired_permutation) as permutation:
            summary = holdout.summarize(scenarios, robust)
        self.assertEqual(bootstrap.call_count, 2)
        self.assertEqual(permutation.call_count, 1)
        for call in bootstrap.call_args_list:
            self.assertEqual(call.args[1:], (2000, robust.stable_seed(20260919, 'PHASE3|60')))
        self.assertEqual(permutation.call_args.args[1:], (10000, robust.stable_seed(20260919, 'PHASE3|60')))
        self.assertTrue(all(r['role'] == 'SECONDARY_DESCRIPTIVE' for r in summary
                            if r['horizon_minutes'] == 120 or r['metric'] in ('mfe_points', 'mae_points')))


if __name__ == '__main__':
    unittest.main()
