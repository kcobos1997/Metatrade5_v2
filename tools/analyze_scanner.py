"""Offline scanner-v1 validation and sanitized signal sampling (standard library only)."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "scanner_analysis"
LANES = ("b0_buy", "b0_sell", "pb1_buy", "pb1_sell")
BASE_COLUMNS = (
    "identity", "decision_server", "signal_open_server", "observed_server",
    "delay_seconds", "decision_utc", "decision_ny", "observed_utc",
    "server_offset_minutes", "ny_offset_minutes", "session", "data_status",
    "h1_open_server", "h1_close", "h1_ema", "h1_gate", "bid", "ask",
    "spread_points", "m5_window", "trade_authorized",
)
COLUMNS = BASE_COLUMNS + tuple(
    f"{lane}_{field}" for lane in LANES for field in ("key", "raw", "reason", "episode_server")
) + ("state", "checksum")
INTEGER_COLUMNS = (
    "decision_server", "signal_open_server", "observed_server", "delay_seconds",
    "decision_utc", "decision_ny", "observed_utc", "server_offset_minutes",
    "ny_offset_minutes", "h1_open_server", "h1_gate", "trade_authorized",
) + tuple(f"{lane}_{field}" for lane in LANES for field in ("raw", "episode_server"))
FLOAT_COLUMNS = ("h1_close", "h1_ema", "bid", "ask", "spread_points")
TIME_COLUMNS = (
    "decision_server", "signal_open_server", "observed_server", "decision_utc",
    "decision_ny", "observed_utc", "h1_open_server",
) + tuple(f"{lane}_episode_server" for lane in LANES)
DATA_CODES = {"OK", "DATA_M5", "DATA_H1", "DATA_EMA", "DATA_TICK"}
REASONS = DATA_CODES - {"OK"} | {
    "GAP_RESET", "BASELINE", "NO_SETUP", "EQUALITY", "NO_BREAKOUT",
    "EPISODE_CONSUMED", "H1_CHANGED", "COOLDOWN", "FRESH_SEQUENCE_REQUIRED",
    "H1_NEUTRAL", "H1_OPPOSED", "SESSION_UNKNOWN", "OUTSIDE_SESSION", "ACCEPT_DIAGNOSTIC",
}
REDUCED_COLUMNS = (
    "signal_id", "decision_server", "decision_server_text", "signal_open_server",
    "signal_open_server_text", "decision_ny", "decision_ny_text", "direction",
    "module", "accepted_lanes", "overlap", "h1_gate", "h1_open_server", "h1_close",
    "h1_ema", "bid", "ask", "spread_points", "delay_seconds", "signal_open",
    "signal_high", "signal_low", "signal_close",
) + tuple(f"{lane}_reason" for lane in LANES) + ("m5_window",)
REVIEW_COLUMNS = ("review_status", "structure_quality", "signal_quality", "review_notes")
STRATA = ("B0 BUY", "B0 SELL", "PB1 BUY", "PB1 SELL", "B0+PB1 BUY", "B0+PB1 SELL")
WEIGHTS = (2, 2, 2, 2, 1, 1)
OUTPUT_NAMES = ("signals_reduced.csv", "signals_review_sample.csv", "scanner_summary.json")
VALIDATIONS = (
    "required_39_columns", "one_identity", "strictly_increasing_decisions",
    "no_duplicate_decisions", "trade_authorized_zero", "typed_fields",
    "accepted_session_in", "accepted_data_ok", "accepted_h1_direction",
    "no_buy_sell_conflict", "accepted_raw_one", "signal_open_alignment",
    "accepted_m5_window", "accepted_h1_closed", "event_keys", "state_types",
    "row_checksums", "sample_unique", "sample_within_strata", "sanitized_outputs",
    "source_unchanged",
)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class ValidationError(ValueError):
    """Diagnostics deliberately exclude raw values, identity, paths and keys."""
    def __init__(self, row: int, cause: str):
        self.row = row
        super().__init__(f"Fila {row}: {cause}")


def require(condition: bool, row: int, cause: str) -> None:
    if not condition:
        raise ValidationError(row, cause)


def integer(value: str, row: int, field: str) -> int:
    require(bool(re.fullmatch(r"-?(0|[1-9][0-9]*)", value)), row, f"entero inválido en {field}")
    try:
        return int(value)
    except ValueError:
        raise ValidationError(row, f"entero inválido en {field}") from None


def finite(value: str, row: int, field: str) -> float:
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ValidationError(row, f"número inválido en {field}") from None
    require(math.isfinite(number), row, f"número no finito en {field}")
    return number


def timestamp_text(value: int, row: int = 0) -> str:
    require(value >= 0, row, "timestamp negativo")
    if value == 0:
        return ""  # Scanner convention: unknown, not a real 1970 observation.
    try:
        return (EPOCH + timedelta(seconds=value)).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, ValueError):
        raise ValidationError(row, "timestamp fuera de rango") from None


def checksum(row: dict[str, str]) -> str:
    # MQL5 Hash operates on UTF-16 code units. Native scanner output is ASCII.
    body = ",".join(row[name] for name in COLUMNS[:-1])
    data = body.encode("utf-16-le")
    value = 2166136261
    for index in range(0, len(data), 2):
        value = ((value ^ (data[index] | data[index + 1] << 8)) * 16777619) & 0xFFFFFFFF
    return f"{value:08X}"


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity_metadata(identity: str, row: int) -> tuple[set[str], int, int, int]:
    parts = identity.split("|")
    require(len(parts) == 14 and parts[0] == "scanner-v1", row, "formato de identity no soportado")
    require(parts[5] in {"demo", "tester"}, row, "modo de identity inválido")
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", parts[6])), row, "RunId inválido")
    for index in (1, 3, 13):
        require(len(parts[index]) % 4 == 0 and bool(re.fullmatch(r"[0-9A-F]*", parts[index])),
                row, "codificación de identity inválida")
    require(bool(parts[1]) and bool(parts[3]), row, "identity incompleta")
    values = {index: integer(parts[index], row, "identity") for index in (2, 4, 7, 8, 9, 10, 11, 12)}
    require(values[2] >= 0 and 0 <= values[4] < 2**64, row, "identity numérica inválida")
    require(2 <= values[7] <= 200 and 2 <= values[8] <= 20 and 1 <= values[9] <= 100
            and 0 <= values[10] <= 100 and 0 <= values[11] < values[12] <= 24,
            row, "parámetros de identity inválidos")
    try:
        server = bytes.fromhex(parts[1]).decode("utf-16-be")
    except (ValueError, UnicodeError):
        raise ValidationError(row, "servidor codificado inválido") from None
    sensitive = {identity, parts[1], parts[2], parts[4], server}
    # Also check meaningful decoded server components, not only its entire name.
    sensitive.update(part for part in re.split(r"[^\w]+", server) if len(part) >= 3)
    return sensitive, values[11], values[12], max(values[8], values[9]) + 1


def parse_m5_window(value: str, signal_open: int, row: int = 0) -> list[tuple]:
    bars = []
    for item in value.split(";"):
        fields = item.split(":")
        require(len(fields) == 5, row, "formato m5_window inválido")
        stamp = integer(fields[0], row, "m5_window.time")
        timestamp_text(stamp, row)
        prices = tuple(finite(v, row, "m5_window.OHLC") for v in fields[1:])
        opening, high, low, close = prices
        require(stamp > 0 and min(prices) > 0, row, "m5_window no positivo")
        require(high >= max(opening, close) and low <= min(opening, close) and high >= low,
                row, "OHLC incoherente en m5_window")
        require(not bars or stamp == bars[-1][0] + 300, row, "hueco o duplicado en m5_window")
        bars.append((stamp, *prices))
    require(bars[-1][0] == signal_open, row, "timestamp final incorrecto en m5_window")
    return bars


def typed_row(raw: dict[str, str], line: int) -> dict:
    values = {key: integer(raw[key], line, key) for key in INTEGER_COLUMNS}
    values.update({key: finite(raw[key], line, key) for key in FLOAT_COLUMNS})
    for key in TIME_COLUMNS:
        timestamp_text(values[key], line)
    require(values["decision_server"] > 300, line, "decision_server inválido")
    require(raw["session"] in {"IN", "OUT", "UNKNOWN"}, line, "session inválida")
    require(raw["data_status"] in DATA_CODES, line, "data_status inválido")
    require(values["h1_gate"] in {-1, 0, 1}, line, "h1_gate inválido")
    require(values["trade_authorized"] == 0, line, "trade_authorized debe ser 0")
    require(values["signal_open_server"] == values["decision_server"] - 300,
            line, "signal_open_server debe ser decision_server - 300")
    require(values["delay_seconds"] == values["observed_server"] - values["decision_server"],
            line, "delay_seconds incoherente")
    require(-840 <= values["server_offset_minutes"] <= 840 and
            values["ny_offset_minutes"] in {0, -240, -300}, line, "offset horario inválido")
    for lane in LANES:
        require(values[f"{lane}_raw"] in {0, 1}, line, "raw debe ser 0 o 1")
        require(raw[f"{lane}_reason"] in REASONS, line, "código reason desconocido")
        module, direction = lane.upper().split("_")
        expected = f'{raw["identity"]}:{values["decision_server"]}:{module}:{direction}'
        require(raw[f"{lane}_key"] == expected, line, "clave de evento inconsistente")
    state = raw["state"].split(";")
    require(len(state) == 24, line, "state debe contener 24 enteros")
    state = [integer(v, line, "state") for v in state]
    require(state[0] == values["decision_server"] and state[1] > 0 and
            state[2] in {-1, 0, 1, 9} and state[3] in {0, 1}, line, "checkpoint inválido")
    for index in range(4, 24, 5):
        require(state[index] in {0, 1} and 0 <= state[index+1] <= state[0] and
                0 <= state[index+2] <= state[1] and 0 <= state[index+3] <= 1000000000 and
                0 <= state[index+4] <= state[1]+100, line, "estado de canal inválido")
    require(bool(re.fullmatch(r"[0-9A-F]{8}", raw["checksum"])), line, "formato checksum inválido")
    require(raw["checksum"] == checksum(raw), line, "checksum de fila incorrecto")
    return values


def collect(path: Path) -> tuple[list[dict], dict, set[str]]:
    """Keep counters/day slots, a single identity and accepted bars only."""
    csv.field_size_limit(16 * 1024 * 1024)
    signals = []
    sessions, data_statuses, gates, lane_counts = Counter(), Counter(), Counter(), Counter()
    exclusive, ny_hours = Counter(), Counter()
    day_slots = defaultdict(set)
    identity = None
    sensitive = set()
    previous = None
    first = last = None
    start_hour = end_hour = window_size = 0
    total = 0
    line = 1
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            header = reader.fieldnames
            require(header is not None and len(header) == 39 and set(header) == set(COLUMNS),
                    1, "se requieren las 39 columnas únicas del scanner-v1")
            for raw in reader:
                line = reader.line_num
                require(None not in raw and all(v is not None for v in raw.values()),
                        line, "número de campos incorrecto")
                if identity is None:
                    identity = raw["identity"]
                    sensitive, start_hour, end_hour, window_size = identity_metadata(identity, line)
                require(raw["identity"] == identity, line, "más de una identidad")
                values = typed_row(raw, line)
                decision = values["decision_server"]
                if previous is not None:
                    require(decision != previous, line, "decision_server duplicado")
                    require(decision > previous, line, "retroceso temporal en decision_server")
                previous = last = decision
                if first is None:
                    first = decision
                total += 1
                sessions[raw["session"]] += 1
                data_statuses[raw["data_status"]] += 1
                gates[str(values["h1_gate"])] += 1
                ny_text = timestamp_text(values["decision_ny"], line)
                if raw["session"] == "IN":
                    require(bool(ny_text), line, "sesión IN sin timestamp NY")
                    ny_dt = EPOCH + timedelta(seconds=values["decision_ny"])
                    require(start_hour <= ny_dt.hour < end_hour, line, "session IN fuera del horario configurado")
                    if raw["data_status"] == "OK":
                        day_slots[ny_text[:10]].add(ny_dt.hour*3600 + ny_dt.minute*60 + ny_dt.second)
                accepted = [lane for lane in LANES if raw[f"{lane}_reason"] == "ACCEPT_DIAGNOSTIC"]
                if not accepted:
                    continue
                directions = {lane.rsplit("_", 1)[1].upper() for lane in accepted}
                require(len(directions) == 1, line, "conflicto BUY/SELL en la misma barra")
                direction = next(iter(directions))
                require(raw["session"] == "IN", line, "señal aceptada fuera de sesión IN")
                require(raw["data_status"] == "OK", line, "señal aceptada con datos incompletos")
                require(values["h1_gate"] == (1 if direction == "BUY" else -1),
                        line, "dirección aceptada incompatible con h1_gate")
                require(all(values[f"{lane}_raw"] == 1 for lane in accepted), line, "señal aceptada con raw=0")
                require(values["h1_open_server"] > 0 and
                        values["h1_open_server"]+3600 <= decision < values["h1_open_server"]+7200,
                        line, "H1 abierta o antigua en señal aceptada")
                require(min(values[key] for key in ("h1_close", "h1_ema", "bid", "ask")) > 0 and
                        values["ask"] >= values["bid"] and values["spread_points"] >= 0 and
                        values["delay_seconds"] >= 0, line, "precios o demora inválidos en señal aceptada")
                bars = parse_m5_window(raw["m5_window"], values["signal_open_server"], line)
                require(len(bars) == window_size, line, "longitud m5_window incompatible con configuración")
                modules = {lane.split("_", 1)[0].upper() for lane in accepted}
                module = "+".join(m for m in ("B0", "PB1") if m in modules)
                signal = {key: values[key] for key in (
                    "decision_server", "signal_open_server", "decision_ny", "h1_gate", "h1_open_server",
                    "h1_close", "h1_ema", "bid", "ask", "spread_points", "delay_seconds")}
                signal.update({
                    "signal_id": f"SIG-{len(signals)+1:06d}",
                    "decision_server_text": timestamp_text(decision, line),
                    "signal_open_server_text": timestamp_text(values["signal_open_server"], line),
                    "decision_ny_text": ny_text, "direction": direction, "module": module,
                    "accepted_lanes": ",".join(accepted), "overlap": int(len(modules) == 2),
                    "m5_window": raw["m5_window"],
                })
                signal.update(zip(("signal_open", "signal_high", "signal_low", "signal_close"), bars[-1][1:]))
                signal.update({f"{lane}_reason": raw[f"{lane}_reason"] for lane in LANES})
                signals.append(signal)
                lane_counts.update(accepted)
                exclusive[f"{module} {direction}"] += 1
                ny_hours[ny_text[11:13]] += 1
    except (csv.Error, UnicodeError):
        raise ValidationError(line, "CSV o codificación UTF-8 inválidos") from None
    require(total > 0, 1, "CSV vacío: no se puede validar una identidad")
    expected_slots = set(range(start_hour*3600, end_hour*3600, 300))
    spreads = [s["spread_points"] for s in signals]
    summary = {
        "total_rows": total, "first_decision": first, "last_decision": last,
        "first_decision_text": timestamp_text(first), "last_decision_text": timestamp_text(last),
        "identity_count": 1, "duplicates": 0, "temporal_regressions": 0, "buy_sell_conflicts": 0,
        "authorized_trades": 0, "session_distribution": dict(sorted(sessions.items())),
        "data_status_distribution": dict(sorted(data_statuses.items())),
        "h1_gate_distribution": dict(sorted(gates.items())), "in_session_bars": sessions["IN"],
        "ny_days_with_valid_session": len(day_slots),
        "complete_ny_sessions": sum(slots == expected_slots for slots in day_slots.values()),
        "bars_per_complete_session": len(expected_slots),
        "accepted_by_lane": {lane: lane_counts[lane] for lane in LANES},
        "total_lane_acceptances": sum(lane_counts.values()), "unique_signal_bars": len(signals),
        "overlap_bars": sum(s["overlap"] for s in signals),
        "exclusive_distribution": {stratum: exclusive[stratum] for stratum in STRATA},
        "ny_hour_distribution": dict(sorted(ny_hours.items())),
        "accepted_spread_points": {
            "minimum": min(spreads) if spreads else None,
            "median": statistics.median(spreads) if spreads else None,
            "mean": statistics.fmean(spreads) if spreads else None,
            "maximum": max(spreads) if spreads else None,
        },
        "accepted_bars_with_nonzero_delay": sum(s["delay_seconds"] != 0 for s in signals),
    }
    return signals, summary, sensitive


def stratified_sample(signals: list[dict], size: int, seed: int) -> tuple[list[dict], dict]:
    require(size >= 0, 0, "sample_size debe ser >= 0")
    quotas = [size * weight // sum(WEIGHTS) for weight in WEIGHTS]
    remainder_order = sorted(range(6), key=lambda i: (-(size*WEIGHTS[i] % sum(WEIGHTS)), i))
    for index in remainder_order[:size-sum(quotas)]:
        quotas[index] += 1
    groups = {stratum: [] for stratum in STRATA}
    for signal in signals:
        groups[f'{signal["module"]} {signal["direction"]}'].append(signal)
    rng = random.Random(seed)
    sample, details = [], {}
    for stratum, requested in zip(STRATA, quotas):
        group = groups[stratum]
        actual = min(requested, len(group))
        chosen = rng.sample(group, actual)
        require(len(chosen) <= len(group), 0, "muestra supera disponibilidad del estrato")
        sample.extend(dict(row, review_status="PENDING", structure_quality="",
                           signal_quality="", review_notes="") for row in chosen)
        details[stratum] = {"requested": requested, "available": len(group), "selected": actual,
                            "shortfall": requested-actual}
    sample.sort(key=lambda row: row["decision_server"])
    require(len({row["decision_server"] for row in sample}) == len(sample), 0, "muestra duplicada")
    return sample, details


def write_csv(path: Path, columns: tuple, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        output.flush()
        os.fsync(output.fileno())


def audit_outputs(directory: Path, sensitive: set[str]) -> None:
    needles = tuple(token.casefold() for token in sensitive if token)

    def audit_text(text: str, line: int) -> None:
        require(not any(token in text.casefold() for token in needles), line,
                "salida sanitizada contiene un token sensible; no se publicará")

    for name in OUTPUT_NAMES:
        path = directory / name
        # Raw textual scan also covers headers, escaped values and metadata.
        with path.open(encoding="utf-8") as source:
            for line, text in enumerate(source, 1):
                audit_text(text, line)
        if name.endswith(".csv"):
            with path.open(encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                require(not any(field == "identity" or field.endswith("_key") or
                                field in {"state", "checksum", "magic"} for field in reader.fieldnames),
                        1, "columna sensible en salida")
                for row in reader:
                    for value in row.values():
                        audit_text(value, reader.line_num)
        else:
            def walk(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        audit_text(key, 0)
                        walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)
                elif isinstance(value, str):
                    audit_text(value, 0)
            walk(json.loads(path.read_text(encoding="utf-8")))


def publish_directory(stage: Path, output: Path) -> None:
    """Swap the complete result set; restore the old directory if publication fails."""
    backup = None
    if output.exists():
        backup = Path(tempfile.mkdtemp(prefix=".scanner-backup-", dir=output.parent))
        backup.rmdir()
        os.replace(output, backup)
    try:
        os.replace(stage, output)
    except OSError:
        if backup is not None:
            os.replace(backup, output)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def analyze(input_path: Path, output_dir: Path, sample_size: int = 50, seed: int = 20260917) -> dict:
    require(sample_size >= 0, 0, "sample_size debe ser >= 0")
    input_path = Path(input_path).resolve()
    output_arg = Path(output_dir)
    require(not output_arg.is_symlink(), 0, "directorio de salida no puede ser un enlace")
    output_dir = output_arg.resolve()
    require(input_path != output_dir and output_dir not in input_path.parents,
            0, "el original no puede estar dentro del destino de resultados")
    if output_dir.exists():
        require(output_dir.is_dir() and all(p.name in OUTPUT_NAMES and p.is_file() and not p.is_symlink()
                                           for p in output_dir.iterdir()),
                0, "el destino contiene archivos ajenos; use otro experimento")
    original_hash = source_sha256(input_path)
    signals, summary, sensitive = collect(input_path)
    sample, strata = stratified_sample(signals, sample_size, seed)
    summary.update({
        "analyzer_version": "1.0", "python_version": sys.version.split()[0],
        "input_filename": input_path.name, "input_sha256": original_hash,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_size": sample_size, "seed": seed, "actual_sample_size": len(sample),
        "sampling_strata": strata, "sampling_shortfall": sample_size-len(sample),
        "validations": {name: "PASS" for name in VALIDATIONS},
        "original_event_keys_audit": "Keys validated as identity + decision + channel; full identity absent from outputs.",
    })
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".scanner-stage-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        write_csv(stage / OUTPUT_NAMES[0], REDUCED_COLUMNS, signals)
        write_csv(stage / OUTPUT_NAMES[1], REDUCED_COLUMNS + REVIEW_COLUMNS, sample)
        (stage / OUTPUT_NAMES[2]).write_text(json.dumps(summary, ensure_ascii=False, indent=2,
                                                       sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        audit_outputs(stage, sensitive)
        require(source_sha256(input_path) == original_hash, 0, "el CSV original cambió durante la lectura")
        publish_directory(stage, output_dir)
    return summary


def repository_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="CSV exacto del scanner; nunca se descubre automáticamente")
    parser.add_argument("--output-dir", required=True, help="artifacts/scanner_analysis/<experimento>")
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260917)
    args = parser.parse_args(argv)
    try:
        output = repository_path(args.output_dir).resolve()
        require(output.parent == ARTIFACT_ROOT.resolve() and bool(re.fullmatch(r"[A-Za-z0-9_-]+", output.name)),
                0, "output-dir debe ser artifacts/scanner_analysis/<experimento> con nombre alfanumérico, _ o -")
        summary = analyze(repository_path(args.input), output, args.sample_size, args.seed)
    except ValidationError as error:
        print(f"Validación fallida: {error}", file=sys.stderr)
        return 2
    except OSError:
        print("Error de acceso o publicación de archivos; no se muestran rutas ni datos privados.", file=sys.stderr)
        return 3
    print(f'OK: {summary["total_rows"]} filas; {summary["unique_signal_bars"]} barras con señal; '
          f'{summary["actual_sample_size"]} en muestra; validaciones PASS.')
    if summary["sampling_shortfall"]:
        print(f'Muestra incompleta: faltan {summary["sampling_shortfall"]} barras en los estratos solicitados.')
    return 0


if __name__ == "__main__":
    # Consistent diagnostics when Windows pipes otherwise default to a legacy code page.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
