"""Deterministic fixtures; real CSV integration is opt-in via SCANNER_CSV_PATH."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import analyze_scanner as scanner

ACCOUNT = "98765432109876"
SERVER = "PrivateBroker-Demo"
IDENTITY = "|".join(("scanner-v1", SERVER.encode("utf-16-be").hex().upper(), ACCOUNT,
                     "XAUUSD".encode("utf-16-be").hex().upper(), "1997101", "tester",
                     "fixture", "50", "3", "3", "2", "8", "12", ""))
START = int(datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc).timestamp())


def make_row(index=0, lanes=("b0_buy",), **changes):
    decision = START + index*300
    row = {name: "0" for name in scanner.COLUMNS}
    row.update(identity=IDENTITY, decision_server=str(decision), signal_open_server=str(decision-300),
               observed_server=str(decision), delay_seconds="0", decision_utc=str(decision-7200),
               decision_ny=str(decision-21600), observed_utc=str(decision-7200),
               server_offset_minutes="120", ny_offset_minutes="-240", session="IN", data_status="OK",
               h1_open_server=str(decision//3600*3600-3600), h1_close="101.0", h1_ema="100.0",
               h1_gate="1", bid="104.0", ask="104.10", spread_points="10.0", trade_authorized="0")
    row["m5_window"] = ";".join(f"{decision-(4-i)*300}:{c}:{c+0.25}:{c-0.25}:{c}"
                                for i, c in enumerate((103.0, 102.0, 101.0, 104.0)))
    for lane in scanner.LANES:
        row[f"{lane}_raw"] = "1" if lane in lanes else "0"
        row[f"{lane}_reason"] = "ACCEPT_DIAGNOSTIC" if lane in lanes else "NO_BREAKOUT"
        row[f"{lane}_episode_server"] = str(decision-300 if lane in lanes else 0)
    if lanes and all(lane.endswith("sell") for lane in lanes):
        row["h1_gate"] = "-1"
        row["h1_close"] = "99.0"
    row.update(changes)
    for lane in scanner.LANES:
        module, direction = lane.upper().split("_")
        row[f"{lane}_key"] = f'{row["identity"]}:{row["decision_server"]}:{module}:{direction}'
    state = [int(row["decision_server"]), index+1, int(row["h1_gate"]), 1] + [0]*20
    row["state"] = ";".join(map(str, state))
    row["checksum"] = scanner.checksum(row)
    return row


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input = self.root / "scanner.csv"
        self.output = self.root / "results"

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, rows, columns=scanner.COLUMNS, encoding="utf-8", newline="\r\n"):
        with self.input.open("w", encoding=encoding, newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator=newline)
            writer.writeheader()
            writer.writerows(rows)

    def run_analysis(self, rows=None, size=50, seed=20260917):
        if rows is not None:
            self.write(rows)
        return scanner.analyze(self.input, self.output, size, seed)

    def read(self, name):
        with (self.output / name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def assert_invalid(self, rows, text):
        self.write(rows)
        with self.assertRaisesRegex(scanner.ValidationError, text):
            self.run_analysis()
        self.assertFalse(self.output.exists())

    def test_valid_small_csv(self):
        summary = self.run_analysis([make_row(), make_row(1, ()), make_row(2, ("pb1_sell",))])
        self.assertEqual(summary["total_rows"], 3)
        self.assertEqual(summary["unique_signal_bars"], 2)
        self.assertEqual(summary["actual_sample_size"], 2)
        self.assertEqual(set(summary["validations"].values()), {"PASS"})
        reduced = self.read(scanner.OUTPUT_NAMES[0])
        self.assertEqual(list(reduced[0]), list(scanner.REDUCED_COLUMNS))
        self.assertEqual([r["signal_id"] for r in reduced], ["SIG-000001", "SIG-000002"])
        self.assertEqual(reduced[0]["signal_open_server_text"], "2026-06-10 14:55:00")
        review = self.read(scanner.OUTPUT_NAMES[1])
        self.assertTrue(all(row["review_status"] == "PENDING" and row["review_notes"] == "" for row in review))

    def test_missing_column(self):
        self.write([make_row()], scanner.COLUMNS[:-1])
        with self.assertRaisesRegex(scanner.ValidationError, "Fila 1.*39 columnas"):
            self.run_analysis()
        self.assertFalse(self.output.exists())

    def test_duplicate_header(self):
        self.write([make_row()], scanner.COLUMNS[:-1]+("identity",))
        with self.assertRaisesRegex(scanner.ValidationError, "39 columnas"):
            self.run_analysis()

    def test_duplicate_decision(self):
        self.assert_invalid([make_row(), make_row()], "Fila 3.*duplicado")

    def test_backward_timestamp(self):
        self.assert_invalid([make_row(1), make_row(0)], "Fila 3.*retroceso")

    def test_multiple_identities(self):
        other = IDENTITY.replace("|fixture|", "|another|")
        self.assert_invalid([make_row(), make_row(1, identity=other)], "más de una identidad")

    def test_authorized_trade(self):
        self.assert_invalid([make_row(trade_authorized="1")], "trade_authorized")

    def test_accepted_outside_session(self):
        self.assert_invalid([make_row(session="OUT")], "fuera de sesión")

    def test_accepted_bad_data(self):
        self.assert_invalid([make_row(data_status="DATA_EMA")], "datos incompletos")

    def test_buy_bearish_h1(self):
        self.assert_invalid([make_row(h1_gate="-1")], "h1_gate")

    def test_sell_bullish_h1(self):
        self.assert_invalid([make_row(lanes=("b0_sell",), h1_gate="1")], "h1_gate")

    def test_buy_sell_conflict(self):
        self.assert_invalid([make_row(lanes=("b0_buy", "pb1_sell"))], "conflicto BUY/SELL")

    def test_overlap_once_canonical_order(self):
        summary = self.run_analysis([make_row(lanes=("pb1_buy", "b0_buy"))])
        self.assertEqual(summary["unique_signal_bars"], 1)
        self.assertEqual(summary["total_lane_acceptances"], 2)
        self.assertEqual(summary["overlap_bars"], 1)
        row = self.read(scanner.OUTPUT_NAMES[0])[0]
        self.assertEqual((row["module"], row["direction"], row["overlap"]), ("B0+PB1", "BUY", "1"))
        self.assertEqual(row["accepted_lanes"], "b0_buy,pb1_buy")

    def test_sanitization_all_outputs(self):
        original = make_row()
        self.run_analysis([original])
        forbidden = (IDENTITY, ACCOUNT, SERVER, SERVER.encode("utf-16-be").hex().upper())
        for name in scanner.OUTPUT_NAMES:
            text = (self.output / name).read_text(encoding="utf-8")
            for token in forbidden + tuple(original[f"{lane}_key"] for lane in scanner.LANES):
                self.assertNotIn(token, text)
        self.assertNotIn(str(self.input.parent), (self.output / scanner.OUTPUT_NAMES[2]).read_text())

    def test_leak_in_filename_aborts_publication(self):
        self.input = self.root / f"scanner_{ACCOUNT}.csv"
        self.assert_invalid([make_row()], "token sensible")

    def test_timezone_independent(self):
        with mock.patch.dict(os.environ, {"TZ": "Pacific/Honolulu"}), mock.patch("time.localtime", side_effect=AssertionError):
            self.assertEqual(scanner.timestamp_text(START), "2026-06-10 15:00:00")
        with mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            self.assertEqual(scanner.timestamp_text(START), "2026-06-10 15:00:00")

    def test_valid_m5_window(self):
        original = make_row()
        bars = scanner.parse_m5_window(original["m5_window"], START-300)
        self.assertEqual(len(bars), 4)
        self.assertEqual(bars[-1], (START-300, 104.0, 104.25, 103.75, 104.0))

    def test_bad_last_window_timestamp(self):
        shifted = make_row(1)["m5_window"]
        self.assert_invalid([make_row(m5_window=shifted)], "timestamp final incorrecto")

    def test_invalid_ohlc(self):
        bad = make_row()["m5_window"].replace("104.25", "103.0")
        self.assert_invalid([make_row(m5_window=bad)], "OHLC incoherente")

    def test_nonfinite_price(self):
        self.assert_invalid([make_row(bid="nan")], "no finito")

    def test_nonnumeric_integer(self):
        self.assert_invalid([make_row(trade_authorized="zero")], "entero inválido")

    def test_signal_open_alignment(self):
        self.assert_invalid([make_row(signal_open_server=str(START))], "decision_server - 300")

    def test_open_h1(self):
        self.assert_invalid([make_row(h1_open_server=str(START))], "H1 abierta")

    def test_checksum_corruption(self):
        row = make_row()
        row["checksum"] = "00000000"
        self.assert_invalid([row], "checksum de fila")

    def test_key_corruption(self):
        row = make_row()
        row["b0_buy_key"] = "invalid"
        row["checksum"] = scanner.checksum(row)
        self.assert_invalid([row], "clave de evento")

    def test_empty_file(self):
        self.assert_invalid([], "CSV vacío")

    def test_no_accepted_signals(self):
        summary = self.run_analysis([make_row(lanes=())])
        self.assertEqual(summary["unique_signal_bars"], 0)
        self.assertIsNone(summary["accepted_spread_points"]["median"])
        self.assertEqual(self.read(scanner.OUTPUT_NAMES[0]), [])

    def test_utf8_bom_and_lf(self):
        self.write([make_row()], encoding="utf-8-sig", newline="\n")
        self.assertEqual(self.run_analysis()["total_rows"], 1)

    def test_large_csv_field(self):
        window = make_row()["m5_window"].replace(":103.0:", ":" + "0"*140000 + "103.0:", 1)
        self.assertEqual(self.run_analysis([make_row(m5_window=window)])["unique_signal_bars"], 1)

    def test_raw_original_unchanged(self):
        self.write([make_row()])
        before = self.input.read_bytes()
        self.run_analysis()
        self.assertEqual(before, self.input.read_bytes())

    def test_validation_failure_preserves_previous_outputs(self):
        self.run_analysis([make_row()])
        before = {name: (self.output/name).read_bytes() for name in scanner.OUTPUT_NAMES}
        self.write([make_row(trade_authorized="1")])
        with self.assertRaises(scanner.ValidationError):
            self.run_analysis()
        self.assertEqual(before, {name: (self.output/name).read_bytes() for name in scanner.OUTPUT_NAMES})

    def test_privacy_failure_preserves_previous_outputs(self):
        self.run_analysis([make_row()])
        before = {name: (self.output/name).read_bytes() for name in scanner.OUTPUT_NAMES}
        self.input = self.root / f"{ACCOUNT}.csv"
        self.write([make_row()])
        with self.assertRaisesRegex(scanner.ValidationError, "token sensible"):
            self.run_analysis()
        self.assertEqual(before, {name: (self.output/name).read_bytes() for name in scanner.OUTPUT_NAMES})

    def test_publication_failure_rolls_back(self):
        self.run_analysis([make_row()])
        before = {name: (self.output/name).read_bytes() for name in scanner.OUTPUT_NAMES}
        real_replace = os.replace

        def fail_stage(source, target):
            if Path(source).name.startswith(".scanner-stage-"):
                raise OSError("synthetic publication failure")
            return real_replace(source, target)

        with mock.patch.object(scanner.os, "replace", side_effect=fail_stage), self.assertRaises(OSError):
            self.run_analysis()
        self.assertEqual(before, {name: (self.output/name).read_bytes() for name in scanner.OUTPUT_NAMES})

    def test_source_change_blocks_publication(self):
        self.write([make_row()])
        with mock.patch.object(scanner, "source_sha256", side_effect=("a"*64, "b"*64)), self.assertRaisesRegex(scanner.ValidationError, "cambió"):
            self.run_analysis()
        self.assertFalse(self.output.exists())

    def test_unrelated_output_files_preserved(self):
        self.output.mkdir()
        (self.output/"unrelated.txt").write_text("keep")
        self.write([make_row()])
        with self.assertRaisesRegex(scanner.ValidationError, "archivos ajenos"):
            self.run_analysis()
        self.assertEqual((self.output/"unrelated.txt").read_text(), "keep")

    def test_cli_failure_nonzero_and_no_leak(self):
        self.write([make_row(trade_authorized="1")])
        command = [sys.executable, str(ROOT/"tools"/"analyze_scanner.py"), "--input", str(self.input),
                   "--output-dir", "artifacts/scanner_analysis/unittest_invalid"]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Fila 2", result.stderr)
        self.assertNotIn(ACCOUNT, result.stderr)
        self.assertFalse((scanner.ARTIFACT_ROOT/"unittest_invalid").exists())

    def test_internal_paths_independent_of_cwd(self):
        with mock.patch("pathlib.Path.cwd", return_value=self.root):
            self.assertEqual(scanner.repository_path("artifacts/scanner_analysis/example"),
                             ROOT/"artifacts/scanner_analysis/example")


class SamplingTests(unittest.TestCase):
    def signals(self, per_stratum):
        rows = []
        for stratum in scanner.STRATA:
            module, direction = stratum.split()
            for _ in range(per_stratum):
                rows.append(dict(module=module, direction=direction, decision_server=START+len(rows)*300,
                                 signal_id=f"SIG-{len(rows)+1:06d}"))
        return rows

    def test_deterministic_exclusive_sampling(self):
        rows = self.signals(15)
        first, quotas = scanner.stratified_sample(rows, 50, 20260917)
        second, _ = scanner.stratified_sample(rows, 50, 20260917)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 50)
        self.assertEqual(len({r["decision_server"] for r in first}), 50)
        self.assertEqual([quotas[s]["selected"] for s in scanner.STRATA], [10,10,10,10,5,5])
        self.assertEqual(first, sorted(first, key=lambda r: r["decision_server"]))

    def test_insufficient_strata_not_oversampled(self):
        sample, quotas = scanner.stratified_sample(self.signals(2), 50, 42)
        self.assertEqual(len(sample), 12)
        self.assertTrue(all(v["selected"] <= v["available"] for v in quotas.values()))
        self.assertEqual(sum(v["shortfall"] for v in quotas.values()), 38)

    def test_other_sample_sizes(self):
        for size in (0, 1, 7, 19, 49):
            with self.subTest(size=size):
                sample, _ = scanner.stratified_sample(self.signals(30), size, 42)
                self.assertEqual(len(sample), size)

    def test_negative_size(self):
        with self.assertRaises(scanner.ValidationError):
            scanner.stratified_sample([], -1, 42)


@unittest.skipUnless(os.environ.get("SCANNER_CSV_PATH"), "Set SCANNER_CSV_PATH to run the real CSV integration; no file discovery")
class RealCsvIntegrationTests(unittest.TestCase):
    def test_expected_counts_and_privacy(self):
        source = Path(os.environ["SCANNER_CSV_PATH"])
        self.assertTrue(source.is_file(), "Explicit integration input is missing")
        before = scanner.source_sha256(source)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/"result"
            summary = scanner.analyze(source, destination, 50, 20260917)
            expected = {
                "total_rows": 12848, "in_session_bars": 2256, "complete_ny_sessions": 47,
                "bars_per_complete_session": 48, "ny_days_with_valid_session": 47,
                "total_lane_acceptances": 284, "unique_signal_bars": 266, "overlap_bars": 18,
                "buy_sell_conflicts": 0, "duplicates": 0, "temporal_regressions": 0,
                "authorized_trades": 0, "actual_sample_size": 50,
            }
            for field, value in expected.items():
                with self.subTest(field=field):
                    self.assertEqual(summary[field], value)
            self.assertEqual(summary["accepted_by_lane"], dict(zip(scanner.LANES, (103,97,47,37))))
            self.assertEqual(summary["exclusive_distribution"], dict(zip(scanner.STRATA, (93,89,37,29,10,8))))
            with source.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                original = next(reader)
                sensitive, *_ = scanner.identity_metadata(original["identity"], 2)
            scanner.audit_outputs(destination, sensitive)
            self.assertEqual(summary["input_sha256"], before)
        self.assertEqual(scanner.source_sha256(source), before)


if __name__ == "__main__":
    unittest.main()
