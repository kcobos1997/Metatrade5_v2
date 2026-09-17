# Strategy V1: XAUUSD M15 session-range breakout

## Status and hypothesis

Phase 1 diagnostics were validated by the user. Phase 2/3 implements an
experimental baseline; compilation and runtime validation are separate gates.
Use demo accounts and the Strategy Tester only. No profitability is claimed.

Hypothesis: a completed M15 close outside the early server-session range may
continue far enough to reach a fixed reward-to-risk target before the time exit.
This hypothesis must be tested, including spread, commission, slippage, and gaps.

## Parameters and defaults

| Input | Default | Constraint |
| --- | --- | --- |
| InpMagicNumber | 1997001 | Positive, at most LONG_MAX; unique to this EA |
| InpStrategyTimeframe | PERIOD_M15 | Only M15 accepted in V1 |
| InpRangeStartHour | 0 | Integer hour 0..23 |
| InpRangeEndHour | 6 | Start < end |
| InpEntryEndHour | 12 | Range end < entry end |
| InpForcedExitHour | 20 | Entry end <= exit; at most 23 |
| InpRiskPercent | 0.5 | Finite, > 0 and <= 100 |
| InpRewardRiskRatio | 1.0 | Finite and > 0 |
| InpMaxSpreadPoints | 30 | Finite and >= 0; zero permits only zero spread |
| InpTradeComment | XAUUSD Range V1 | Nonempty, at most 31 characters |

Use the chart's `_Symbol`, including broker prefixes/suffixes. Reject names
without the case-sensitive substring `XAUUSD`. Reject non-hedging accounts and
real accounts outside the tester. Calculations always use M15, independently of
the chart timeframe. All times are broker-server calendar times from ticks /
TimeCurrent, never the Windows clock or UTC. Hours do not span midnight.

## Daily range and timing

- At the first tick of a new server date, reset daily in-memory state and restore
  that day's persisted state and owned trade history, if any.
- After 06:00, load the exact M15 sequence in [00:00, 06:00): 24 completed bars
  at defaults. Verify every expected timestamp, valid OHLC, and High > Low for
  the aggregate. Missing, duplicated, or malformed data cannot authorize entry.
- Range High/Low are the maximum high/minimum low. Freeze once complete, then
  never recompute that date's frozen values. Delayed history can be retried at
  later new bars; past breakout signals then consume the opportunity without a
  late trade. An invalid/unavailable range produces no trade.
- Evaluate once on each observed new M15 bar. Use completed candles only.
  The first signal candle is 06:00-06:15; the last is 11:45-12:00.
- A long requires close > Range High; a short requires close < Range Low.
  Equality, a wick, and an intrabar tick outside the range do not qualify.
- Entry uses a market order on the first observed tick of the next M15 bar.
  At 12:00 the server tick timestamp must be <= 12:00:00. A first tick stamped
  12:00:01 is too late. No signals or entries are evaluated after the cutoff.
  If entry-end equals forced-exit hour, a signal at that shared boundary is
  consumed but skipped: no position is opened once the exit time is reached.
- Attaching/reinitializing establishes the current bar as a baseline; it never
  submits an immediate catch-up entry. Closed signal history is scanned in
  chronological order at later new bars to identify the first breakout. An
  earlier missed breakout consumes the opportunity without a late order.
- History must include all expected completed signal candles from range end
  through the current evaluation boundary. No entry on partial history.

## One opportunity and ownership

The first qualifying breakout consumes the daily opportunity BEFORE any filters
or order request. It stays consumed for spread rejection, invalid quotes,
invalid prices/stops, invalid risk/volume, insufficient margin, unavailable
trading, an existing owned position, broker rejection, submission failure,
partial fill, or subsequent win/loss. Never retry an entry that day.

Positions and entry deals are owned only if BOTH symbol and Magic match.
Iterate hedging positions by ticket. Never close by symbol and never modify or
close manual trades or another EA's positions. Use a dedicated Magic Number;
another EA deliberately sharing it cannot be distinguished. One owned open
position blocks a new entry. Existing owned positions from an earlier day are
also blockers until closed.

## Risk, stops, volume, and target

- Budget = current account balance * risk percentage / 100 in account currency.
- The executable quote is Ask for buys and Bid for sells; no candle-close price
  is substituted for the entry quote. SL is the opposite frozen range boundary.
- Normalize prices to SYMBOL_TRADE_TICK_SIZE. Align SL outward (buy: down;
  sell: up). Normally recorded candle prices already lie on the tick grid.
- Compute TP from that quote and normalized SL at the requested reward/risk;
  align TP outward to the tick grid. Check SL/TP directions and broker stop
  distances against the current quote. Do not widen stops to pass the filter.
- OrderCalcProfit for 1 lot estimates loss from quoted entry to normalized SL.
  Reject failure, non-finite or nonnegative loss, or invalid balance/budget.
- Raw volume = budget / absolute one-lot loss. Cap at broker maximum, floor to
  the volume step, and never increase volume to meet the minimum. Check the
  final volume with OrderCalcProfit and OrderCalcMargin. Estimated loss must
  not exceed the budget; rounding may remove another step to maintain it.
- Reject below-minimum volume, invalid symbol specifications, insufficient
  free margin, or invalid calculations. Do not silently substitute values.
- SL and TP are included in the initial CTrade market request. Synchronous
  requests use the symbol's supported filling mode and zero requested price
  deviation. Broker execution rules can still allow slippage.
- IMPORTANT execution assumption: final fill price is unknown before sending.
  Exact fill-based sizing and exact fill-based R cannot both be guaranteed
  while also prohibiting post-entry SL/TP changes. V1 sizes and fixes TP from
  the executable quote, logs the actual fill and resulting estimated SL loss,
  and never modifies SL/TP afterward. Commission, swap, gaps, and slippage can
  make realized loss exceed the nominal risk budget. Tick rounding can change R.

## End-of-day exit

At/after 20:00, attempt to close each owned position by ticket on the first
received tick, even if history, range, or daily state is unavailable. Also close
an overdue position from a previous server date on the first tick after a gap
across midnight. Retry failed/partial exits at most once per 60 server seconds;
log every actual attempt and broker result. Trading-disabled periods or market
closure can delay exit. Never open a new position outside the entry window.

## Restart and persistence

Outside the tester, terminal Global Variables use a namespace containing
`XRB1`, account login, symbol, Magic Number, and a hash of broker server name.
Names exceeding MT5's 63-character limit cause initialization failure; they are
not truncated. One temporary atomic lock permits one attached instance per
namespace in the same terminal. It is released on deinitialization and is not
persisted across terminal shutdown. Multiple independent terminals are not
coordinated; run only one terminal for this account/symbol/Magic combination.

Durable fields contain the server day, frozen high/low, schedule signature,
range-ready day marker, and consumed-opportunity day marker. Range-ready is
written last; a partially written record cannot authorize entry. Flush before
entry. Claim the opportunity atomically before filters/orders. Never erase it
on deinitialization. Changing the schedule after freezing blocks entries for
that date rather than changing the range. Changing risk/spread never revives
an already consumed opportunity. Persistence failure blocks entries for the
day, while forced exits remain active. Do not manually delete these variables
while using this strategy; MT5 may expire unused variables after four weeks.

On initialization and each server day, use HistorySelect and owned open
positions to recover successful entries. A history or position-read failure
blocks entry and is retried at new bars. Pending recovery cannot authorize a
trade. In the tester, use only per-run memory and tester history/positions;
never read or write terminal Global Variables. Each test/optimization pass
starts clean, with no state imported from another run or live/demo execution.

## Edge cases and non-goals

- No tick means no new-bar evaluation or time exit. No synthetic missed trades.
- Missing early-session candles (holidays, broker session breaks, incomplete
  history) invalidate the range for entry until the entire sequence exists.
- A restart before/during a signal bar does not cause an immediate late entry.
- A rejected/ambiguous market request is never resubmitted. Broker retcodes,
  order IDs and deal IDs are logged; a later entry deal is logged separately.
- Terminal disconnection, process crashes, disk failure, or external deletion
  of state cannot provide an absolute exactly-once guarantee. Persist-before-
  send deliberately favors skipping a trade after a crash over duplicating it.
- No indicators, martingale, grid, averaging, trailing stop, break-even,
  pending orders, news filter, optimization, or profitability assertions.

## Expected normal-day log events

Values in angle brackets depend on data; prefixes match the implementation.
An example assumes an eligible BUY at 06:15 and a position still open at 20:00.

1. `[V1] INIT ...` and symbol property lines on attachment before 06:00.
2. `[V1] DAY_RESET day=<date>` and `[V1] STATE ...`.
3. `[V1] BAR ...` once per observed M15 bar (time, bid, ask, spread).
4. After the 06:00 BAR: `[V1] RANGE_BUILD ...`, then `[V1] RANGE_FROZEN ...`.
5. `[V1] BREAKOUT direction=BUY candle=<date 06:00> ...`.
6. `[V1] OPPORTUNITY_CONSUMED day=<date>`.
7. `[V1] VOLUME ...`, `[V1] VOLUME_FINAL ...`, then `[V1] ORDER_RESULT ...`.
8. `[V1] ENTRY_DEAL ...` and `[V1] ENTRY_RISK ...` when the execution transaction is delivered.
9. `[V1] FORCED_EXIT ...` at/after 20:00, unless SL/TP already closed it.
10. Next server day: `DAY_RESET`, fresh range, fresh opportunity.
11. `[V1] DEINIT reason=<code>` on removal, recompile, or timeframe change.

Rejections log `SKIP reason=...`; data issues use `DATA_WAIT`;
persistence faults use `STATE_ERROR`. A no-breakout day has no opportunity,
volume, entry, or forced-exit log unless an earlier owned position remains.
