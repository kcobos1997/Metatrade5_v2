#property strict
#property version   "1.00"
#property description "Phase 1: symbol and new-bar diagnostics only. No trading."

input ulong InpMagicNumber = 1997001; // Reserved for future use; never used to trade.

datetime g_last_bar_time = 0;

// Failed property reads are explicit rather than reported as valid zero values.
void LogIntegerProperty(const string label, const ENUM_SYMBOL_INFO_INTEGER property)
{
   long value = 0;
   ResetLastError();
   if(SymbolInfoInteger(_Symbol, property, value))
      PrintFormat("[Phase 1] %s=%I64d", label, value);
   else
      PrintFormat("[Phase 1] %s=unavailable (error=%d)", label, GetLastError());
}

void LogDoubleProperty(const string label, const ENUM_SYMBOL_INFO_DOUBLE property)
{
   double value = 0.0;
   ResetLastError();
   if(SymbolInfoDouble(_Symbol, property, value))
      PrintFormat("[Phase 1] %s=%.16g", label, value);
   else
      PrintFormat("[Phase 1] %s=unavailable (error=%d)", label, GetLastError());
}

int OnInit()
{
   PrintFormat("[Phase 1] Diagnostic EA: symbol=%s timeframe=%s magic=%I64u (reserved)",
               _Symbol, EnumToString(_Period), InpMagicNumber);

   if(StringFind(_Symbol, "XAUUSD") < 0)
      PrintFormat("[Phase 1] WARNING: active symbol '%s' does not contain XAUUSD; diagnostics continue.",
                  _Symbol);

   LogIntegerProperty("digits", SYMBOL_DIGITS);
   LogDoubleProperty("point", SYMBOL_POINT);
   LogDoubleProperty("tick_size", SYMBOL_TRADE_TICK_SIZE);
   LogDoubleProperty("tick_value", SYMBOL_TRADE_TICK_VALUE);
   LogDoubleProperty("contract_size", SYMBOL_TRADE_CONTRACT_SIZE);
   LogDoubleProperty("minimum_volume", SYMBOL_VOLUME_MIN);
   LogDoubleProperty("maximum_volume", SYMBOL_VOLUME_MAX);
   LogDoubleProperty("volume_step", SYMBOL_VOLUME_STEP);
   LogIntegerProperty("stops_level_points", SYMBOL_TRADE_STOPS_LEVEL);
   LogIntegerProperty("freeze_level_points", SYMBOL_TRADE_FREEZE_LEVEL);

   if(!MathIsValidNumber(_Point) || _Point <= 0.0)
   {
      Print("[Phase 1] ERROR: invalid symbol point; cannot calculate spread.");
      return INIT_FAILED;
   }

   // Do not label the existing bar as new when attaching or reinitializing.
   // If history is not ready, the first valid bar in OnTick becomes the baseline.
   g_last_bar_time = iTime(_Symbol, _Period, 0);
   return INIT_SUCCEEDED;
}

void OnTick()
{
   const datetime bar_time = iTime(_Symbol, _Period, 0);
   if(bar_time <= 0)
      return;

   if(g_last_bar_time == 0)
   {
      g_last_bar_time = bar_time;
      return;
   }

   // Ignore repeated or older timestamps, including transient history changes.
   if(bar_time <= g_last_bar_time)
      return;

   MqlTick tick = {};
   if(!SymbolInfoTick(_Symbol, tick))
      return;
   if(tick.time < bar_time || !MathIsValidNumber(tick.bid) ||
      !MathIsValidNumber(tick.ask) || tick.bid <= 0.0 || tick.ask <= 0.0 ||
      tick.ask < tick.bid)
      return;

   const double spread_points = (tick.ask - tick.bid) / _Point;
   PrintFormat("[Phase 1] %s %s bar=%s bid=%s ask=%s spread=%.2f points",
               _Symbol, EnumToString(_Period),
               TimeToString(bar_time, TIME_DATE | TIME_SECONDS),
               DoubleToString(tick.bid, _Digits),
               DoubleToString(tick.ask, _Digits), spread_points);

   // Mark the bar only after valid diagnostics, allowing silent retries otherwise.
   g_last_bar_time = bar_time;
}

void OnDeinit(const int reason)
{
   PrintFormat("[Phase 1] Diagnostic EA stopped: symbol=%s reason=%d", _Symbol, reason);
}
