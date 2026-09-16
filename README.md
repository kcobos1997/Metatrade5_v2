# XAUUSD MT5 Project - Phase 1

## Diagnostic Expert Advisor

`XAUUSD_Practice_EA.mq5` inspects the active chart symbol (`_Symbol`) and
 timeframe (`_Period`). It contains no trading strategy and does not place,
modify, or close trades.

- Initialization logs the symbol, digits, point, tick size, tick value, contract
  size, minimum/maximum volume, volume step, stops level, and freeze level.
  Failed property reads are logged as unavailable with an error code.
- Symbols whose names do not contain `XAUUSD` produce a warning; diagnostics
  continue. Broker prefixes and suffixes are supported through `_Symbol`.
- `InpMagicNumber` is an unsigned input reserved for future use only.
- Each newly observed bar produces one line containing the bar opening time
  (broker/server time), bid, ask, and spread calculated as `(ask - bid) / _Point`.
- Deinitialization logs the numeric MT5 reason code.

The bar present at attachment is a baseline and is not logged as a new bar.
If history is initially unavailable, the first valid bar becomes that baseline.
Unavailable or invalid quotes are retried silently on later ticks. Diagnostics
require incoming ticks; missed bars during disconnection are not reconstructed.
Reattaching or changing timeframe starts a fresh baseline. Property logs are an
initialization snapshot, and tick value can depend on broker data availability.

## Manual verification

1. Open the source in MetaEditor and compile with F7. Confirm **0 errors and
   0 warnings** before attaching the EA.
2. Attach it to an XAUUSD chart in MT5, using the broker's actual symbol name.
   Confirm the reserved Magic Number input and compare the initialization logs
   in the Experts tab with the symbol's Specification (stops/freeze in points).
3. On M1 with incoming ticks, observe several bar transitions. Expect exactly
   one diagnostic line per new observed bar, no per-tick log spam, correctly
   formatted prices, and spread matching `(ask - bid) / point` for the logged quote.
4. Attach to a non-XAUUSD chart and confirm the warning and continued diagnostics.
5. Change timeframe, remove, and reattach the EA. Confirm deinitialization reason
   logs and a fresh baseline without a false new-bar message at attachment.
6. Check behavior after reconnecting or loading history: no repeated lines for
   the same bar and no invented diagnostics for missed bars.
7. Run a short Strategy Tester check with tick data. Confirm diagnostics appear
   and **zero trades/orders** are generated. No performance target applies in Phase 1.

Compilation and runtime checks must be completed in MetaEditor and MetaTrader 5;
source review alone does not establish those results.
