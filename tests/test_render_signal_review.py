"""Offline review regression tests, including real browser CSV download and opt-in data."""
import csv
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools import render_signal_review as review
from test_analyze_scanner import make_row, START, IDENTITY, ACCOUNT, SERVER

scanner = review.scanner


def market_bar(stamp):
    index = (stamp-START)//300
    opening = 2300 + index*0.25
    close = opening + (0.5 if index % 2 else -0.5)
    return (stamp, opening, max(opening, close)+0.25, min(opening, close)-0.25, close)


def source_row(index, lanes=()):
    row = make_row(index, lanes)
    decision = int(row['decision_server'])
    row['m5_window'] = ';'.join(':'.join(map(str, market_bar(stamp)))
                              for stamp in range(decision-1200, decision, 300))
    row['checksum'] = scanner.checksum(row)
    return row


def sample_row(row, identifier):
    fields = set(review.REQUIRED_SAMPLE) | {'decision_server', 'signal_open_server', 'decision_ny'}
    result = {key: row.get(key, '') for key in fields}
    result['signal_id'] = identifier
    result['signal_open_server_text'] = scanner.timestamp_text(int(row['signal_open_server']))
    result['decision_ny_text'] = scanner.timestamp_text(int(row['decision_ny']))
    accepted = [lane for lane in scanner.LANES if row[f'{lane}_reason'] == 'ACCEPT_DIAGNOSTIC']
    result['direction'] = accepted[0].split('_')[1].upper()
    result['module'] = '+'.join(m for m in ('B0', 'PB1') if any(lane.startswith(m.lower()) for lane in accepted))
    result.update(zip(review.PRICE_FIELDS, map(str, market_bar(int(row['signal_open_server']))[1:])))
    result['review_notes'] = ''
    return result


def write_csv(path, rows, columns=None):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ElementText(HTMLParser):
    def __init__(self, wanted):
        super().__init__()
        self.wanted, self.inside, self.parts = wanted, False, []
        self.external, self.images, self.candles = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id') == self.wanted:
            self.inside = True
        if tag == 'img':
            self.images.append(attrs)
        if 'src' in attrs or (tag == 'link' and 'href' in attrs):
            self.external.append(attrs)
        if tag == 'g' and 'data-bar-time' in attrs:
            self.candles.append((int(attrs['data-bar-time']), attrs['class']))

    def handle_endtag(self, tag):
        if tag in ('script', 'pre'):
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)

    def value(self):
        return ''.join(self.parts)


def browser_run(case, target, script, profile):
    candidates = [os.environ.get('REVIEW_BROWSER_EXE', ''),
                  r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                  shutil.which('chromium') or '', shutil.which('google-chrome') or '']
    browser = next((p for p in candidates if p and Path(p).is_file()), None)
    if not browser:
        case.skipTest('Set REVIEW_BROWSER_EXE to an installed Chromium/Edge browser')
    document = target.read_text(encoding='utf-8')
    harness = """<script>(async () => { const result = {};
    try { SCRIPT } catch(error) { result.error = String(error); }
    const pre = document.createElement('pre'); pre.id = 'browser-test-result';
    pre.textContent = JSON.stringify(result); document.body.appendChild(pre);
    })();</script>""".replace('SCRIPT', script)
    target.write_text(document.replace('</body>', harness+'</body>'), encoding='utf-8')
    try:
        run = subprocess.run([browser, '--headless', '--disable-gpu', '--no-first-run',
                              '--no-default-browser-check', '--disable-background-networking',
                              '--disable-extensions', '--window-size=1920,1080',
                              '--user-data-dir='+str(profile), '--virtual-time-budget=3000',
                              '--dump-dom', target.as_uri()], capture_output=True, encoding='utf-8',
                             errors='replace', timeout=45,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        parsed = ElementText('browser-test-result')
        parsed.feed(run.stdout)
        case.assertTrue(parsed.value(), 'No browser result: '+run.stderr[-1500:])
        result = json.loads(parsed.value())
        case.assertNotIn('error', result)
        return result
    finally:
        target.write_text(document, encoding='utf-8')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input, self.sample, self.output = self.root/'scanner.csv', self.root/'sample.csv', self.root/'book'
        accepted = {35: ('b0_buy',), 38: ('pb1_sell',), 40: ('b0_buy', 'pb1_buy')}
        self.rows = [source_row(i, accepted.get(i, ())) for i in range(44)]
        self.samples = [sample_row(self.rows[i], f'SIG-{i:06}') for i in accepted]
        self.write()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self):
        write_csv(self.input, self.rows, scanner.COLUMNS)
        write_csv(self.sample, self.samples)

    def records(self, bars=30):
        return review.build_records(self.input, self.sample, bars)[0]

    def test_timestamp_primary_and_epoch_confirmation(self):
        records = self.records()
        for record, sample in zip(records, self.samples):
            self.assertEqual(record['status'], 'OK')
            self.assertEqual(record['bar_time_epoch'], int(sample['signal_open_server']))
            self.assertEqual(record['signal_open_server_text'], sample['signal_open_server_text'])

    def test_requested_aliases(self):
        for row in self.samples:
            row['sample_id'] = row.pop('signal_id')
            row['bar_time_epoch'] = row.pop('signal_open_server')
        self.write()
        self.assertTrue(all(r['status'] == 'OK' for r in self.records()))

    def test_conflicting_secondary_epoch_rejected(self):
        self.samples[0]['signal_open_server'] = str(int(self.samples[0]['signal_open_server'])-300)
        self.write()
        self.assertIn('epoch', ' '.join(self.records()[0]['errors']))
        self.assertEqual(self.records()[0]['bars'], [])

    def test_ohlc_mismatch_blocks_chart_and_is_visible(self):
        self.samples[0]['signal_open'] = '9999'
        self.write()
        target, records = review.generate(self.input, self.sample, self.output)
        self.assertEqual(records[0]['bars'], [])
        self.assertIn('OHLC de señal incompatibles', target.read_text(encoding='utf-8'))
        self.assertEqual(records[1]['status'], 'OK')

    def test_direction_and_module_must_match(self):
        for field, value in (('direction', 'SELL'), ('module', 'PB1')):
            with self.subTest(field=field):
                original = self.samples[0][field]
                self.samples[0][field] = value
                self.write()
                self.assertEqual(self.records()[0]['status'], 'ERROR')
                self.samples[0][field] = original

    def test_exact_30_prior_bars_and_one_signal_without_future(self):
        for record in self.records():
            target = record['bar_time_epoch']
            self.assertEqual([b[0] for b in record['bars']], list(range(target-9000, target+1, 300)))
            self.assertEqual(record['bars'][-1], list(market_bar(target)))
            parsed = ElementText('unused')
            parsed.feed(review.chart_svg(record, 30))
            self.assertEqual(len(parsed.candles), 31)
            self.assertEqual(sum(' signal' in cls for _, cls in parsed.candles), 1)
            self.assertTrue(all(stamp <= target for stamp, _ in parsed.candles))

    def test_zero_prior_bars(self):
        self.assertTrue(all(len(r['bars']) == 1 for r in self.records(0)))

    def test_short_initial_history_is_explicit(self):
        self.rows = [source_row(0, ('b0_buy',))]
        self.samples = [sample_row(self.rows[0], 'EARLY')]
        self.write()
        record = self.records()[0]
        self.assertEqual(record['status'], 'INCOMPLETE')
        self.assertEqual(len(record['bars']), 4)
        self.assertIn('3/30', record['warnings'][0])
        self.assertEqual(record['bars'][-1][0], record['bar_time_epoch'])

    def test_missing_signal_decision_visible(self):
        self.rows = [r for r in self.rows if r['decision_server'] != self.samples[0]['decision_server']]
        self.write()
        record = self.records()[0]
        self.assertEqual(record['status'], 'ERROR')
        self.assertIn('falta la decisión', record['errors'][0])
        self.assertEqual(record['bars'], [])

    def test_internal_missing_bar_is_not_disguised_as_short_history(self):
        # Four consecutive omitted windows leave one missing historical bar.
        self.rows = [r for i, r in enumerate(self.rows) if i not in range(15, 19)]
        self.write()
        record = self.records()[0]
        self.assertIn('huecos', ' '.join(record['errors']))
        self.assertEqual(record['bars'], [])

    def test_later_rows_cannot_fill_missing_history_or_revise_past_chart(self):
        before = self.records()
        self.rows[36]['m5_window'] = self.rows[36]['m5_window'].replace('2308.5', '2308.6')
        self.rows[36]['checksum'] = scanner.checksum(self.rows[36])
        self.write()
        self.assertEqual(before[0], self.records()[0])
        # Even complete later windows cannot create a missing decision's chart.
        self.rows = [r for r in self.rows if r['decision_server'] != self.samples[0]['decision_server']]
        self.write()
        self.assertEqual(self.records()[0]['bars'], [])

    def test_conflicting_historical_ohlc_blocks_chart(self):
        bar = list(market_bar(START+29*300))
        bar[1] += 0.1
        old = ':'.join(map(str, market_bar(bar[0])))
        self.rows[30]['m5_window'] = self.rows[30]['m5_window'].replace(old, ':'.join(map(str, bar)))
        self.rows[30]['checksum'] = scanner.checksum(self.rows[30])
        self.write()
        self.assertIn('contradictorios', ' '.join(self.records()[0]['errors']))

    def test_sample_file_order_and_deterministic_html(self):
        self.samples.reverse()
        self.write()
        first = self.records()
        self.assertEqual([r['sample_id'] for r in first], [r['signal_id'] for r in self.samples])
        self.assertEqual(review.render_html(first, 30), review.render_html(self.records(), 30))

    def test_html_and_json_text_escaped_no_external_assets(self):
        attack = '</script><img src=x onerror="alert(1)">&\u2028'
        self.samples[0]['signal_id'] = attack
        self.samples[0]['review_notes'] = '</textarea>' + attack
        self.write()
        target, _ = review.generate(self.input, self.sample, self.output)
        document = target.read_text(encoding='utf-8')
        parsed = ElementText('review-data')
        parsed.feed(document)
        self.assertFalse(parsed.images)
        self.assertFalse(parsed.external)
        self.assertIn('&lt;/script&gt;', document)
        decoded = json.loads(parsed.value())
        self.assertEqual(decoded[0]['sample_id'], attack)
        self.assertEqual(decoded[0]['review']['reviewer_notes'], '</textarea>'+attack)

    def test_inputs_unchanged_and_private_identity_absent(self):
        before = [p.read_bytes() for p in (self.input, self.sample)]
        target, _ = review.generate(self.input, self.sample, self.output)
        self.assertEqual(before, [p.read_bytes() for p in (self.input, self.sample)])
        text = target.read_text(encoding='utf-8')
        for token in (IDENTITY, ACCOUNT, SERVER):
            self.assertNotIn(token, text)
        self.assertEqual(list(self.output.iterdir()), [target])

    def test_invalid_header_preserves_existing_output(self):
        target, _ = review.generate(self.input, self.sample, self.output)
        original = target.read_bytes()
        self.input.write_text('invalid\n', encoding='utf-8')
        with self.assertRaises(review.ValidationError):
            review.generate(self.input, self.sample, self.output)
        self.assertEqual(original, target.read_bytes())

    def test_invalid_bars_before(self):
        for count in (-1, 1001):
            with self.subTest(count=count), self.assertRaises(review.ValidationError):
                self.records(count)

    def test_source_checksum_rejected(self):
        self.rows[0]['checksum'] = '0'
        self.write()
        with self.assertRaisesRegex(review.ValidationError, 'checksum'):
            self.records()

    def test_duplicate_sample_rejected_visibly(self):
        self.samples.append(dict(self.samples[0]))
        self.write()
        self.assertEqual(self.records()[-1]['status'], 'ERROR')

    def test_metadata_disagreement_rejected(self):
        for field, value in (('h1_ema', '99'), ('spread_points', '20'), ('decision_ny_text', '2026-06-10 00:00:00'),
                             ('b0_buy_reason', 'NO_BREAKOUT')):
            with self.subTest(field=field):
                original = self.samples[0][field]
                self.samples[0][field] = value
                self.write()
                self.assertEqual(self.records()[0]['status'], 'ERROR')
                self.samples[0][field] = original

    def test_storage_key_deterministic_and_isolated(self):
        records = self.records()
        def key(rows):
            parser = ElementText('review-config')
            parser.feed(review.render_html(rows, 30))
            return json.loads(parser.value())['storageKey']
        original = key(records)
        self.assertEqual(original, key(self.records()))
        records[0]['review']['reviewer_notes'] = 'An input note must not reset saved reviews'
        self.assertEqual(original, key(records))
        records[0]['signal_close'] += 0.01
        self.assertNotEqual(original, key(records))
        self.assertNotEqual(original, key(list(reversed(self.records()))))

    def test_buttons_accessibility_and_exact_option_values(self):
        class Controls(HTMLParser):
            def __init__(self):
                super().__init__()
                self.buttons, self.selects = [], []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'button' and 'data-field' in attrs:
                    self.buttons.append(attrs)
                if tag == 'select' and 'data-field' in attrs:
                    self.selects.append(attrs)
        parser = Controls()
        parser.feed(review.render_card(self.records()[0], 0, 30))
        self.assertFalse(parser.selects)
        for field, options in review.OPTIONS.items():
            buttons = [b for b in parser.buttons if b['data-field'] == field]
            self.assertEqual([b['data-value'] for b in buttons], list(options))
            for button in buttons:
                self.assertEqual(button['type'], 'button')
                self.assertIn(button['aria-pressed'], ('true', 'false'))
                self.assertIn(field, button['aria-label'])
                self.assertIn(field, button['data-testid'])
                self.assertIn(button['data-value'] or 'EMPTY', button['data-testid'])
        self.assertEqual(len({b['data-testid'] for b in parser.buttons}), len(parser.buttons))

    def test_browser_persistence_reload_reopen_and_completed_protection(self):
        target, records = review.generate(self.input, self.sample, self.output)
        script = r'''
const all = Array.from(document.querySelectorAll('.signal-card'));
const current = () => all.findIndex(card => !card.hidden);
const save = document.getElementById('save-next');
const setNote = (index, value) => { const note = all[index].querySelector('textarea'); note.value=value; note.dispatchEvent(new Event('input', {bubbles:true})); };
if(location.hash !== '#restore') {
  const first = {initialBlocked:save.disabled, missingBlocked:[], immediate:[]};
  setNote(0, "Nota previa"); first.fieldsBlocked=save.disabled;
  const fields = {chart_quality:'CLEAR', signal_alignment:'ALIGNED', context_class:'TREND', reviewer_decision:'VALID'};
  for(const [field,value] of Object.entries(fields)) {
    const button=all[0].querySelector(`button[data-field="${field}"][data-value="${value}"]`);
    button.click();
    first.missingBlocked.push(save.disabled);
    first.immediate.push(JSON.parse(localStorage.getItem(reviewBook.storageKey)).annotations[0][field] === value);
    if(button.getAttribute('aria-pressed') !== 'true') throw new Error('Selection not accessible');
  }
  setNote(0, '  '); first.blankBlocked=save.disabled;
  setNote(0, 'Nota de prueba persistente'); first.ready=!save.disabled;
  first.noteImmediate=JSON.parse(localStorage.getItem(reviewBook.storageKey)).annotations[0].reviewer_notes;
  save.click();
  first.next=current(); first.confirmation=document.getElementById('confirmation').textContent;
  first.completed=document.getElementById('completed-count').textContent;
  first.pending=document.getElementById('pending-count').textContent;
  setNote(1, 'Borrador que debe restaurarse');
  all[1].querySelector('button[data-field="chart_quality"][data-value="MIXED"]').click();
  sessionStorage.setItem('review-test-observations', JSON.stringify(first));
  location.hash='#restore'; location.reload(); return;
}
Object.assign(result, JSON.parse(sessionStorage.getItem('review-test-observations')));
result.resumed=current(); result.draft=all[1].querySelector('textarea').value;
result.draftPressed=all[1].querySelector('button[data-field="chart_quality"][data-value="MIXED"]').getAttribute('aria-pressed');
document.getElementById('prev').click();
result.locked=all[0].querySelector('textarea').readOnly && Array.from(all[0].querySelectorAll('button')).every(b=>b.disabled) && save.disabled;
const before=localStorage.getItem(reviewBook.storageKey);
all[0].querySelector('button[data-field="chart_quality"][data-value="POOR"]').click();
result.unchanged=before===localStorage.getItem(reviewBook.storageKey);
document.getElementById('first-pending').click(); result.firstPending=current();
const footer=save.getBoundingClientRect(); result.saveVisible=footer.bottom <= innerHeight && footer.top>=0;
result.current=document.getElementById('current-count').textContent;
result.currentId=document.getElementById('current-id').textContent;
result.completedState=reviewBook.collectAnnotations()[0];
'''
        result = browser_run(self, target, script, self.root/'profile-persistence')
        for key in ('initialBlocked', 'fieldsBlocked', 'blankBlocked', 'ready', 'locked', 'unchanged', 'saveVisible'):
            self.assertTrue(result[key], key)
        self.assertEqual(result['missingBlocked'], [True, True, True, False])
        self.assertEqual(result['immediate'], [True]*4)
        self.assertEqual((result['next'], result['resumed'], result['firstPending']), (1, 1, 1))
        self.assertIn(records[0]['sample_id'], result['confirmation'])
        self.assertEqual(result['completed'], 'Completadas 1/3')
        self.assertEqual(result['pending'], 'Pendientes 2')
        self.assertEqual(result['current'], 'Actual 2/3')
        self.assertIn(records[1]['sample_id'], result['currentId'])
        self.assertEqual(result['draft'], 'Borrador que debe restaurarse')
        self.assertEqual(result['draftPressed'], 'true')
        self.assertEqual(result['noteImmediate'], 'Nota de prueba persistente')
        reopened = browser_run(self, target, "result.current = document.querySelector('.signal-card:not([hidden])').dataset.index; result.saved=reviewBook.collectAnnotations()[0];", self.root/'profile-persistence')
        self.assertEqual(reopened['current'], '1')
        self.assertEqual(reopened['saved'], result['completedState'])

    def test_browser_storage_failure_and_stale_tab_do_not_overwrite(self):
        target, _ = review.generate(self.input, self.sample, self.output)
        script = r'''
const key=reviewBook.storageKey;
const saved=localStorage.getItem(key);
localStorage.setItem(key, saved+' '); // Simulate a different tab writing first.
document.querySelector('.signal-card button[data-value="CLEAR"]').click();
result.preserved=localStorage.getItem(key) === saved+' ';
result.blocked=document.getElementById('save-next').disabled;
result.warning=document.getElementById('storage-status').textContent;
'''
        result = browser_run(self, target, script, self.root/'profile-conflict')
        self.assertTrue(result['preserved'])
        self.assertTrue(result['blocked'])
        self.assertIn('otra pestaña', result['warning'])
        document = target.read_text(encoding='utf-8')
        target.write_text(document.replace('<script>\nconst annotationColumns', '<script>Storage.prototype.setItem = function(){throw new Error("quota");};</script><script>\nconst annotationColumns'), encoding='utf-8')
        result = browser_run(self, target, "result.blocked=document.getElementById('save-next').disabled; result.warning=document.getElementById('storage-status').textContent;", self.root/'profile-failure')
        self.assertTrue(result['blocked'])
        self.assertIn('No se pudo guardar', result['warning'])

    def test_browser_filters_navigation_annotations_and_csv_download(self):
        candidates = [os.environ.get('REVIEW_BROWSER_EXE', ''),
                      r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                      shutil.which('chromium') or '', shutil.which('google-chrome') or '']
        browser = next((p for p in candidates if p and Path(p).is_file()), None)
        if not browser:
            self.skipTest('Set REVIEW_BROWSER_EXE to an installed Chromium/Edge browser')
        target, _ = review.generate(self.input, self.sample, self.output)
        harness = r'''
<script>
(async () => {
  const result = {filters:{}};
  try {
    const all = Array.from(document.querySelectorAll('.signal-card'));
    const filterControl = document.getElementById('filter');
    for(const value of ['ALL','BUY','SELL','B0','PB1','B0+PB1']) {
      filterControl.value = value;
      filterControl.dispatchEvent(new Event('change'));
      result.filters[value] = document.getElementById('picker').options.length;
    }
    filterControl.value = 'ALL'; filterControl.dispatchEvent(new Event('change'));
    const notes = all[0].querySelector('[data-field="reviewer_notes"]');
    notes.value = 'Texto, "cita"\nsegunda línea ñ';
    notes.dispatchEvent(new Event('input', {bubbles:true}));
    const fields = {chart_quality:'CLEAR',signal_alignment:'ALIGNED',context_class:'TREND',reviewer_decision:'VALID'};
    for(const [field,value] of Object.entries(fields)) all[0].querySelector(`button[data-field="${field}"][data-value="${value}"]`).click();
    all[1].querySelector('[data-field="reviewer_notes"]').value = '=1+1';
    all[1].querySelector('textarea').dispatchEvent(new Event('input', {bubbles:true}));
    document.getElementById('next').click();
    result.next = all.findIndex(card => !card.hidden);
    document.getElementById('prev').click();
    result.previous = all.findIndex(card => !card.hidden);
    result.notesRetained = notes.value;
    filterControl.value = 'SELL'; filterControl.dispatchEvent(new Event('change'));
    result.visible = all.findIndex(card => !card.hidden);
    result.status = document.getElementById('runtime-status').textContent;
    let blob;
    URL.createObjectURL = value => { blob = value; return 'blob:test'; };
    URL.revokeObjectURL = () => {};
    HTMLAnchorElement.prototype.click = function() { result.filename = this.download; };
    document.getElementById('download').click();
    result.csv = await blob.text();
  } catch(error) { result.error = String(error); }
  const pre = document.createElement('pre'); pre.id = 'browser-test-result';
  pre.textContent = JSON.stringify(result); document.body.appendChild(pre);
})();
</script>
'''
        target.write_text(target.read_text(encoding='utf-8').replace('</body>', harness+'</body>'), encoding='utf-8')
        run = subprocess.run([browser, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                              '--disable-background-networking', '--disable-extensions',
                              '--user-data-dir='+str(self.root/'browser-profile'), '--virtual-time-budget=3000',
                              '--dump-dom', target.as_uri()], capture_output=True, encoding='utf-8', errors='replace', timeout=45,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        parsed = ElementText('browser-test-result')
        parsed.feed(run.stdout)
        self.assertTrue(parsed.value(), f'Browser produced no test result: {run.stderr[-2000:]}')
        result = json.loads(parsed.value())
        self.assertNotIn('error', result)
        self.assertEqual(result['filters'], {'ALL':3,'BUY':2,'SELL':1,'B0':1,'PB1':1,'B0+PB1':1})
        self.assertEqual((result['next'], result['previous'], result['visible']), (1, 0, 1))
        self.assertIn('sin conexión', result['status'])
        rows = list(csv.DictReader(io.StringIO(result['csv'].lstrip('\ufeff'), newline='')))
        self.assertEqual(len(rows), 3)  # Export includes hidden cards, in original sample order.
        self.assertEqual([r['sample_id'] for r in rows], [r['signal_id'] for r in self.samples])
        self.assertEqual(rows[0]['reviewer_notes'], 'Texto, "cita"\nsegunda línea ñ')
        self.assertEqual(rows[0]['reviewer_notes'], result['notesRetained'])
        self.assertEqual(rows[1]['reviewer_notes'], "'=1+1")
        self.assertEqual([rows[0][f] for f in review.REVIEW_FIELDS[:-1]], ['CLEAR','ALIGNED','TREND','VALID'])
        self.assertTrue(result['filename'].startswith('signal_review_annotations_'))
        self.assertNotEqual(result['filename'], self.sample.name)
        with self.sample.open(encoding='utf-8', newline='') as stream:
            self.assertEqual(list(csv.DictReader(stream)), self.samples)


class RealReviewTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SCANNER_CSV_PATH') and os.environ.get('SCANNER_SAMPLE_PATH'),
                         'Set SCANNER_CSV_PATH and SCANNER_SAMPLE_PATH for real 50-signal integration')
    def test_real_50_signals_and_input_integrity(self):
        original, sample = Path(os.environ['SCANNER_CSV_PATH']), Path(os.environ['SCANNER_SAMPLE_PATH'])
        before = [scanner.source_sha256(path) for path in (original, sample)]
        with tempfile.TemporaryDirectory() as directory:
            target, records = review.generate(original, sample, Path(directory))
            with sample.open(encoding='utf-8-sig', newline='') as stream:
                expected = list(csv.DictReader(stream))
            self.assertEqual(len(records), 50)
            self.assertEqual([r['sample_id'] for r in records], [r['signal_id'] for r in expected])
            for record in records:
                self.assertEqual(record['status'], 'OK', record['errors'])
                self.assertEqual(len(record['bars']), 31)
                self.assertEqual(record['bars'][-1][0], record['bar_time_epoch'])
                self.assertEqual(sum(b[0] == record['bar_time_epoch'] for b in record['bars']), 1)
                self.assertTrue(all(b[0] <= record['bar_time_epoch'] for b in record['bars']))
            document = target.read_text(encoding='utf-8')
            self.assertEqual(document.count('class="signal-card"'), 50)
            self.assertEqual(document.count('data-bar-time='), 50*31)
            result = browser_run(self, target, r'''
const filter=document.getElementById('filter'); filter.value='BUY'; filter.dispatchEvent(new Event('change'));
let blob; URL.createObjectURL = value => {blob=value;return 'blob:test';};
URL.revokeObjectURL=()=>{}; HTMLAnchorElement.prototype.click=function(){};
document.getElementById('download').click(); result.csv=await blob.text();
result.count=document.getElementById('picker').options.length;
''', Path(directory)/'profile-export')
            exported = list(csv.DictReader(io.StringIO(result['csv'].lstrip('\ufeff'), newline='')))
            self.assertEqual(len(exported), 50)
            self.assertLess(result['count'], 50)
            self.assertEqual([r['sample_id'] for r in exported], [r['signal_id'] for r in expected])
        self.assertEqual(before, [scanner.source_sha256(path) for path in (original, sample)])


if __name__ == '__main__':
    unittest.main()
