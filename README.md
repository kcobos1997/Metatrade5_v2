# XAUUSD MT5 Project

## Phase 2/3 - Strategy V1 implementation in progress

Phase 1 diagnostic validation is complete (user-validated). The source now
implements an experimental M15 session-range breakout baseline. **Demo and
backtest only; no profitability claim.** Strategy V1 runtime validation remains
pending; compilation alone is not strategy validation.

The authoritative rules, defaults, state persistence, timing edge cases, and
expected log events are in [docs/STRATEGY.md](docs/STRATEGY.md).

- Use the chart's broker-specific XAUUSD symbol; all calculations use M15 even
  on another chart timeframe. Non-XAUUSD and non-M15 strategy inputs are rejected.
- Freeze the complete 00:00-06:00 server-time range. Evaluate closed M15 candles
  from 06:00-06:15 through 11:45-12:00; never enter after 12:00:00.
- First close outside the range consumes the one daily opportunity, including
  filtered/rejected/failed entries. No later retry that day.
- Defaults: 0.5% balance risk, 1:1 quoted reward/risk, maximum spread 30 points,
  opposite-range SL, and forced exit at/after 20:00. Volume always rounds down.
- Dedicated Magic Number `1997001`; hedging positions are managed by ticket and
  symbol/Magic ownership. Real-account execution is rejected outside the tester.
- Initialization, new-bar diagnostics, state/range changes, trade results, and
  deinitialization are logged. No per-tick log spam or post-entry SL/TP changes.

Market fills can differ from requested quotes. See the specification's explicit
execution assumption: exact fill-based risk/R cannot be guaranteed with fixed
SL/TP submitted before a market fill. Gaps, costs, and slippage can exceed the
nominal budget.

## Build and validation

Compiler check (2026-09-16): MetaEditor compiled an identical temporary copy:
`Result: 0 errors, 0 warnings, 1191 ms elapsed, cpu='X64 Regular'`.
The tracked Phase 1 EX5 was verified unchanged. No Strategy Tester runtime
validation was performed in this implementation pass.

The tracked `XAUUSD_Practice_EA.ex5` is the **legacy Phase 1 binary**, not the
current Strategy V1 source. Do not run that binary to validate V1 or commit new
compiled binaries. Compile a temporary copy of the source with access to MT5's
standard `MQL5/Include` directory for validation. For manual MT5 testing, compile
the current source in MetaEditor; this updates the local EX5, which must remain
uncommitted. No external libraries are required; the EA uses standard CTrade.

1. In MetaEditor open `XAUUSD_Practice_EA.mq5`, press F7, and record the exact
   errors/warnings. Require 0 errors and 0 warnings.
2. In MT5 Strategy Tester choose this freshly compiled EA, a broker XAUUSD
   symbol, M15, a hedging demo configuration, and **Every tick based on real
   ticks** where available. Use a short date range with complete M15 history;
   then repeat on an H1 chart/test period to confirm the strategy still uses M15.
3. Verify exactly 24 range bars at defaults, no 06:00 candle in the range,
   range immutability, strict closed-candle breakouts, and no entries before
   06:15 or after 12:00:00. Test equality and wick-only cases.
4. Check first-breakout spread rejection above 30 points and absence of a second
   opportunity; repeat for disabled trading, invalid/minimum volume, rejected
   orders, and existing owned positions. Confirm no volume rounded upward.
5. Compare logged balance risk and OrderCalcProfit losses to the symbol's
   contract/tick/volume specifications. Test a safe volume below broker minimum,
   a cap at maximum, nontrivial tick size/volume step, and invalid stops/margin.
6. Validate BUY and SELL SL/TP and fill/slippage logs. Confirm no SL/TP changes.
7. Verify owned-ticket closure at/after 20:00, retry after rejection, first-tick
   closure when no 20:00 tick exists, and overdue closure after a midnight gap.
   On demo, leave unrelated manual/different-Magic positions open and confirm
   they are untouched. Use a dedicated Magic and one terminal instance.
8. On demo restart/reattach/change chart timeframe after a successful entry,
   after a spread rejection, and after an order failure. Confirm persisted range
   and opportunity prevent duplicates. Changing the frozen schedule blocks
   entries that day. A second same-namespace chart instance must be rejected.
9. Test missing range/signal history, reconnects, skipped bars, server-date
   changes/weekends, and a first 12:00 bar tick at 12:00:01 (no entry).
10. Repeat identical tester runs and optimization passes; no state may leak
    between runs or from demo terminal globals. Reject invalid inputs,
    non-XAUUSD symbols, non-M15 strategy inputs, and netting accounts.

Collect logs and tester reports before declaring Strategy V1 validated.
`docs/BACKTEST_PROTOCOL.md` is currently an empty placeholder.
