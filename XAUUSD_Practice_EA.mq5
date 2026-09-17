#property strict
#property version "2.00"
#property description "Experimental XAUUSD M15 session breakout. Demo/backtest only."

#include <Trade/Trade.mqh>

input ulong           InpMagicNumber        = 1997001;
input ENUM_TIMEFRAMES InpStrategyTimeframe  = PERIOD_M15;
input int             InpRangeStartHour     = 0;
input int             InpRangeEndHour       = 6;
input int             InpEntryEndHour       = 12;
input int             InpForcedExitHour     = 20;
input double          InpRiskPercent        = 0.5;
input double          InpRewardRiskRatio    = 1.0;
input double          InpMaxSpreadPoints    = 30.0;
input string          InpTradeComment       = "XAUUSD Range V1";

CTrade g_trade;
const int BAR_SECONDS = 900;
datetime g_day = 0, g_last_bar = 0, g_last_exit_attempt = 0;
double g_range_high = 0.0, g_range_low = 0.0;
double g_point = 0.0, g_tick_size = 0.0;
int g_digits = 0;
bool g_frozen = false, g_consumed = false, g_recovered = false;
bool g_blocked = false, g_tester = false, g_lock_held = false;
bool g_range_announced = false;
string g_namespace = "", g_last_data_issue = "", g_server = "";
long g_login = 0;

bool Positive(const double value)
{
   return MathIsValidNumber(value) && value > 0.0;
}

bool ReadDouble(const ENUM_SYMBOL_INFO_DOUBLE property, double &value)
{
   ResetLastError();
   if(!SymbolInfoDouble(_Symbol, property, value) || !MathIsValidNumber(value))
   {
      PrintFormat("[V1] PROPERTY_ERROR %s error=%d", EnumToString(property), GetLastError());
      return false;
   }
   return true;
}

bool ReadInteger(const ENUM_SYMBOL_INFO_INTEGER property, long &value)
{
   ResetLastError();
   if(!SymbolInfoInteger(_Symbol, property, value))
   {
      PrintFormat("[V1] PROPERTY_ERROR %s error=%d", EnumToString(property), GetLastError());
      return false;
   }
   return true;
}

void DataWait(const string reason)
{
   if(reason != g_last_data_issue)
      PrintFormat("[V1] DATA_WAIT reason=%s", reason);
   g_last_data_issue = reason;
}

void StateError(const string reason)
{
   if(!g_blocked)
      PrintFormat("[V1] STATE_ERROR reason=%s; entries blocked for this day", reason);
   g_blocked = true;
}

bool Skip(const string reason)
{
   PrintFormat("[V1] SKIP reason=%s; daily opportunity remains consumed", reason);
   return false;
}

datetime ServerDay(const datetime time)
{
   MqlDateTime parts = {};
   if(!TimeToStruct(time, parts))
      return 0;
   parts.hour = 0;
   parts.min = 0;
   parts.sec = 0;
   return StructToTime(parts);
}

int ScheduleSignature()
{
   return InpRangeStartHour + 24 * InpRangeEndHour +
          576 * InpEntryEndHour + 13824 * InpForcedExitHour;
}

bool ValidateInputs()
{
   return InpMagicNumber > 0 && InpMagicNumber <= (ulong)LONG_MAX &&
          InpStrategyTimeframe == PERIOD_M15 &&
          InpRangeStartHour >= 0 && InpRangeStartHour < InpRangeEndHour &&
          InpRangeEndHour < InpEntryEndHour &&
          InpEntryEndHour <= InpForcedExitHour && InpForcedExitHour <= 23 &&
          Positive(InpRiskPercent) && InpRiskPercent <= 100.0 &&
          Positive(InpRewardRiskRatio) && MathIsValidNumber(InpMaxSpreadPoints) &&
          InpMaxSpreadPoints >= 0.0 && StringLen(InpTradeComment) > 0 &&
          StringLen(InpTradeComment) <= 31;
}

bool LogSymbolProperties()
{
   bool ok = true;
   long digits = 0;
   if(!ReadInteger(SYMBOL_DIGITS, digits)) ok = false;
   else PrintFormat("[V1] digits=%I64d", digits);
   g_digits = (int)digits;
   ENUM_SYMBOL_INFO_DOUBLE properties[] = {
      SYMBOL_POINT, SYMBOL_TRADE_TICK_SIZE, SYMBOL_TRADE_TICK_VALUE,
      SYMBOL_TRADE_CONTRACT_SIZE, SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_MAX, SYMBOL_VOLUME_STEP
   };
   for(int i = 0; i < ArraySize(properties); i++)
   {
      double value = 0.0;
      if(!ReadDouble(properties[i], value)) { ok = false; continue; }
      PrintFormat("[V1] %s=%.16g", EnumToString(properties[i]), value);
      if(properties[i] == SYMBOL_POINT) g_point = value;
      if(properties[i] == SYMBOL_TRADE_TICK_SIZE) g_tick_size = value;
      // Tick value may legitimately be unavailable/zero before market conversion data.
      if(properties[i] != SYMBOL_TRADE_TICK_VALUE && !Positive(value)) ok = false;
   }
   long stops = 0, freeze = 0;
   if(!ReadInteger(SYMBOL_TRADE_STOPS_LEVEL, stops)) ok = false;
   else PrintFormat("[V1] stops_level_points=%I64d", stops);
   if(!ReadInteger(SYMBOL_TRADE_FREEZE_LEVEL, freeze)) ok = false;
   else PrintFormat("[V1] freeze_level_points=%I64d", freeze);
   return ok && g_digits >= 0 && g_digits <= 8 && stops >= 0 && freeze >= 0;
}

// Durable state is only for demo execution. Tester passes use memory and their
// own trade history, never terminal GVs. Include login/symbol/Magic/strategy and
// a server hash; never truncate long namespaces and accidentally share state.
bool SetupPersistence()
{
   if(g_tester) return true;
   string server = g_server;
   uint hash = 2166136261;
   for(int i = 0; i < StringLen(server); i++)
      hash = (hash ^ (uint)StringGetCharacter(server, i)) * 16777619;
   g_namespace = StringFormat("XRB1.%I64d.%s.%I64u.%08X", g_login, _Symbol, InpMagicNumber, hash);
   if(StringLen(g_namespace) + 2 > 63)
   {
      Print("[V1] INIT_ERROR persistence namespace exceeds 63 characters");
      return false;
   }
   string key = g_namespace + ".K";
   // Temporary lock is removed on terminal shutdown, durable opportunity is not.
   if(!GlobalVariableTemp(key) || !GlobalVariableSetOnCondition(key, (double)ChartID(), 0.0))
   {
      Print("[V1] INIT_ERROR another instance owns this namespace or lock unavailable");
      return false;
   }
   g_lock_held = true;
   if(!GlobalVariableCheck(g_namespace + ".O") &&
      GlobalVariableSet(g_namespace + ".O", 0.0) == 0)
   { StateError("cannot create opportunity record"); return false; }
   return true;
}

bool SaveValue(const string suffix, const double value)
{
   if(g_tester) return true;
   if(GlobalVariableSet(g_namespace + suffix, value) != 0) return true;
   StateError("persistent write failed: " + suffix);
   return false;
}

bool LoadValue(const string suffix, double &value)
{
   if(GlobalVariableGet(g_namespace + suffix, value) && MathIsValidNumber(value)) return true;
   StateError("persistent read failed: " + suffix);
   return false;
}

// PositionGetTicket selects each hedging position; failures block new entries.
bool SelectedPosition(bool &owned, datetime &opened)
{
   string symbol;
   long magic = 0, time = 0;
   if(!PositionGetString(POSITION_SYMBOL, symbol) ||
      !PositionGetInteger(POSITION_MAGIC, magic) ||
      !PositionGetInteger(POSITION_TIME, time)) return false;
   owned = symbol == _Symbol && (ulong)magic == InpMagicNumber;
   opened = (datetime)time;
   return true;
}

bool OwnedPositions(int &count, bool &entered_today)
{
   count = 0;
   entered_today = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetTicket(i) == 0) return false;
      bool owned = false;
      datetime opened = 0;
      if(!SelectedPosition(owned, opened)) return false;
      if(!owned) continue;
      count++;
      if(opened >= g_day) entered_today = true;
   }
   return true;
}

bool RecoverSuccessfulEntries(const datetime now)
{
   int positions = 0;
   bool found = false;
   if(!OwnedPositions(positions, found) || !HistorySelect(g_day, now))
   {
      DataWait("cannot recover positions/history");
      return false;
   }
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      string symbol;
      long magic = 0, entry = 0;
      if(deal == 0 || !HistoryDealGetString(deal, DEAL_SYMBOL, symbol) ||
         !HistoryDealGetInteger(deal, DEAL_MAGIC, magic) ||
         !HistoryDealGetInteger(deal, DEAL_ENTRY, entry))
      {
         DataWait("cannot read entry deal history");
         return false;
      }
      if(symbol == _Symbol && (ulong)magic == InpMagicNumber &&
         (entry == DEAL_ENTRY_IN || entry == DEAL_ENTRY_INOUT)) found = true;
   }
   if(found)
   {
      g_consumed = true;
      if(!SaveValue(".O", (double)g_day)) return false;
      if(!g_tester) GlobalVariablesFlush();
   }
   g_recovered = true;
   PrintFormat("[V1] STATE consumed=%s owned_positions=%d source=history/positions/persistence",
               g_consumed ? "true" : "false", positions);
   return true;
}

bool BeginDay(const datetime now)
{
   datetime day = ServerDay(now);
   if(day <= 0) return false;
   g_day = day;
   g_frozen = false;
   g_consumed = false;
   g_recovered = false;
   g_blocked = false;
   g_range_announced = false;
   g_range_high = 0.0;
   g_range_low = 0.0;
   g_last_data_issue = "";
   PrintFormat("[V1] DAY_RESET day=%s", TimeToString(g_day, TIME_DATE));
   if(!g_tester)
   {
      double opportunity_day = 0.0;
      if(!LoadValue(".O", opportunity_day)) return false;
      if(opportunity_day > (double)g_day) { StateError("future opportunity date"); return false; }
      g_consumed = opportunity_day == (double)g_day;
      if(GlobalVariableCheck(g_namespace + ".F"))
      {
         double frozen_day = 0.0;
         if(!LoadValue(".F", frozen_day)) return false;
         if(frozen_day > (double)g_day) { StateError("future range date"); return false; }
         if(frozen_day == (double)g_day)
         {
            double signature = 0.0;
            if(!LoadValue(".H", g_range_high) || !LoadValue(".L", g_range_low) ||
               !LoadValue(".S", signature)) return false;
            if(signature != ScheduleSignature() || !Positive(g_range_low) ||
               !Positive(g_range_high) || g_range_high <= g_range_low)
            { StateError("invalid frozen range or changed schedule"); return false; }
            g_frozen = true;
            PrintFormat("[V1] RANGE_RESTORED high=%s low=%s",
                        DoubleToString(g_range_high, g_digits), DoubleToString(g_range_low, g_digits));
         }
      }
   }
   return RecoverSuccessfulEntries(now);
}

bool ValidCandle(const MqlRates &bar)
{
   return Positive(bar.open) && Positive(bar.high) && Positive(bar.low) && Positive(bar.close) &&
          bar.high >= bar.low && bar.open >= bar.low && bar.open <= bar.high &&
          bar.close >= bar.low && bar.close <= bar.high;
}

bool FreezeRange(const datetime now)
{
   if(g_frozen) return true;
   datetime start = g_day + InpRangeStartHour * 3600;
   datetime end = g_day + InpRangeEndHour * 3600;
   if(now < end) return false;
   if(!g_range_announced)
   {
      PrintFormat("[V1] RANGE_BUILD start=%s end_exclusive=%s expected_bars=%d",
                  TimeToString(start, TIME_DATE | TIME_SECONDS), TimeToString(end, TIME_SECONDS),
                  (int)((end - start) / BAR_SECONDS));
      g_range_announced = true;
   }
   MqlRates bars[];
   int expected = (int)((end - start) / BAR_SECONDS);
   if(CopyRates(_Symbol, PERIOD_M15, start, end - 1, bars) != expected)
   { DataWait("range history incomplete"); return false; }
   double high = 0.0, low = DBL_MAX;
   for(int i = 0; i < expected; i++)
   {
      if(bars[i].time != start + i * BAR_SECONDS || !ValidCandle(bars[i]))
      { DataWait("range timestamp/OHLC invalid"); return false; }
      high = MathMax(high, bars[i].high);
      low = MathMin(low, bars[i].low);
   }
   if(high <= low) { DataWait("range high must exceed low"); return false; }
   // Commit marker is written last. An incomplete persisted range cannot be read.
   if(!SaveValue(".H", high) || !SaveValue(".L", low) ||
      !SaveValue(".S", (double)ScheduleSignature()) || !SaveValue(".F", (double)g_day)) return false;
   if(!g_tester) GlobalVariablesFlush();
   g_range_high = high;
   g_range_low = low;
   g_frozen = true;
   g_last_data_issue = "";
   PrintFormat("[V1] RANGE_FROZEN high=%s low=%s bars=%d",
               DoubleToString(high, g_digits), DoubleToString(low, g_digits), expected);
   return true;
}

bool ConsumeOpportunity()
{
   if(g_consumed || g_blocked) return false;
   // Mark memory first; persistence failure must never permit another attempt.
   g_consumed = true;
   if(!g_tester)
   {
      double old = 0.0;
      if(!LoadValue(".O", old)) return false;
      if(old >= (double)g_day) { StateError("opportunity already claimed or future date"); return false; }
      if(!GlobalVariableSetOnCondition(g_namespace + ".O", (double)g_day, old))
      { StateError("atomic opportunity claim failed"); return false; }
      GlobalVariablesFlush();
   }
   PrintFormat("[V1] OPPORTUNITY_CONSUMED day=%s", TimeToString(g_day, TIME_DATE));
   return true;
}

bool TradingAllowed(const bool buy, const bool closing)
{
   if(!TerminalInfoInteger(TERMINAL_CONNECTED) || !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ||
      !MQLInfoInteger(MQL_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) ||
      !AccountInfoInteger(ACCOUNT_TRADE_EXPERT)) return false;
   long mode = 0;
   if(!ReadInteger(SYMBOL_TRADE_MODE, mode)) return false;
   if(closing) return mode != SYMBOL_TRADE_MODE_DISABLED;
   return mode == SYMBOL_TRADE_MODE_FULL ||
          (buy && mode == SYMBOL_TRADE_MODE_LONGONLY) ||
          (!buy && mode == SYMBOL_TRADE_MODE_SHORTONLY);
}

double TickPrice(const double price, const bool upward)
{
   double units = price / g_tick_size;
   double nearest = MathRound(units);
   // Preserve already aligned candle prices despite binary floating-point noise.
   if(MathAbs(units - nearest) < 0.00000001)
      return NormalizeDouble(nearest * g_tick_size, g_digits);
   return NormalizeDouble((upward ? MathCeil(units) : MathFloor(units)) * g_tick_size, g_digits);
}

bool BuildPrices(const bool buy, const MqlTick &tick, double &entry, double &sl, double &tp)
{
   entry = buy ? tick.ask : tick.bid;
   double aligned_entry = NormalizeDouble(MathRound(entry / g_tick_size) * g_tick_size, g_digits);
   if(MathAbs(aligned_entry - entry) > g_tick_size * 0.000001)
      return Skip("entry quote is not aligned with tick size");
   entry = aligned_entry;
   sl = TickPrice(buy ? g_range_low : g_range_high, !buy);
   double distance = buy ? entry - sl : sl - entry;
   if(!Positive(sl) || !Positive(distance)) return Skip("SL is not on correct side of entry");
   double target = buy ? entry + distance * InpRewardRiskRatio : entry - distance * InpRewardRiskRatio;
   if(!Positive(target)) return Skip("invalid TP calculation");
   tp = TickPrice(target, buy);
   if(!Positive(tp) || (buy ? tp <= entry : tp >= entry)) return Skip("invalid normalized TP");
   long stops = 0, orders = 0;
   if(!ReadInteger(SYMBOL_TRADE_STOPS_LEVEL, stops) || stops < 0 ||
      !ReadInteger(SYMBOL_ORDER_MODE, orders)) return Skip("cannot read stop/order constraints");
   if((orders & SYMBOL_ORDER_MARKET) == 0 || (orders & SYMBOL_ORDER_SL) == 0 ||
      (orders & SYMBOL_ORDER_TP) == 0) return Skip("market order with initial SL/TP unsupported");
   double minimum_distance = stops * g_point;
   // Stops for buys are checked from Bid, for sells from Ask.
   double reference = buy ? tick.bid : tick.ask;
   double stop_distance = buy ? reference - sl : sl - reference;
   double target_distance = buy ? tp - reference : reference - tp;
   if(stop_distance <= 0.0 || target_distance <= 0.0 ||
      stop_distance < minimum_distance || target_distance < minimum_distance)
      return Skip("SL/TP violate broker stops level; no widening allowed");
   return true;
}

bool CalculateVolume(const bool buy, const double entry, const double sl, double &volume)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double budget = balance * InpRiskPercent / 100.0;
   if(!Positive(balance) || !Positive(budget)) return Skip("invalid balance or risk budget");
   ENUM_ORDER_TYPE type = buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double one_lot_profit = 0.0;
   ResetLastError();
   if(!OrderCalcProfit(type, _Symbol, 1.0, entry, sl, one_lot_profit) ||
      !MathIsValidNumber(one_lot_profit) || one_lot_profit >= 0.0)
      return Skip(StringFormat("invalid 1-lot SL loss error=%d", GetLastError()));
   double minimum = 0.0, maximum = 0.0, step = 0.0;
   if(!ReadDouble(SYMBOL_VOLUME_MIN, minimum) || !ReadDouble(SYMBOL_VOLUME_MAX, maximum) ||
      !ReadDouble(SYMBOL_VOLUME_STEP, step) || !Positive(minimum) || !Positive(maximum) ||
      !Positive(step) || minimum > maximum || NormalizeDouble(step, 8) != step)
      return Skip("invalid broker volume limits/step");
   double raw = budget / (-one_lot_profit);
   if(!Positive(raw)) return Skip("invalid raw volume");
   double cap = MathMin(raw, maximum);
   volume = NormalizeDouble(MathFloor(cap / step) * step, 8);
   // NormalizeDouble may round a floating representation upward: remove a step.
   if(volume > cap) volume = NormalizeDouble(volume - step, 8);
   PrintFormat("[V1] VOLUME balance=%.2f risk_money=%.2f loss_1lot=%.8f raw=%.8f floored=%.8f",
               balance, budget, -one_lot_profit, raw, volume);
   if(!Positive(volume) || volume < minimum || volume > maximum)
      return Skip("safe volume below minimum or outside broker bounds");
   double loss = 0.0;
   if(!OrderCalcProfit(type, _Symbol, volume, entry, sl, loss) ||
      !MathIsValidNumber(loss) || loss >= 0.0) return Skip("final volume loss calculation failed");
   if(-loss > budget)
   {
      volume = NormalizeDouble(volume - step, 8);
      if(!Positive(volume) || volume < minimum ||
         !OrderCalcProfit(type, _Symbol, volume, entry, sl, loss) ||
         !MathIsValidNumber(loss) || loss >= 0.0 || -loss > budget)
         return Skip("normalized volume exceeds risk budget");
   }
   double margin = 0.0;
   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(!OrderCalcMargin(type, _Symbol, volume, entry, margin) ||
      !MathIsValidNumber(margin) || margin < 0.0 || !Positive(free_margin) || margin > free_margin)
      return Skip("invalid or insufficient free margin");
   PrintFormat("[V1] VOLUME_FINAL lots=%.8f estimated_SL_loss=%.2f margin=%.2f", volume, -loss, margin);
   return true;
}

void SubmitEntry(const bool buy)
{
   // Refresh the quote at submission; never size from the signal candle close.
   MqlTick tick = {};
   if(!SymbolInfoTick(_Symbol, tick) || !Positive(tick.ask) || !Positive(tick.bid) ||
      tick.ask < tick.bid || tick.time < g_last_bar)
   { Skip("invalid/stale entry quote"); return; }
   if(TimeCurrent() > g_day + InpEntryEndHour * 3600 ||
      tick.time > g_day + InpEntryEndHour * 3600)
   { Skip("entry cutoff passed before submission"); return; }
   if(TimeCurrent() >= g_day + InpForcedExitHour * 3600)
   { Skip("forced exit time already reached"); return; }
   double spread = (tick.ask - tick.bid) / g_point;
   if(!MathIsValidNumber(spread) || spread > InpMaxSpreadPoints)
   { Skip(StringFormat("spread %.2f exceeds maximum %.2f points", spread, InpMaxSpreadPoints)); return; }
   int count = 0;
   bool entered = false;
   if(!OwnedPositions(count, entered)) { Skip("cannot inspect owned positions"); return; }
   if(count > 0) { Skip("owned position already open"); return; }
   if(!TradingAllowed(buy, false)) { Skip("trading unavailable"); return; }
   double entry = 0.0, sl = 0.0, tp = 0.0, volume = 0.0;
   if(!BuildPrices(buy, tick, entry, sl, tp) || !CalculateVolume(buy, entry, sl, volume)) return;
   if(!g_trade.SetTypeFillingBySymbol(_Symbol)) { Skip("unsupported filling mode"); return; }
   // Persisted opportunity is already consumed. There is exactly one request,
   // including on timeout, partial fill, rejection, or ambiguous broker result.
   ResetLastError();
   bool sent = buy ? g_trade.Buy(volume, _Symbol, entry, sl, tp, InpTradeComment) :
                     g_trade.Sell(volume, _Symbol, entry, sl, tp, InpTradeComment);
   PrintFormat("[V1] ORDER_RESULT direction=%s sent=%s retcode=%u description=%s order=%I64u deal=%I64u error=%d requested=%.8f fill=%.8f lots=%.8f SL=%.8f TP=%.8f",
               buy ? "BUY" : "SELL", sent ? "true" : "false", g_trade.ResultRetcode(),
               g_trade.ResultRetcodeDescription(), g_trade.ResultOrder(), g_trade.ResultDeal(),
               GetLastError(), entry, g_trade.ResultPrice(), g_trade.ResultVolume(), sl, tp);
   uint code = g_trade.ResultRetcode();
   if(!sent || (code != TRADE_RETCODE_DONE && code != TRADE_RETCODE_DONE_PARTIAL && code != TRADE_RETCODE_PLACED))
      Skip("market order failed/rejected; no entry retry");
}

void EvaluateBreakout(const datetime bar_time)
{
   if(g_consumed || g_blocked || !g_recovered || !g_frozen) return;
   datetime start = g_day + InpRangeEndHour * 3600;
   if(bar_time <= start || bar_time > g_day + InpEntryEndHour * 3600) return;
   MqlRates candles[];
   int expected = (int)((bar_time - start) / BAR_SECONDS);
   if(CopyRates(_Symbol, PERIOD_M15, start, bar_time - 1, candles) != expected)
   { DataWait("signal history incomplete"); return; }
   for(int i = 0; i < expected; i++)
      if(candles[i].time != start + i * BAR_SECONDS || !ValidCandle(candles[i]))
      { DataWait("signal timestamp/OHLC invalid"); return; }
   // Scan chronologically so a missed first breakout cannot become a later trade.
   // The time-bounded copy excludes the forming candle (index 0 in timeseries).
   for(int i = 0; i < expected; i++)
   {
      bool buy = candles[i].close > g_range_high;
      bool sell = candles[i].close < g_range_low;
      if(!buy && !sell) continue;
      PrintFormat("[V1] BREAKOUT direction=%s candle=%s close=%s",
                  buy ? "BUY" : "SELL", TimeToString(candles[i].time, TIME_DATE | TIME_SECONDS),
                  DoubleToString(candles[i].close, g_digits));
      if(!ConsumeOpportunity()) return;
      if(candles[i].time != bar_time - BAR_SECONDS)
      { Skip("first breakout occurred while detached/data unavailable; no late entry"); return; }
      SubmitEntry(buy);
      return;
   }
}

void CloseDuePositions(const datetime now)
{
   if(g_last_exit_attempt != 0 && now - g_last_exit_attempt < 60) return;
   datetime day = ServerDay(now);
   if(day <= 0) return;
   bool attempted = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      bool owned = false;
      datetime opened = 0;
      if(ticket == 0 || !SelectedPosition(owned, opened))
      {
         if(!attempted) Print("[V1] FORCED_EXIT position scan unavailable; will retry");
         attempted = true;
         continue;
      }
      if(!owned || (now < day + InpForcedExitHour * 3600 && ServerDay(opened) >= day)) continue;
      attempted = true;
      if(!TradingAllowed(false, true) || !g_trade.SetTypeFillingBySymbol(_Symbol))
      { PrintFormat("[V1] FORCED_EXIT ticket=%I64u skipped=trading unavailable", ticket); continue; }
      // Ticket overload is essential on hedging accounts. No symbol-wide close.
      ResetLastError();
      bool closed = g_trade.PositionClose(ticket, 0);
      PrintFormat("[V1] FORCED_EXIT ticket=%I64u sent=%s retcode=%u description=%s error=%d",
                  ticket, closed ? "true" : "false", g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription(), GetLastError());
   }
   if(attempted) g_last_exit_attempt = now;
}

int OnInit()
{
   if(!ValidateInputs())
   {
      Print("[V1] INIT_ERROR invalid inputs: require M15, ordered hours, positive risk/R, valid spread/Magic/comment");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(StringFind(_Symbol, "XAUUSD") < 0)
   {
      PrintFormat("[V1] INIT_ERROR symbol=%s does not contain XAUUSD", _Symbol);
      return INIT_PARAMETERS_INCORRECT;
   }
   g_tester = (bool)MQLInfoInteger(MQL_TESTER);
   g_login = AccountInfoInteger(ACCOUNT_LOGIN);
   g_server = AccountInfoString(ACCOUNT_SERVER);
   if((!g_tester && (g_login <= 0 || StringLen(g_server) == 0)) || AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ||
      (!g_tester && AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL))
   {
      Print("[V1] INIT_ERROR requires demo/tester hedging account with valid login");
      return INIT_FAILED;
   }
   PrintFormat("[V1] INIT symbol=%s strategy=PERIOD_M15 chart=%s magic=%I64u range=%02d-%02d entry_end=%02d exit=%02d risk=%.4f%% R=%.4f spread_max=%.2f comment=%s tester=%s",
               _Symbol, EnumToString(_Period), InpMagicNumber, InpRangeStartHour, InpRangeEndHour,
               InpEntryEndHour, InpForcedExitHour, InpRiskPercent, InpRewardRiskRatio,
               InpMaxSpreadPoints, InpTradeComment, g_tester ? "true" : "false");
   if(!LogSymbolProperties() || !SetupPersistence()) return INIT_FAILED;
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetAsyncMode(false);
   g_trade.SetDeviationInPoints(0);
   g_trade.LogLevel(LOG_LEVEL_NO);
   if(!g_trade.SetTypeFillingBySymbol(_Symbol))
   { Print("[V1] INIT_ERROR symbol filling mode unavailable"); return INIT_FAILED; }
   datetime now = TimeCurrent();
   if(now <= 0) { Print("[V1] INIT_ERROR server time unavailable"); return INIT_FAILED; }
   bool restored = BeginDay(now);
   if(!restored) Print("[V1] STATE recovery pending or blocked; entries disabled until safe");
   if(!g_blocked) FreezeRange(now);
   // Reattaching never enters in the middle of the currently forming candle.
   g_last_bar = iTime(_Symbol, PERIOD_M15, 0);
   return INIT_SUCCEEDED;
}

void OnTick()
{
   datetime now = TimeCurrent();
   if(now <= 0) return;
   if(AccountInfoInteger(ACCOUNT_LOGIN) != g_login || AccountInfoString(ACCOUNT_SERVER) != g_server)
   { StateError("account changed; reattach EA"); return; }
   // Forced exits are independent of daily data/recovery/entry failures.
   CloseDuePositions(now);
   datetime day = ServerDay(now);
   if(day <= 0) return;
   if(day != g_day) BeginDay(now);
   datetime bar_time = iTime(_Symbol, PERIOD_M15, 0);
   if(bar_time <= 0 || bar_time > now || bar_time < day) return;
   if(g_last_bar == 0) { g_last_bar = bar_time; return; }
   if(bar_time <= g_last_bar) return;
   // Claim this bar before any reads or trading; never retry an entry per tick.
   g_last_bar = bar_time;
   MqlTick tick = {};
   if(SymbolInfoTick(_Symbol, tick) && Positive(tick.bid) && Positive(tick.ask) && tick.ask >= tick.bid)
      PrintFormat("[V1] BAR time=%s bid=%s ask=%s spread=%.2f points",
                  TimeToString(bar_time, TIME_DATE | TIME_SECONDS), DoubleToString(tick.bid, g_digits),
                  DoubleToString(tick.ask, g_digits), (tick.ask - tick.bid) / g_point);
   else DataWait("new-bar quote unavailable");
   if(g_blocked) return;
   if(!g_recovered && !RecoverSuccessfulEntries(now)) return;
   if(!FreezeRange(now)) return;
   if(now > g_day + InpEntryEndHour * 3600) return;
   EvaluateBreakout(bar_time);
}

void OnTradeTransaction(const MqlTradeTransaction &transaction,
                        const MqlTradeRequest &request, const MqlTradeResult &result)
{
   if(transaction.type != TRADE_TRANSACTION_DEAL_ADD || transaction.deal == 0) return;
   if(!HistoryDealSelect(transaction.deal))
   { PrintFormat("[V1] DEAL_READ_ERROR ticket=%I64u error=%d", transaction.deal, GetLastError()); return; }
   string symbol;
   long magic = 0, entry = 0;
   double price = 0.0, volume = 0.0, sl = 0.0;
   if(!HistoryDealGetString(transaction.deal, DEAL_SYMBOL, symbol) ||
      !HistoryDealGetInteger(transaction.deal, DEAL_MAGIC, magic) ||
      !HistoryDealGetInteger(transaction.deal, DEAL_ENTRY, entry) ||
      !HistoryDealGetDouble(transaction.deal, DEAL_PRICE, price) ||
      !HistoryDealGetDouble(transaction.deal, DEAL_VOLUME, volume) ||
      !HistoryDealGetDouble(transaction.deal, DEAL_SL, sl))
   { PrintFormat("[V1] DEAL_READ_ERROR ticket=%I64u", transaction.deal); return; }
   if(symbol != _Symbol || (ulong)magic != InpMagicNumber || entry != DEAL_ENTRY_IN) return;
   PrintFormat("[V1] ENTRY_DEAL deal=%I64u price=%s lots=%.8f SL=%s",
               transaction.deal, DoubleToString(price, g_digits), volume, DoubleToString(sl, g_digits));
   long type = 0;
   double profit = 0.0;
   if(HistoryDealGetInteger(transaction.deal, DEAL_TYPE, type) && Positive(sl) &&
      OrderCalcProfit(type == DEAL_TYPE_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                      _Symbol, volume, price, sl, profit) && MathIsValidNumber(profit))
      PrintFormat("[V1] ENTRY_RISK actual_fill_SL_loss=%.2f excluding costs/gaps", -profit);
   else Print("[V1] ENTRY_RISK unavailable; no post-entry SL/TP modification");
}

void OnDeinit(const int reason)
{
   if(g_lock_held && !g_tester)
   {
      if(!GlobalVariableSetOnCondition(g_namespace + ".K", 0.0, (double)ChartID()))
         PrintFormat("[V1] STATE_ERROR lock release failed error=%d", GetLastError());
      GlobalVariablesFlush();
   }
   PrintFormat("[V1] DEINIT reason=%d symbol=%s", reason, _Symbol);
}
