"""Build an offline, causal SVG review book from scanner-v1 and a review sample."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import html
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
if __package__:
    from . import analyze_scanner as scanner
else:
    import analyze_scanner as scanner

OUTPUT_NAME = "signal_review_book.html"
REVIEW_FIELDS = ("chart_quality", "signal_alignment", "context_class", "reviewer_decision", "reviewer_notes")
OPTIONS = {
    "chart_quality": ("", "CLEAR", "MIXED", "POOR"),
    "signal_alignment": ("", "ALIGNED", "UNCLEAR", "MISALIGNED"),
    "context_class": ("", "TREND", "RANGE", "TRANSITION", "UNCLEAR"),
    "reviewer_decision": ("PENDING", "VALID", "QUESTIONABLE", "REJECTED"),
}
PRICE_FIELDS = ("signal_open", "signal_high", "signal_low", "signal_close")
REASON_FIELDS = tuple(f"{lane}_reason" for lane in scanner.LANES)
REQUIRED_SAMPLE = ("signal_open_server_text", "decision_ny_text", "direction", "module",
                   "spread_points", "h1_gate", "h1_ema") + PRICE_FIELDS + REASON_FIELDS
require = scanner.require
ValidationError = scanner.ValidationError


def text_epoch(value: str, line: int) -> int:
    try:
        stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        result = int((stamp - scanner.EPOCH).total_seconds())
    except ValueError:
        raise ValidationError(line, "signal_open_server_text inválido") from None
    require(result > 0 and scanner.timestamp_text(result) == value, line, "timestamp textual no canónico")
    return result


def read_sample(path: Path) -> list[dict]:
    records = []
    seen_ids, seen_times = set(), set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames or []
        require(len(fields) == len(set(fields)) and set(REQUIRED_SAMPLE) <= set(fields),
                1, "cabecera de muestra incompleta o duplicada")
        require("sample_id" in fields or "signal_id" in fields, 1, "falta sample_id o signal_id")
        require("bar_time_epoch" in fields or "signal_open_server" in fields,
                1, "falta bar_time_epoch o signal_open_server")
        for row in reader:
            line = reader.line_num
            require(None not in row and all(value is not None for value in row.values()), line, "fila de muestra incompleta")
            record = {name: row[name] for name in REQUIRED_SAMPLE}
            record.update(sample_id=row.get("sample_id", row.get("signal_id", "")),
                          bar_time_epoch=None, bars=[], errors=[], warnings=[], review={}, sample_row=line)
            for field, options in OPTIONS.items():
                candidate = row.get(field, options[0])
                record["review"][field] = candidate if candidate in options else options[0]
            record["review"]["reviewer_notes"] = row.get("reviewer_notes", row.get("review_notes", ""))
            try:
                require(bool(record["sample_id"]) and record["sample_id"] not in seen_ids,
                        line, "sample_id vacío o duplicado")
                seen_ids.add(record["sample_id"])
                stamp = text_epoch(row["signal_open_server_text"], line)
                record["bar_time_epoch"] = stamp  # Text is the primary lookup, not the epoch alias.
                require(stamp not in seen_times, line, "barra duplicada en la muestra")
                seen_times.add(stamp)
                for alias in ("bar_time_epoch", "signal_open_server"):
                    if alias in row:
                        require(scanner.integer(row[alias], line, alias) == stamp, line, "epoch no coincide con timestamp textual")
                if "decision_server" in row:
                    require(scanner.integer(row["decision_server"], line, "decision_server") == stamp+300,
                            line, "decision_server no corresponde a la siguiente M5")
                if "decision_ny" in row:
                    require(scanner.timestamp_text(scanner.integer(row["decision_ny"], line, "decision_ny")) == row["decision_ny_text"],
                            line, "fecha NY incoherente en muestra")
                require(row["direction"] in {"BUY", "SELL"} and row["module"] in {"B0", "PB1", "B0+PB1"},
                        line, "dirección o módulo inválido")
                for field in PRICE_FIELDS + ("spread_points", "h1_ema"):
                    record[field] = scanner.finite(row[field], line, field)
                record["h1_gate"] = scanner.integer(row["h1_gate"], line, "h1_gate")
            except ValidationError as error:
                record["errors"].append(str(error))
            records.append(record)
    require(bool(records), 1, "muestra vacía")
    return records


def match_record(record: dict, raw: dict, values: dict, history: dict, conflicts: set,
                 earliest: int | None, bars_before: int) -> None:
    """Snapshot only bars observed by this decision; never repair from later rows."""
    line = record["sample_row"]
    target = record["bar_time_epoch"]
    try:
        require(scanner.timestamp_text(values["signal_open_server"]) == record["signal_open_server_text"],
                line, "no coincide la apertura textual con el original")
        require(target in history, line, "falta la barra de señal en el original")
        require(target not in conflicts, line, "OHLC contradictorios para la barra de señal")
        require(tuple(record[key] for key in PRICE_FIELDS) == history[target][1:], line, "OHLC de señal incompatibles con la muestra")
        accepted = [lane for lane in scanner.LANES if raw[f"{lane}_reason"] == "ACCEPT_DIAGNOSTIC"]
        directions = {lane.split("_")[1].upper() for lane in accepted}
        modules = {lane.split("_")[0].upper() for lane in accepted}
        require(len(directions) == 1 and record["direction"] in directions, line, "dirección distinta del original")
        require(record["module"] == "+".join(m for m in ("B0", "PB1") if m in modules), line, "módulo distinto del original")
        require(raw["session"] == "IN" and raw["data_status"] == "OK" and
                all(values[f"{lane}_raw"] == 1 for lane in accepted), line, "señal original no válida para revisión")
        require(values["h1_gate"] == (1 if record["direction"] == "BUY" else -1), line, "permiso H1 incompatible")
        for field in ("h1_gate", "h1_ema", "spread_points"):
            require(record[field] == values[field], line, f"{field} distinto del original")
        require(record["decision_ny_text"] == scanner.timestamp_text(values["decision_ny"]), line, "hora NY distinta del original")
        require(all(record[key] == raw[key] for key in REASON_FIELDS), line, "reason codes distintos del original")
        expected = list(range(target-bars_before*300, target+1, 300))
        missing = [stamp for stamp in expected if stamp not in history]
        internal = [stamp for stamp in missing if earliest is not None and stamp >= earliest]
        require(not internal, line, f"falta una barra histórica M5 ({len(internal)} huecos); gráfico bloqueado")
        require(not any(stamp in conflicts for stamp in expected), line, "OHLC históricos contradictorios; gráfico bloqueado")
        if missing:
            record["warnings"].append(f"Historial insuficiente al inicio: {bars_before-len(missing)}/{bars_before} barras anteriores; no se inventan velas.")
        record["bars"] = [list(history[stamp]) for stamp in expected if stamp in history]
        require(record["bars"][-1][0] == target and sum(bar[0] == target for bar in record["bars"]) == 1,
                line, "barra de señal ausente o repetida")
        require(all(bar[0] <= target for bar in record["bars"]), line, "barra futura bloqueada")
    except ValidationError as error:
        record["bars"] = []
        record["errors"].append(str(error))


def build_records(input_path: Path, sample_path: Path, bars_before: int = 30) -> tuple[list[dict], set[str]]:
    require(0 <= bars_before <= 1000, 0, "bars-before debe estar entre 0 y 1000")
    csv.field_size_limit(16*1024*1024)
    records = read_sample(sample_path)
    wanted = defaultdict(list)
    for record in records:
        if not record["errors"]:
            wanted[record["bar_time_epoch"]+300].append(record)
    last_needed = max(wanted, default=0)
    history, conflicts = {}, set()
    earliest = None
    identity = None
    sensitive = set()
    previous = 0
    with input_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        header = reader.fieldnames or []
        require(len(header) == 39 and set(header) == set(scanner.COLUMNS), 1, "cabecera original incompatible")
        for raw in reader:
            line = reader.line_num
            require(None not in raw and all(v is not None for v in raw.values()), line, "fila original incompleta")
            if identity is None:
                identity = raw["identity"]
                sensitive, *_ = scanner.identity_metadata(identity, line)
            require(identity == raw["identity"], line, "más de una identidad en el original")
            # Never ingest a later decision even if it contains an old overlapping window.
            decision = scanner.integer(raw["decision_server"], line, "decision_server")
            if decision > last_needed:
                break
            values = scanner.typed_row(raw, line)
            require(decision > previous, line, "decisiones originales duplicadas o fuera de orden")
            previous = decision
            cutoff = decision-(bars_before+1)*300
            history = {stamp: bar for stamp, bar in history.items() if stamp >= cutoff}
            conflicts = {stamp for stamp in conflicts if stamp >= cutoff}
            try:
                window = scanner.parse_m5_window(raw["m5_window"], values["signal_open_server"], line)
            except ValidationError:
                # Data-error rows may carry an unavailable/partial window. No synthetic fill.
                window = []
            for bar in window:
                stamp = bar[0]
                require(stamp+300 <= decision, line, "ventana original contiene barra todavía abierta")
                earliest = stamp if earliest is None else min(earliest, stamp)
                if stamp < cutoff:
                    continue
                if stamp in history and history[stamp] != bar:
                    conflicts.add(stamp)
                else:
                    history[stamp] = bar
            for record in wanted.pop(decision, []):
                match_record(record, raw, values, history, conflicts, earliest, bars_before)
    require(identity is not None, 1, "original vacío")
    for pending in wanted.values():
        for record in pending:
            record["errors"].append(f'Fila {record["sample_row"]}: falta la decisión/barra de señal en el original')
    for record in records:
        record["status"] = "ERROR" if record["errors"] else ("INCOMPLETE" if record["warnings"] else "OK")
    return records, sensitive


def escape(value) -> str:
    return html.escape(str(value), quote=True)


def chart_svg(record: dict, bars_before: int) -> str:
    bars = record["bars"]
    if not bars:
        return '<div class="blocked">Gráfico bloqueado: revisar los errores de esta ficha.</div>'
    width, height, left, top, plot_w, plot_h = 1120, 410, 24, 24, 980, 318
    low, high = min(b[3] for b in bars), max(b[2] for b in bars)
    pad = max((high-low)*0.08, abs(high)*0.00001, 0.000001)
    low -= pad
    high += pad
    def y(price):
        return top + (high-price)/(high-low)*plot_h
    step = plot_w/(bars_before+1)
    start = record["bar_time_epoch"]-bars_before*300
    signal_x = left+bars_before*step
    svg = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Velas M5 hasta la señal" class="chart">',
           '<title>Velas cerradas M5: verde alcista hueca; roja bajista rellena; franja azul de señal.</title>',
           f'<rect class="signal-band" x="{signal_x:.3f}" y="{top}" width="{step:.3f}" height="{plot_h}"/>']
    for i in range(6):
        price = low+(high-low)*i/5
        pos = y(price)
        svg.append(f'<line class="grid" x1="{left}" x2="{left+plot_w}" y1="{pos:.3f}" y2="{pos:.3f}"/>'
                   f'<text class="axis" x="{left+plot_w+12}" y="{pos+4:.3f}">{price:.3f}</text>')
    for index, (stamp, opening, maximum, minimum, close) in enumerate(bars):
        slot = (stamp-start)//300
        cx = left+(slot+0.5)*step
        body_top, body_bottom = sorted((y(opening), y(close)))
        body_width = min(18, step*0.62)
        cls = "up" if close >= opening else "down"
        marked = " signal" if stamp == record["bar_time_epoch"] else ""
        label = scanner.timestamp_text(stamp)
        svg.append(f'<g class="candle {cls}{marked}" data-bar-time="{stamp}"><title>{label} | '
                   f'O {opening} H {maximum} L {minimum} C {close}</title>'
                   f'<line class="wick" x1="{cx:.3f}" x2="{cx:.3f}" y1="{y(maximum):.3f}" y2="{y(minimum):.3f}"/>')
        if opening == close:
            svg.append(f'<line class="body" x1="{cx-body_width/2:.3f}" x2="{cx+body_width/2:.3f}" y1="{body_top:.3f}" y2="{body_top:.3f}"/>')
        else:
            svg.append(f'<rect class="body" x="{cx-body_width/2:.3f}" y="{body_top:.3f}" width="{body_width:.3f}" height="{body_bottom-body_top:.3f}"/>')
        svg.append('</g>')
        if index == 0 or index == len(bars)-1 or slot % max(1, (bars_before+1)//6) == 0:
            svg.append(f'<text class="axis" text-anchor="middle" x="{cx:.3f}" y="365">{label[11:16]}</text>')
    svg.append(f'<text class="axis" x="24" y="397">Hora del servidor · {len(bars)-1} barras anteriores + 1 señal · sin barras posteriores</text></svg>')
    return "".join(svg)


EXPORT_JS = r'''
const annotationColumns = ["sample_id","signal_open_server_text","bar_time_epoch","decision_ny_text",
  "direction","module","status","validation_errors","chart_quality","signal_alignment","context_class","reviewer_decision","reviewer_notes","completed"];
function csvCell(value) {
  let text = String(value ?? "");
  // Protect spreadsheet users from formulas in editable text; numbers remain numeric.
  if (typeof value === "string" && /^[\s]*[=+\-@]/u.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}
function buildAnnotationCsv(records, annotations) {
  const lines = [annotationColumns.map(csvCell).join(",")];
  records.forEach((record, index) => {
    const row = {...record, ...annotations[index], validation_errors: record.errors.join("; ")};
    lines.push(annotationColumns.map(column => csvCell(row[column])).join(","));
  });
  return "\uFEFF" + lines.join("\r\n") + "\r\n";
}
'''
UI_JS = r'''
const records = JSON.parse(document.getElementById("review-data").textContent);
const config = JSON.parse(document.getElementById("review-config").textContent);
const cards = Array.from(document.querySelectorAll(".signal-card"));
const filter = document.getElementById("filter"), picker = document.getElementById("picker");
const saveButton = document.getElementById("save-next");
let visible = [], selected = 0, storageOK = true, storedSnapshot = null, unsaved = false;
let annotations = records.map(record => ({...record.review, completed:false}));
function ready(entry) {
  return Object.entries(config.options).every(([field, choices]) => choices.includes(entry[field])) &&
    !!entry.chart_quality && !!entry.signal_alignment && !!entry.context_class &&
    entry.reviewer_decision !== "PENDING" && typeof entry.reviewer_notes === "string" &&
    entry.reviewer_notes.trim().length >= 3;
}
function storageFailure(message) {
  storageOK = false;
  document.getElementById("storage-status").textContent = message;
  document.getElementById("storage-status").className = "error";
  saveButton.disabled = true;
}
try {
  storedSnapshot = localStorage.getItem(config.storageKey);
  if(storedSnapshot !== null) {
    const saved = JSON.parse(storedSnapshot);
    if(saved.version !== 1 || !Array.isArray(saved.annotations) || saved.annotations.length !== records.length)
      throw new Error("Formato incompatible");
    const restored = saved.annotations.map(entry => {
      if(!entry || typeof entry.completed !== "boolean" || typeof entry.reviewer_notes !== "string" ||
         !Object.entries(config.options).every(([field, choices]) => choices.includes(entry[field])) ||
         (entry.completed && !ready(entry))) throw new Error("Anotaciones incompatibles");
      return Object.fromEntries([...Object.keys(config.options), "reviewer_notes", "completed"].map(field => [field, entry[field]]));
    });
    annotations = restored;
  }
} catch(error) {
  storageFailure("No se pudo restaurar el progreso local. No se sobrescribirá. Conserva una copia y revisa el almacenamiento del navegador.");
}
function persist() {
  if(!storageOK) return false;
  try {
    // A stale tab must never overwrite progress saved by another tab.
    if(localStorage.getItem(config.storageKey) !== storedSnapshot) {
      storageFailure("El progreso cambió en otra pestaña. Descarga tus borradores y recarga para recuperar la versión guardada.");
      return false;
    }
    const next = JSON.stringify({version:1, annotations});
    localStorage.setItem(config.storageKey, next);
    storedSnapshot = next;
    unsaved = false;
    document.getElementById("storage-status").textContent = "Guardado local automático · mismo archivo y perfil de Edge";
    return true;
  } catch(error) {
    storageFailure("No se pudo guardar en localStorage. Descarga el CSV antes de cerrar; Guardar y siguiente está bloqueado.");
    return false;
  }
}
function collectAnnotations() { return annotations.map(entry => ({...entry})); }
function refreshCard(index) {
  const entry = annotations[index], card = cards[index];
  card.querySelectorAll("button[data-field]").forEach(button => {
    button.setAttribute("aria-pressed", String(entry[button.dataset.field] === button.dataset.value));
    button.disabled = entry.completed;
  });
  const notes = card.querySelector("textarea");
  notes.value = entry.reviewer_notes;
  notes.readOnly = entry.completed;
  card.querySelector(".completion-state").textContent = entry.completed ? "COMPLETADA · solo lectura" : "PENDIENTE";
}
function updateProgress() {
  const count = annotations.filter(entry => entry.completed).length;
  const index = visible[selected];
  document.getElementById("completed-count").textContent = `Completadas ${count}/${records.length}`;
  document.getElementById("pending-count").textContent = `Pendientes ${records.length-count}`;
  document.getElementById("current-count").textContent = `Actual ${index === undefined ? 0 : index+1}/${records.length}`;
  document.getElementById("current-id").textContent = `sample_id: ${index === undefined ? "—" : records[index].sample_id}`;
  saveButton.disabled = index === undefined || !storageOK || annotations[index].completed || !ready(annotations[index]);
  document.getElementById("first-pending").disabled = count === records.length;
  document.getElementById("save-help").textContent = index !== undefined && annotations[index].completed ?
    "Ficha completada protegida. Usa Ir a primera pendiente para continuar." :
    "Elige las cuatro clasificaciones (decisión distinta de PENDING) y escribe una nota de al menos 3 caracteres.";
}
function showSelected() {
  cards.forEach(card => { card.hidden = true; });
  if (visible.length) cards[visible[selected]].hidden = false;
  picker.value = String(selected);
  document.getElementById("position").textContent = visible.length ? `${selected+1} / ${visible.length} visibles` : "0 visibles";
  document.getElementById("empty").hidden = visible.length !== 0;
  document.getElementById("prev").disabled = selected === 0 || !visible.length;
  document.getElementById("next").disabled = selected >= visible.length-1;
  updateProgress();
}
function applyFilter(target) {
  visible = records.map((record, index) => ({record,index})).filter(({record}) =>
    filter.value === "ALL" || record.direction === filter.value || record.module === filter.value).map(x => x.index);
  picker.replaceChildren();
  visible.forEach((index, position) => {
    const option = document.createElement("option");
    option.value = String(position);
    option.textContent = `${records[index].sample_id} · ${records[index].signal_open_server_text} · ${records[index].module} ${records[index].direction}`;
    picker.appendChild(option);
  });
  selected = Math.max(0, visible.indexOf(target));
  showSelected();
}
function goPending(after = -1) {
  let next = annotations.findIndex((entry, index) => index > after && !entry.completed);
  if(next < 0) next = annotations.findIndex(entry => !entry.completed);
  // Pending navigation covers the entire sample, regardless of a visual filter.
  filter.value = "ALL";
  applyFilter(next < 0 ? Math.max(0, after) : next);
  return next;
}
filter.addEventListener("change", () => applyFilter());
picker.addEventListener("change", () => { selected = Number(picker.value); showSelected(); });
document.getElementById("prev").addEventListener("click", () => { if(selected>0) selected--; showSelected(); });
document.getElementById("next").addEventListener("click", () => { if(selected+1<visible.length) selected++; showSelected(); });
document.getElementById("first-pending").addEventListener("click", () => goPending());
cards.forEach((card, index) => {
  card.querySelectorAll("button[data-field]").forEach(button => button.addEventListener("click", () => {
    if(annotations[index].completed) return;
    annotations[index][button.dataset.field] = button.dataset.value;
    unsaved = true;
    persist(); refreshCard(index); updateProgress();
  }));
  card.querySelector("textarea").addEventListener("input", event => {
    if(annotations[index].completed) return;
    annotations[index].reviewer_notes = event.target.value;
    unsaved = true;
    persist(); updateProgress();
  });
  refreshCard(index);
});
saveButton.addEventListener("click", () => {
  const index = visible[selected];
  if(index === undefined || !storageOK || annotations[index].completed || !ready(annotations[index])) return;
  annotations[index].completed = true;
  unsaved = true;
  if(!persist()) { annotations[index].completed = false; updateProgress(); return; }
  refreshCard(index);
  const next = goPending(index);
  document.getElementById("confirmation").textContent = `Guardada ${records[index].sample_id}.` +
    (next < 0 ? " Todas las fichas están completadas. Descarga el CSV." : ` Siguiente pendiente: ${records[next].sample_id}.`);
});
document.getElementById("download").addEventListener("click", () => {
  const content = buildAnnotationCsv(records, collectAnnotations());
  const url = URL.createObjectURL(new Blob([content], {type:"text/csv;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "signal_review_annotations_" + new Date().toISOString().replace(/[:.]/g,"-") + ".csv";
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.getElementById("save-state").textContent = `Descarga solicitada: ${records.length} fichas. Comprueba el archivo descargado.`;
});
window.addEventListener("beforeunload", event => { if(unsaved) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("storage", event => {
  if((event.key === config.storageKey || event.key === null) && event.newValue !== storedSnapshot)
    storageFailure("El progreso cambió en otra pestaña. Recarga antes de continuar; no se sobrescribirá.");
});
window.reviewBook = {records, buildAnnotationCsv, collectAnnotations, storageKey:config.storageKey};
if(storageOK) persist();
goPending();
document.getElementById("runtime-status").textContent = "Listo · funciona sin conexión";
'''
CSS = '''
:root{font-family:Segoe UI,Arial,sans-serif;color:#e4edf7;background:#0c1524;color-scheme:dark}
*{box-sizing:border-box}body{margin:0}main{max-width:1240px;margin:auto;padding:24px}
h1{margin:0 0 8px;font-size:28px}p{line-height:1.5}.muted,.axis{color:#a8b9cd;fill:#a8b9cd}
.toolbar{position:sticky;top:0;background:#142238;z-index:2;padding:14px;border:1px solid #32445e;border-radius:10px;display:flex;gap:12px;align-items:end;flex-wrap:wrap}
label{display:flex;flex-direction:column;gap:5px;font-size:13px}select,button,textarea{font:inherit;padding:9px;border:1px solid #526984;border-radius:6px;background:#0d1a2c;color:#edf5ff}
button{cursor:pointer}button:disabled{opacity:.4;cursor:default}button:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #78b7ff}
#picker{max-width:480px}#download{background:#235ba0}#position{min-width:60px;padding:10px}
.signal-card{margin-top:20px;border:1px solid #32445e;border-radius:12px;background:#111e31;padding:20px}[hidden]{display:none!important}
.card-title{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.badge{padding:5px 9px;background:#20354f;border-radius:5px}.BUY{color:#71e8c2}.SELL{color:#ffa3a3}
.metadata{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:18px 0}dt{font-size:12px;color:#a8b9cd}dd{margin:4px 0;overflow-wrap:anywhere}
.chart-wrap{overflow-x:auto}.chart{display:block;width:100%;min-width:720px}.grid{stroke:#263951;stroke-width:1}.axis{font-size:12px}
.signal-band{fill:#2a568a;fill-opacity:.38;stroke:#79b9ff;stroke-width:1.5}.wick,.body{stroke-width:1.6}.up .wick,.up .body{stroke:#64dfb5}.up .body{fill:#111e31}.down .wick,.down .body{stroke:#ff929a}.down .body{fill:#ff929a}
.error,.warning,.blocked{padding:12px;border-radius:6px;margin:12px 0}.error,.blocked{background:#4b2330;border:1px solid #ff929a}.warning{background:#43391f;border:1px solid #e5bd60}
.reasons{font-size:12px;line-height:1.8;overflow-wrap:anywhere}.review-grid{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:12px;margin-top:18px}.notes{grid-column:1/-1}textarea{width:100%;min-height:85px;resize:vertical}
@media(max-width:700px){main{padding:12px}.signal-card{padding:12px}.review-grid{grid-template-columns:1fr 1fr}#picker{max-width:310px}}
main{max-width:1880px;padding:12px 20px}h1{font-size:23px;margin:0}p{margin:5px 0;font-size:13px}
.sticky-header{position:sticky;top:0;z-index:3;background:#0c1524;padding:6px 0}
.progress{display:flex;gap:28px;flex-wrap:wrap;font-size:20px;padding:8px 12px;background:#20354f;border-radius:8px}
.toolbar{position:static;padding:8px;gap:10px;margin-top:6px}.toolbar button{min-height:46px;font-size:15px}
#confirmation{min-height:24px;color:#8bf0c8;font-weight:600;font-size:16px}#runtime-status{display:inline-block}
.signal-card{margin-top:8px;padding:12px}.card-title h2{font-size:19px;margin:2px 0}.completion-state{margin-left:auto;color:#8bf0c8;font-size:15px}
.workspace{display:grid;grid-template-columns:minmax(0,1fr) 560px;gap:20px}.market{min-width:0}
.metadata{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0}.metadata dd{font-size:14px}
.chart{min-width:640px}.review-grid{display:flex;flex-direction:column;gap:8px;margin-top:8px}
fieldset{margin:0;padding:6px 8px 10px;border:1px solid #536881;border-radius:8px;min-width:0}
legend{font-size:15px;font-weight:700;padding:0 5px}.choices{display:flex;gap:6px;flex-wrap:wrap}
.choices button{min-height:48px;padding:9px 10px;font-size:15px;font-weight:600;border:2px solid #536881;flex:1 0 auto}
.selected-mark{display:none}.choices button[aria-pressed="true"]{background:#17694e;border:3px solid #8bf0c8;color:white;box-shadow:0 0 0 1px #8bf0c8}
.choices button[aria-pressed="true"] .selected-mark{display:inline}.choices button:disabled{opacity:.8;cursor:default}
.notes{font-size:15px;font-weight:600}.notes textarea{min-height:72px;font-size:16px}textarea:read-only{background:#20354f}
.save-footer{position:sticky;bottom:0;background:#142238;padding:10px;display:flex;align-items:center;gap:16px;border-radius:8px;margin-top:8px}
#save-next{min-height:54px;min-width:290px;font-size:21px;font-weight:700;background:#17694e;border:2px solid #8bf0c8}
#save-next:disabled{background:#263951;border-color:#536881;opacity:.65}#save-help{font-size:14px}
@media(max-width:1200px){.workspace{grid-template-columns:1fr}.review-grid{display:grid;grid-template-columns:1fr 1fr}.progress{font-size:17px;gap:12px}}
@media(max-width:700px){main{padding:8px}.review-grid{display:flex}.save-footer{flex-wrap:wrap}.chart{min-width:640px}}
'''


def render_card(record: dict, index: int, bars_before: int) -> str:
    def field(label, value):
        return f'<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
    messages = "".join(f'<div class="error" role="alert">{escape(message)}</div>' for message in record["errors"])
    messages += "".join(f'<div class="warning">{escape(message)}</div>' for message in record["warnings"])
    metadata = field("Servidor · apertura de señal", record["signal_open_server_text"])
    metadata += field("Nueva York · decisión", record["decision_ny_text"])
    metadata += field("OHLC · muestra", " / ".join(str(record[key]) for key in PRICE_FIELDS))
    metadata += field("Spread · puntos", record["spread_points"])
    metadata += field("H1 gate", record["h1_gate"]) + field("EMA H1 · cierre disponible", record["h1_ema"])
    reasons = " · ".join(f'{lane}: {record[f"{lane}_reason"]}' for lane in scanner.LANES)
    controls = []
    for name, options in OPTIONS.items():
        buttons = "".join(
            f'<button type="button" data-field="{name}" data-value="{escape(value)}" '
            f'data-testid="review-{index}-{name}-{value or "EMPTY"}" '
            f'aria-label="{name}: {escape(value or "Sin clasificar")}" '
            f'aria-pressed="{str(value == record["review"][name]).lower()}">'
            f'<span class="selected-mark" aria-hidden="true">✓ </span>{escape(value or "Sin clasificar")}</button>'
            for value in options)
        controls.append(f'<fieldset><legend>{name}</legend><div class="choices">{buttons}</div></fieldset>')
    controls.append(f'<label class="notes">reviewer_notes<textarea data-testid="review-{index}-reviewer_notes" data-field="reviewer_notes">{escape(record["review"]["reviewer_notes"])}</textarea></label>')
    return (f'<article class="signal-card" data-index="{index}" data-signal-time="{record["bar_time_epoch"]}" hidden>'
            f'<div class="card-title"><h2>sample_id: {escape(record["sample_id"])}</h2>'
            f'<span class="badge">{escape(record["module"])}</span><strong class="{escape(record["direction"])}">{escape(record["direction"])}</strong>'
            f'<span class="badge">{record["status"]}</span><strong class="completion-state">PENDIENTE</strong></div>{messages}'
            f'<div class="workspace"><section class="market"><dl class="metadata">{metadata}</dl>'
            f'<div class="chart-wrap">{chart_svg(record, bars_before)}</div><p class="reasons">{escape(reasons)}</p>'
            f'</section><section class="review-grid" aria-label="Clasificación de la señal">{"".join(controls)}</section></div></article>')


def render_html(records: list[dict], bars_before: int) -> str:
    payload = json.dumps(records, ensure_ascii=False, allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    # Stable across regeneration/UI changes; isolate different market/sample datasets.
    identity = [{k: v for k, v in record.items() if k not in {"review", "sample_row"}} for record in records]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True,
                                       allow_nan=False).encode("utf-8")).hexdigest()
    config = json.dumps({"storageKey": "xau-signal-review:v1:" + digest, "options": OPTIONS})
    errors = sum(bool(record["errors"]) for record in records)
    incomplete = sum(bool(record["warnings"]) for record in records)
    cards = "".join(render_card(record, i, bars_before) for i, record in enumerate(records))
    filters = "".join(f'<option value="{value}">{label}</option>' for value, label in
                      (("ALL", "Todas"), ("BUY", "BUY"), ("SELL", "SELL"), ("B0", "B0 exclusivo"), ("PB1", "PB1 exclusivo"), ("B0+PB1", "B0+PB1")))
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; base-uri \'none\'; form-action \'none\'">'
            f'<title>XAUUSD · revisión de señales</title><style>{CSS}</style></head><body><main>'
            '<h1>XAUUSD · cuaderno de revisión</h1><p class="muted">Contexto M5 cerrado hasta la señal. '
            'Verde hueca: alcista; roja rellena: bajista; franja azul: señal. Sin evaluación de rentabilidad.</p>'
            f'<p>{len(records)} fichas · {errors} con errores · {incomplete} con historial insuficiente · {bars_before} barras anteriores solicitadas</p>'
            '<p id="runtime-status" role="status">Cargando controles…</p><noscript>Activa JavaScript para navegar y exportar las anotaciones.</noscript>'
            f'<div class="sticky-header"><div class="progress" aria-live="polite"><strong id="completed-count"></strong><strong id="pending-count"></strong><strong id="current-count"></strong><strong id="current-id"></strong></div><nav class="toolbar" aria-label="Navegación de señales"><label>Filtro<select id="filter">{filters}</select></label>'
            '<label>Señal<select id="picker"></select></label><button id="prev" type="button">Anterior</button>'
            '<span id="position" aria-live="polite"></span><button id="next" type="button">Siguiente</button>'
            '<button id="first-pending" data-testid="first-pending" type="button">Ir a primera pendiente</button><button id="download" data-testid="download-csv" type="button">Descargar anotaciones CSV</button></nav><p id="confirmation" role="status">Completa una ficha para guardar y avanzar.</p></div>'
            '<p id="storage-status" role="status">Restaurando progreso local…</p><p id="save-state" class="muted">El CSV incluye todas las fichas, incluso con filtro.</p>'
            f'<p id="empty" hidden>No hay señales para este filtro.</p>{cards}'
            '<footer class="save-footer"><button id="save-next" data-testid="save-next" type="button" aria-describedby="save-help" disabled>Guardar y siguiente</button><span id="save-help"></span></footer>'
            f'<script type="application/json" id="review-data">{payload}</script>'
            f'<script type="application/json" id="review-config">{config}</script><script>{EXPORT_JS}\n{UI_JS}</script>'
            '</main></body></html>')


def generate(input_path: Path, sample_path: Path, output_dir: Path, bars_before: int = 30) -> tuple[Path, list[dict]]:
    input_path, sample_path = Path(input_path).resolve(), Path(sample_path).resolve()
    output_dir = Path(output_dir).resolve()
    target = output_dir / OUTPUT_NAME
    require(target.resolve() not in {input_path, sample_path} and not target.is_symlink(), 0, "el destino no puede reemplazar una entrada")
    original_hashes = [scanner.source_sha256(path) for path in (input_path, sample_path)]
    records, sensitive = build_records(input_path, sample_path, bars_before)
    document = render_html(records, bars_before)
    # Check both decoded data and the HTML; no original identity/key is embedded.
    audit = (json.dumps(records, ensure_ascii=False)+document).casefold()
    require(not any(token.casefold() in audit for token in sensitive if token), 0, "el HTML contendría un token sensible")
    require(original_hashes == [scanner.source_sha256(path) for path in (input_path, sample_path)],
            0, "una entrada cambió durante la lectura")
    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".signal-review-", suffix=".html", dir=output_dir)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bars-before", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        target, records = generate(scanner.repository_path(args.input), scanner.repository_path(args.sample),
                                   scanner.repository_path(args.output_dir), args.bars_before)
    except (ValidationError, csv.Error, UnicodeError) as error:
        message = str(error) if isinstance(error, ValidationError) else "CSV o codificación inválidos"
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    except OSError:
        print("ERROR: no se pudo leer una entrada o escribir el HTML.", file=sys.stderr)
        return 3
    errors = sum(bool(record["errors"]) for record in records)
    warnings = sum(bool(record["warnings"]) for record in records)
    print(f"{OUTPUT_NAME}: {len(records)} fichas; {errors} con errores; {warnings} con historial insuficiente.")
    return 2 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
