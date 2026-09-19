#property strict
#property version "1.00"
#property description "XAUUSD Intraday V1: causal diagnostic scanner; no trading."

input int    EMA_H1_Period = 50;
input int    PullbackBars = 3;
input int    BreakoutLookback = 3;
input int    CooldownBars = 2;
input ulong  MagicNumber = 1997101;
input int    NYStartHour = 8;
input int    NYEndHour = 12;
input string BrokerUtcSchedule = ""; // UTC_from|UTC_until|offset_minutes;...
input string RunId = "";              // Required, unique per tester experiment.
input bool   SelfTestOnly = false;

#define SCHEMA "scanner-v1"
#define CSV_COLUMNS 39
#define MAX_CSV_BYTES 134217728

struct Lane
{
   bool active;
   datetime start;
   long start_index;
   int length;
   long cooldown_until;
};
struct Engine
{
   datetime last;
   long index;
   int gate;
   bool ready;
   Lane lanes[4]; // B0 buy, B0 sell, PB1 buy, PB1 sell.
};
struct Frame
{
   datetime decision, observed, utc, ny, observed_utc, h1_open;
   int server_offset, ny_offset, session, gate;
   double h1_close, ema, bid, ask, spread;
   string error;
   MqlRates bars[]; // Chronological; never contains the open M5.
};
struct Verdict
{
   bool raw;
   string reason;
   datetime episode;
};
struct OffsetInterval
{
   datetime from_utc, until_utc;
   int minutes;
};

Engine g_engine;
OffsetInterval g_offsets[];
int g_ema = INVALID_HANDLE;
int g_file = INVALID_HANDLE;
string g_identity, g_filename;
bool g_halted = false;
long g_warning_bucket = -1;
int g_passed = 0, g_failed = 0;

string I(const long value) { return IntegerToString(value); }
string D(const double value) { return DoubleToString(value, 16); }
string Channel(const int i)
{
   if(i == 0) return "B0:BUY";
   if(i == 1) return "B0:SELL";
   if(i == 2) return "PB1:BUY";
   return "PB1:SELL";
}
string HexText(const string value)
{
   string result = "";
   for(int i = 0; i < StringLen(value); i++)
      result += StringFormat("%04X", (uint)StringGetCharacter(value, i));
   return result;
}
string Hash(const string value, const uint seed = 2166136261)
{
   uint h = seed;
   for(int i = 0; i < StringLen(value); i++)
      h = (h ^ (uint)StringGetCharacter(value, i)) * 16777619;
   return StringFormat("%08X", h);
}
bool IntegerField(const string value, long &result)
{
   result = StringToInteger(value);
   return I(result) == value;
}
bool SafeId(const string value)
{
   if(StringLen(value) < 1 || StringLen(value) > 64) return false;
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort c = StringGetCharacter(value, i);
      if(!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
   }
   return true;
}
void Halt(const string reason)
{
   if(!g_halted) Print("[Scanner] HALTED: ", reason);
   g_halted = true;
}
bool IsNewDecision(const datetime decision, const datetime watermark)
{
   return decision > 0 && decision > watermark;
}
bool ClosedH1(const datetime open, const datetime decision)
{
   return open > 0 && open + 3600 <= decision && decision - (open + 3600) < 3600;
}
bool ValidPrice(const double value)
{
   return MathIsValidNumber(value) && value > 0 && value != EMPTY_VALUE;
}
bool ValidBar(const MqlRates &bar)
{
   return bar.time > 0 && ValidPrice(bar.open) && ValidPrice(bar.high) &&
          ValidPrice(bar.low) && ValidPrice(bar.close) &&
          bar.low <= MathMin(bar.open, bar.close) &&
          bar.high >= MathMax(bar.open, bar.close);
}

// ----- Time conversion: explicit broker schedule, versioned US DST rules. -----
bool ParseSchedule(const string value, OffsetInterval &offsets[])
{
   ArrayResize(offsets, 0);
   if(value == "") return true;
   string rows[];
   int count = StringSplit(value, ';', rows);
   if(count < 1 || count > 512) return false;
   ArrayResize(offsets, count);
   for(int i = 0; i < count; i++)
   {
      string cells[];
      if(StringSplit(rows[i], '|', cells) != 3) return false;
      datetime start = StringToTime(cells[0]), end = StringToTime(cells[1]);
      long minutes;
      if(TimeToString(start, TIME_DATE|TIME_MINUTES) != cells[0] ||
         TimeToString(end, TIME_DATE|TIME_MINUTES) != cells[1] ||
         start <= 0 || end <= start || !IntegerField(cells[2], minutes) ||
         minutes < -840 || minutes > 840) return false;
      if(i > 0 && start < offsets[i-1].until_utc) return false;
      offsets[i].from_utc = start;
      offsets[i].until_utc = end;
      offsets[i].minutes = (int)minutes;
   }
   return true;
}
bool ServerToUtc(const datetime server, const OffsetInterval &offsets[],
                 datetime &utc, int &minutes)
{
   int matches = 0;
   utc = 0; minutes = 0;
   for(int i = 0; i < ArraySize(offsets); i++)
   {
      datetime candidate = server - offsets[i].minutes * 60;
      if(candidate >= offsets[i].from_utc && candidate < offsets[i].until_utc)
      {
         matches++;
         utc = candidate;
         minutes = offsets[i].minutes;
      }
   }
   if(matches == 1) return true;
   utc = 0; minutes = 0;
   return false;
}
datetime SundayUtc(const int year, const int month, const int ordinal, const int hour)
{
   MqlDateTime date = {};
   date.year = year; date.mon = month; date.day = 1; date.hour = hour;
   datetime first = StructToTime(date);
   TimeToStruct(first, date);
   return first + ((7 - date.day_of_week) % 7 + 7 * (ordinal - 1)) * 86400;
}
bool NewYorkTime(const datetime utc, datetime &ny, int &offset)
{
   MqlDateTime date = {};
   ny = 0; offset = 0;
   if(!TimeToStruct(utc, date) || date.year < 2007 || date.year > 2099) return false;
   datetime from = SundayUtc(date.year, 3, 2, 7);
   datetime until = SundayUtc(date.year, 11, 1, 6);
   offset = (utc >= from && utc < until) ? -240 : -300;
   ny = utc + offset * 60;
   return true;
}
int SessionAt(const datetime ny, const int start_hour, const int end_hour)
{
   MqlDateTime date = {};
   if(ny <= 0 || !TimeToStruct(ny, date)) return -1;
   return (date.hour >= start_hour && date.hour < end_hour) ? 1 : 0;
}
void ConvertTimes(Frame &frame)
{
   frame.session = -1;
   if(ServerToUtc(frame.decision, g_offsets, frame.utc, frame.server_offset) &&
      NewYorkTime(frame.utc, frame.ny, frame.ny_offset))
      frame.session = SessionAt(frame.ny, NYStartHour, NYEndHour);
   int observed_offset = 0;
   ServerToUtc(frame.observed, g_offsets, frame.observed_utc, observed_offset);
}

// ----- Pure signal/state logic: no terminal, indicator or file calls. -----
string RawPattern(const Frame &frame, const int lane, const int p, const int b, bool &raw)
{
   raw = false;
   int n = ArraySize(frame.bars), last = n - 1;
   if(n < MathMax(p, b) + 1) return "DATA_M5";
   bool buy = (lane % 2 == 0);
   double level = 0;
   if(lane < 2)
   {
      level = buy ? frame.bars[last-1].high : frame.bars[last-1].low;
      for(int j = last-b; j < last; j++)
         level = buy ? MathMax(level, frame.bars[j].high) : MathMin(level, frame.bars[j].low);
   }
   else
   {
      for(int j = last-p+1; j < last; j++)
      {
         if(buy && frame.bars[j-1].close <= frame.bars[j].close) return "NO_SETUP";
         if(!buy && frame.bars[j-1].close >= frame.bars[j].close) return "NO_SETUP";
      }
      level = buy ? frame.bars[last-1].high : frame.bars[last-1].low;
   }
   double close = frame.bars[last].close;
   if(close == level) return "EQUALITY";
   raw = buy ? close > level : close < level;
   return raw ? "RAW" : "NO_BREAKOUT";
}
void ResetEngine(Engine &state, const datetime decision, const long index)
{
   ZeroMemory(state);
   state.last = decision;
   state.index = index;
   state.gate = 9;
}
void Evaluate(const Frame &frame, Engine &state, Verdict &out[],
              const int p, const int b, const int cooldown)
{
   ArrayResize(out, 4);
   string pattern[4];
   for(int i = 0; i < 4; i++)
   {
      pattern[i] = RawPattern(frame, i, p, b, out[i].raw);
      out[i].reason = pattern[i];
      out[i].episode = 0;
   }
   long k = state.index + 1;
   string block = StringLen(frame.error) > 0 ? frame.error : "";
   if(block == "" && ArraySize(frame.bars) < MathMax(p, b) + 1) block = "DATA_M5";
   if(block == "" && state.last > 0 && frame.decision - state.last != 300) block = "GAP_RESET";
   if(block == "" && !state.ready) block = "BASELINE";
   if(block != "")
   {
      ResetEngine(state, frame.decision, k);
      bool baseline = (block == "BASELINE" || block == "GAP_RESET");
      state.ready = baseline;
      state.gate = baseline ? frame.gate : 9;
      for(int i = 0; i < 4; i++)
      {
         out[i].reason = block;
         if(!baseline) continue;
         state.lanes[i].start = frame.decision - 300;
         state.lanes[i].start_index = k;
         state.lanes[i].length = (i >= 2) ? 1 : 0;
         state.lanes[i].active = (i < 2 && out[i].raw);
         if(state.lanes[i].active) out[i].episode = state.lanes[i].start;
      }
      return;
   }
   bool changed = state.gate != frame.gate;
   int last = ArraySize(frame.bars) - 1;
   for(int i = 0; i < 4; i++)
   {
      Lane lane = state.lanes[i];
      bool buy = i % 2 == 0;
      bool consumed = lane.active;
      if(out[i].raw)
      {
         if(i < 2 && !consumed)
         {
            lane.start = frame.decision - 300;
            lane.start_index = k;
         }
         out[i].episode = lane.start;
         if(consumed) out[i].reason = "EPISODE_CONSUMED";
         else if(i >= 2 && changed) out[i].reason = "H1_CHANGED";
         else if(k <= lane.cooldown_until) out[i].reason = "COOLDOWN";
         else if(i >= 2 && (lane.length < p || lane.start_index <= lane.cooldown_until))
            out[i].reason = "FRESH_SEQUENCE_REQUIRED";
         else if(frame.gate == 0) out[i].reason = "H1_NEUTRAL";
         else if(frame.gate != (buy ? 1 : -1)) out[i].reason = "H1_OPPOSED";
         else if(frame.session < 0) out[i].reason = "SESSION_UNKNOWN";
         else if(frame.session == 0) out[i].reason = "OUTSIDE_SESSION";
         else out[i].reason = "ACCEPT_DIAGNOSTIC";
         if(!consumed)
         {
            lane.active = true;
            lane.cooldown_until = k + cooldown;
         }
      }
      else if(i < 2 && k > lane.cooldown_until)
      {
         lane.active = false;
         lane.start = 0;
         lane.start_index = 0;
      }
      if(i >= 2)
      {
         bool extends = buy ? frame.bars[last].close < frame.bars[last-1].close :
                              frame.bars[last].close > frame.bars[last-1].close;
         if(changed || lane.length == 0 || !extends)
         {
            lane.start = frame.decision - 300;
            lane.start_index = k;
            lane.length = 1;
            lane.active = false;
         }
         else if(lane.length < 1000000000) lane.length++;
      }
      state.lanes[i] = lane;
   }
   state.index = k;
   state.last = frame.decision;
   state.gate = frame.gate;
}

// ----- Market adapter: explicit closed-bar alignment and checked copies. -----
void ReadFrame(const datetime decision, Frame &frame)
{
   ZeroMemory(frame);
   frame.error = ""; // ZeroMemory leaves MQL5 strings NULL, not an allocated empty string.
   frame.decision = decision;
   frame.observed = TimeCurrent();
   ConvertTimes(frame);
   MqlTick tick = {};
   if(!SymbolInfoTick(_Symbol, tick) || tick.time < decision ||
      !ValidPrice(tick.bid) || !ValidPrice(tick.ask) || tick.ask < tick.bid || !ValidPrice(_Point))
   {
      frame.error = "DATA_TICK";
      return;
   }
   frame.observed = tick.time;
   frame.bid = tick.bid; frame.ask = tick.ask;
   frame.spread = (tick.ask - tick.bid) / _Point;
   ConvertTimes(frame);
   int count = MathMax(PullbackBars, BreakoutLookback) + 1;
   ArraySetAsSeries(frame.bars, false);
   if(CopyRates(_Symbol, PERIOD_M5, 1, count, frame.bars) != count)
   {
      frame.error = "DATA_M5";
      return;
   }
   for(int i = 0; i < count; i++)
   {
      if(!ValidBar(frame.bars[i]) || frame.bars[i].time != decision - (count-i)*300)
      {
         frame.error = "DATA_M5";
         return;
      }
   }
   int shift = iBarShift(_Symbol, PERIOD_H1, decision - 3600, false);
   int warmup = 5 * EMA_H1_Period;
   MqlRates hours[];
   ArraySetAsSeries(hours, false);
   if(shift < 1 || CopyRates(_Symbol, PERIOD_H1, shift, warmup, hours) != warmup)
   {
      frame.error = "DATA_H1";
      return;
   }
   for(int i = 0; i < warmup; i++)
   {
      if(!ValidBar(hours[i]) || hours[i].time + 3600 > decision ||
         (i > 0 && hours[i].time <= hours[i-1].time))
      {
         frame.error = "DATA_H1";
         return;
      }
   }
   frame.h1_open = hours[warmup-1].time;
   frame.h1_close = hours[warmup-1].close;
   if(!ClosedH1(frame.h1_open, decision))
   {
      frame.error = "DATA_H1";
      return;
   }
   double ema[];
   if(g_ema == INVALID_HANDLE || BarsCalculated(g_ema) < shift + warmup ||
      CopyBuffer(g_ema, 0, shift, 1, ema) != 1 || !ValidPrice(ema[0]))
   {
      frame.error = "DATA_EMA";
      return;
   }
   // Reject a series that changed alignment while the adapter was reading.
   if(iTime(_Symbol, PERIOD_M5, 0) != decision ||
      iTime(_Symbol, PERIOD_H1, shift) != frame.h1_open)
   {
      frame.error = "DATA_H1";
      return;
   }
   frame.ema = ema[0];
   frame.gate = frame.h1_close > frame.ema ? 1 : (frame.h1_close < frame.ema ? -1 : 0);
}

// ----- CSV/checkpoint adapter: one complete row commits all four channels. -----
string StateText(const Engine &state)
{
   string result = I(state.last)+";"+I(state.index)+";"+I(state.gate)+";"+I(state.ready);
   for(int i = 0; i < 4; i++)
      result += ";"+I(state.lanes[i].active)+";"+I(state.lanes[i].start)+";"+
                I(state.lanes[i].start_index)+";"+I(state.lanes[i].length)+";"+
                I(state.lanes[i].cooldown_until);
   return result;
}
bool RestoreState(const string encoded, Engine &state)
{
   string cells[];
   if(StringSplit(encoded, ';', cells) != 24) return false;
   long values[24];
   for(int i = 0; i < 24; i++)
      if(!IntegerField(cells[i], values[i])) return false;
   if(values[0] <= 0 || values[1] < 1 ||
      !(values[2] == -1 || values[2] == 0 || values[2] == 1 || values[2] == 9) ||
      values[3] < 0 || values[3] > 1) return false;
   ResetEngine(state, (datetime)values[0], values[1]);
   state.gate = (int)values[2]; state.ready = values[3] == 1;
   if(state.ready && state.gate == 9) return false;
   for(int i = 0; i < 4; i++)
   {
      int j = 4 + i*5;
      if(values[j] < 0 || values[j] > 1 || values[j+1] < 0 || values[j+1] > state.last ||
         values[j+2] < 0 || values[j+2] > state.index ||
         values[j+3] < 0 || values[j+3] > 1000000000 ||
         values[j+4] < 0 || values[j+4] > state.index + 100) return false;
      state.lanes[i].active = values[j] == 1;
      state.lanes[i].start = (datetime)values[j+1];
      state.lanes[i].start_index = values[j+2];
      state.lanes[i].length = (int)values[j+3];
      state.lanes[i].cooldown_until = values[j+4];
   }
   return true;
}
string CsvHeader()
{
   string result = "identity,decision_server,signal_open_server,observed_server,delay_seconds,"+
                   "decision_utc,decision_ny,observed_utc,server_offset_minutes,ny_offset_minutes,"+
                   "session,data_status,h1_open_server,h1_close,h1_ema,h1_gate,bid,ask,spread_points,"+
                   "m5_window,trade_authorized";
   string names[4] = {"b0_buy", "b0_sell", "pb1_buy", "pb1_sell"};
   for(int i = 0; i < 4; i++)
      result += ","+names[i]+"_key,"+names[i]+"_raw,"+names[i]+"_reason,"+names[i]+"_episode_server";
   return result + ",state,checksum";
}
string EventKey(const string identity, const datetime decision, const int lane)
{
   return identity+":"+I(decision)+":"+Channel(lane);
}
string MakeRow(const string identity, const Frame &frame, const Engine &state, const Verdict &out[])
{
   string window = "";
   for(int i = 0; i < ArraySize(frame.bars); i++)
   {
      if(i > 0) window += ";";
      window += I(frame.bars[i].time)+":"+D(frame.bars[i].open)+":"+D(frame.bars[i].high)+":"+
                D(frame.bars[i].low)+":"+D(frame.bars[i].close);
   }
   string session = frame.session < 0 ? "UNKNOWN" : (frame.session == 1 ? "IN" : "OUT");
   string status = StringLen(frame.error) == 0 ? "OK" : frame.error;
   string row = identity+","+I(frame.decision)+","+I(frame.decision-300)+","+I(frame.observed)+","+
                I(frame.observed-frame.decision)+","+I(frame.utc)+","+I(frame.ny)+","+
                I(frame.observed_utc)+","+I(frame.server_offset)+","+I(frame.ny_offset)+","+
                session+","+status+","+I(frame.h1_open)+","+D(frame.h1_close)+","+D(frame.ema)+","+
                I(frame.gate)+","+D(frame.bid)+","+D(frame.ask)+","+D(frame.spread)+","+window+",0";
   for(int i = 0; i < 4; i++)
      row += ","+EventKey(identity, frame.decision, i)+","+I(out[i].raw)+","+
             out[i].reason+","+I(out[i].episode);
   row += ","+StateText(state);
   return row+","+Hash(row);
}
bool RestoreRow(const string row, const string identity, Engine &state)
{
   string cells[];
   if(StringSplit(row, ',', cells) != CSV_COLUMNS || cells[0] != identity) return false;
   int body_length = StringLen(row) - StringLen(cells[38]) - 1;
   if(body_length < 1 || Hash(StringSubstr(row, 0, body_length)) != cells[38]) return false;
   long decision;
   if(!IntegerField(cells[1], decision) || cells[20] != "0" ||
      !RestoreState(cells[37], state) || state.last != decision) return false;
   for(int i = 0; i < 4; i++)
      if(cells[21+i*4] != EventKey(identity, state.last, i)) return false;
   return true;
}
bool WriteBytes(const string text)
{
   uchar bytes[];
   int count = StringToCharArray(text, bytes, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   if(count < 1) return false;
   ResetLastError();
   if(FileWriteArray(g_file, bytes, 0, count) != (uint)count) return false;
   FileFlush(g_file);
   return GetLastError() == 0;
}
bool OpenJournal()
{
   g_file = FileOpen(g_filename, FILE_READ|FILE_WRITE|FILE_BIN);
   if(g_file == INVALID_HANDLE) return false; // Exclusive lock: no FILE_SHARE_*.
   ulong size = FileSize(g_file);
   if(size == 0) return WriteBytes(CsvHeader()+"\r\n");
   if(size > MAX_CSV_BYTES) return false;
   uchar bytes[];
   if(ArrayResize(bytes, (int)size) != (int)size ||
      FileReadArray(g_file, bytes, 0, (int)size) != (uint)size) return false;
   if(size < 2 || bytes[(int)size-2] != 13 || bytes[(int)size-1] != 10) return false;
   string lines[];
   string all = CharArrayToString(bytes, 0, (int)size, CP_UTF8);
   int count = StringSplit(all, '\n', lines);
   if(count < 2 || lines[count-1] != "" || lines[0] != CsvHeader()+"\r") return false;
   Engine restored;
   ResetEngine(restored, 0, 0);
   for(int i = 1; i < count-1; i++)
   {
      int length = StringLen(lines[i]);
      if(length < 2 || StringGetCharacter(lines[i], length-1) != 13) return false;
      Engine next;
      if(!RestoreRow(StringSubstr(lines[i], 0, length-1), g_identity, next) ||
         next.last <= restored.last || next.index != restored.index + 1) return false;
      restored = next;
   }
   g_engine = restored;
   return FileSeek(g_file, 0, SEEK_END);
}
bool CommitFrame(const Frame &frame, const Engine &next, const Verdict &out[])
{
   string row = MakeRow(g_identity, frame, next, out);
   if(FileSize(g_file) + (ulong)StringLen(row) + 2 > MAX_CSV_BYTES) return false;
   if(!WriteBytes(row+"\r\n")) return false;
   g_engine = next;
   return true;
}

// ----- Deterministic fixtures exercise this same core, without market data. -----
void Check(const string name, const bool passed)
{
   if(passed) g_passed++; else g_failed++;
   Print("[Scanner test] ", passed ? "PASS " : "FAIL ", name);
}
void Fixture(Frame &frame, const bool buy)
{
   ZeroMemory(frame);
   frame.error = ""; // ZeroMemory leaves MQL5 strings NULL, not an allocated empty string.
   frame.decision = D'2026.09.17 14:00';
   frame.observed = frame.decision + 1;
   frame.session = 1;
   frame.gate = buy ? 1 : -1;
   frame.h1_open = frame.decision - 3600;
   frame.ema = 100; frame.h1_close = buy ? 101 : 99;
   frame.bid = 104; frame.ask = 104.1; frame.spread = 10;
   ArrayResize(frame.bars, 4);
   for(int i = 0; i < 4; i++)
   {
      double close = i < 3 ? 103-i : 104;
      if(!buy) close = 200-close;
      frame.bars[i].time = frame.decision - (4-i)*300;
      frame.bars[i].open = close;
      frame.bars[i].close = close;
      frame.bars[i].high = close + 0.25;
      frame.bars[i].low = close - 0.25;
   }
}
void ReadyFixture(Engine &state, const Frame &frame)
{
   ResetEngine(state, frame.decision-300, 10);
   state.ready = true; state.gate = frame.gate;
   for(int i = 2; i < 4; i++)
   {
      state.lanes[i].length = 3;
      state.lanes[i].start = frame.decision - 1200;
      state.lanes[i].start_index = 8;
   }
}
void ShiftFixture(Frame &frame)
{
   frame.decision += 300; frame.observed += 300;
   for(int i = 0; i < ArraySize(frame.bars); i++) frame.bars[i].time += 300;
}
// Replay only the supplied closed prefix; suffix prices are never passed to Evaluate.
bool ReplayFixture(const double &closes[], const int count, const int restart_at, string &rows[])
{
   if(count < 4 || count > ArraySize(closes)) return false;
   ArrayResize(rows, count-3);
   Engine state;
   ResetEngine(state, 0, 0);
   for(int t = 3; t < count; t++)
   {
      Frame frame;
      Fixture(frame, true);
      frame.decision += (t-3)*300;
      frame.observed = frame.decision+1;
      frame.h1_open = (datetime)(((long)frame.decision/3600)*3600-3600);
      for(int j = 0; j < 4; j++)
      {
         frame.bars[j].time = frame.decision-(4-j)*300;
         frame.bars[j].open = closes[t-3+j];
         frame.bars[j].close = closes[t-3+j];
         frame.bars[j].high = closes[t-3+j]+0.25;
         frame.bars[j].low = closes[t-3+j]-0.25;
      }
      Verdict out[];
      if(!IsNewDecision(frame.decision, state.last)) return false;
      Evaluate(frame, state, out, 3, 3, 2);
      rows[t-3] = MakeRow("replay", frame, state, out);
      if(t == restart_at)
      {
         Engine recovered;
         if(!RestoreRow(rows[t-3], "replay", recovered) || IsNewDecision(frame.decision, recovered.last)) return false;
         state = recovered;
      }
   }
   return true;
}
// Synthetic I/O fixtures only. Unique files are owned and removed by this test.
void JournalSelfTests()
{
   string saved_filename = g_filename, saved_identity = g_identity;
   Engine saved_engine = g_engine;
   string stem = "ScannerSelfTest_"+I((long)TimeLocal())+"_"+I((long)GetTickCount64());
   string normal = stem+".csv", broken = stem+"_truncated.csv";
   if(g_file != INVALID_HANDLE || FileIsExist(normal) || FileIsExist(broken))
   {
      Check("Journal fixture isolated filenames", false);
      return;
   }
   g_filename = normal; g_identity = "journal-fixture";
   ResetEngine(g_engine, 0, 0);
   bool opened = OpenJournal();
   Check("Journal create/header", opened);
   if(opened)
   {
      int other = FileOpen(normal, FILE_READ|FILE_WRITE|FILE_BIN);
      Check("Journal exclusive writer", other == INVALID_HANDLE);
      if(other != INVALID_HANDLE) FileClose(other);
      Frame frame; Fixture(frame, true);
      Engine next = g_engine; Verdict out[];
      Evaluate(frame, next, out, 3, 3, 2);
      bool committed = CommitFrame(frame, next, out);
      Check("Journal commit", committed && StateText(g_engine) == StateText(next));
      FileClose(g_file); g_file = INVALID_HANDLE;
      ResetEngine(g_engine, 0, 0);
      bool reopened = OpenJournal();
      Check("Journal reopen restores checkpoint", reopened && StateText(g_engine) == StateText(next) &&
            !IsNewDecision(frame.decision, g_engine.last));
      if(reopened)
      {
         ShiftFixture(frame);
         next = g_engine;
         Evaluate(frame, next, out, 3, 3, 2);
         bool written = WriteBytes(MakeRow(g_identity, frame, next, out)+"\r\n");
         FileClose(g_file); g_file = INVALID_HANDLE;
         bool crash_reopen = OpenJournal();
         Check("Complete row before RAM update survives restart", written && crash_reopen && StateText(g_engine) == StateText(next));
      }
      if(g_file != INVALID_HANDLE) FileClose(g_file);
      g_file = INVALID_HANDLE;
      g_filename = broken;
      g_file = FileOpen(broken, FILE_READ|FILE_WRITE|FILE_BIN);
      bool truncated = g_file != INVALID_HANDLE && WriteBytes(CsvHeader()+"\r\n"+MakeRow(g_identity, frame, next, out));
      if(g_file != INVALID_HANDLE) FileClose(g_file);
      g_file = INVALID_HANDLE;
      Check("Truncated disk row fails closed", truncated && !OpenJournal());
   }
   if(g_file != INVALID_HANDLE) FileClose(g_file);
   g_file = INVALID_HANDLE;
   if(FileIsExist(normal)) FileDelete(normal);
   if(FileIsExist(broken)) FileDelete(broken);
   g_filename = saved_filename; g_identity = saved_identity; g_engine = saved_engine;
}
bool RunSelfTests()
{
   g_passed = 0; g_failed = 0;
   Frame frame;
   Engine state;
   Verdict out[];
   Fixture(frame, true); ReadyFixture(state, frame);
   Evaluate(frame, state, out, 3, 3, 2);
   Check("PB1 BUY", out[2].reason == "ACCEPT_DIAGNOSTIC");
   Check("B0 BUY", out[0].reason == "ACCEPT_DIAGNOSTIC");
   Fixture(frame, false); ReadyFixture(state, frame);
   Evaluate(frame, state, out, 3, 3, 2);
   Check("PB1 SELL", out[3].reason == "ACCEPT_DIAGNOSTIC");
   Check("B0 SELL", out[1].reason == "ACCEPT_DIAGNOSTIC");

   Fixture(frame, true); ReadyFixture(state, frame);
   frame.bars[3].close = frame.bars[2].high;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("PB1 equality", !out[2].raw && out[2].reason == "EQUALITY");
   Fixture(frame, true); ReadyFixture(state, frame);
   frame.bars[3].close = frame.bars[0].high;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("B0 equality", !out[0].raw && out[0].reason == "EQUALITY");
   Fixture(frame, true); ReadyFixture(state, frame);
   frame.bars[1].close = frame.bars[0].close;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Equal setup closes", out[2].reason == "NO_SETUP");

   Fixture(frame, true); ReadyFixture(state, frame);
   frame.gate = 0; state.gate = 0;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Neutral H1", out[0].reason == "H1_NEUTRAL" && out[2].reason == "H1_NEUTRAL");
   Check("Reject open H1", !ClosedH1(frame.decision, frame.decision+300));
   Check("Closed H1 at boundary", ClosedH1(frame.decision-3600, frame.decision));
   Check("Reject stale H1", !ClosedH1(frame.decision-7200, frame.decision));
   Fixture(frame, true); ReadyFixture(state, frame);
   state.gate = -1;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("H1 change invalidates PB1", out[2].reason == "H1_CHANGED" && state.lanes[2].length == 1);

   Fixture(frame, true); ReadyFixture(state, frame);
   state.lanes[2].length = 7; state.lanes[2].start_index = 4;
   state.lanes[2].start = frame.decision - 2400;
   datetime episode = state.lanes[2].start;
   frame.bars[3].close = 100; // Extend the descending episode before a later trigger.
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Extended pullback preserves episode", state.lanes[2].length == 8 && state.lanes[2].start == episode);
   ShiftFixture(frame); frame.bars[3].close = 104;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Extended pullback trigger", out[2].reason == "ACCEPT_DIAGNOSTIC" && out[2].episode == episode);

   Fixture(frame, true); ReadyFixture(state, frame);
   Evaluate(frame, state, out, 3, 3, 2);
   ShiftFixture(frame);
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Consumed B0 episode", out[0].reason == "EPISODE_CONSUMED");
   Fixture(frame, true); ReadyFixture(state, frame);
   state.lanes[2].cooldown_until = 11;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Active cooldown", out[2].reason == "COOLDOWN");
   Fixture(frame, true); ReadyFixture(state, frame);
   state.lanes[2].cooldown_until = 8;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Fresh sequence after cooldown", out[2].reason == "FRESH_SEQUENCE_REQUIRED");

   Fixture(frame, true); ReadyFixture(state, frame); frame.session = 0;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Outside session logged and consumed", out[2].raw && out[2].reason == "OUTSIDE_SESSION" && state.lanes[2].cooldown_until == 13);
   Fixture(frame, true); ReadyFixture(state, frame); frame.session = -1;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Unknown session", out[0].reason == "SESSION_UNKNOWN");
   Fixture(frame, true); ReadyFixture(state, frame); frame.error = "DATA_EMA";
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Indicator failure", !state.ready && out[0].reason == "DATA_EMA");
   Fixture(frame, true); ReadyFixture(state, frame); ArrayResize(frame.bars, 2);
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Insufficient data", !state.ready && out[2].reason == "DATA_M5");
   Fixture(frame, true); ReadyFixture(state, frame); state.last -= 300;
   Evaluate(frame, state, out, 3, 3, 2);
   Check("Gap resets state", out[0].reason == "GAP_RESET" && state.lanes[2].length == 1);

   Fixture(frame, true); ReadyFixture(state, frame);
   Evaluate(frame, state, out, 3, 3, 2);
   string row = MakeRow("fixture", frame, state, out);
   Engine restored;
   Check("CSV checkpoint roundtrip", RestoreRow(row, "fixture", restored) && StateText(restored) == StateText(state));
   Check("Restart no duplicate", !IsNewDecision(frame.decision, restored.last));
   Check("Multiple ticks same M5", !IsNewDecision(frame.decision, state.last) && IsNewDecision(frame.decision+300, state.last));
   Check("Corruption rejected", !RestoreRow(row+"X", "fixture", restored));
   Check("Wrong identity rejected", !RestoreRow(row, "another_run", restored));
   string past = row;
   ShiftFixture(frame); Evaluate(frame, state, out, 3, 3, 2);
   Frame old_frame; Engine old_state; Verdict old_out[];
   Fixture(old_frame, true); ReadyFixture(old_state, old_frame);
   Evaluate(old_frame, old_state, old_out, 3, 3, 2);
   Check("Future data does not change past", MakeRow("fixture", old_frame, old_state, old_out) == past);
   Engine visual_m1, visual_h4; Verdict out_m1[], out_h4[];
   ReadyFixture(visual_m1, old_frame); ReadyFixture(visual_h4, old_frame);
   Evaluate(old_frame, visual_m1, out_m1, 3, 3, 2);
   Evaluate(old_frame, visual_h4, out_h4, 3, 3, 2);
   Check("Visual timeframe absent from core/key", MakeRow("fixture", old_frame, visual_m1, out_m1) == MakeRow("fixture", old_frame, visual_h4, out_h4));

   double prices[] = {100,103,102,101,104,108,107,106,105,109,108,107,106,110,109,108,107,111};
   string prefix_rows[], full_rows[], resumed_rows[];
   bool prefix_ok = ReplayFixture(prices, 10, -1, prefix_rows);
   bool full_ok = ReplayFixture(prices, ArraySize(prices), -1, full_rows);
   bool resume_ok = ReplayFixture(prices, ArraySize(prices), 7, resumed_rows);
   bool same_prefix = prefix_ok && full_ok;
   for(int i = 0; i < ArraySize(prefix_rows) && same_prefix; i++)
      same_prefix = prefix_rows[i] == full_rows[i];
   Check("Chronological prefix versus added future", same_prefix);
   bool same_restart = resume_ok && full_ok;
   for(int i = 0; i < ArraySize(full_rows) && same_restart; i++)
      same_restart = full_rows[i] == resumed_rows[i];
   Check("Full stream versus checkpoint restart", same_restart);
   bool has_signal = false;
   for(int i = 0; i < ArraySize(full_rows); i++)
      if(StringFind(full_rows[i], "ACCEPT_DIAGNOSTIC") >= 0) has_signal = true;
   Check("Replay includes accepted signals", has_signal);
   datetime ny; int offset;
   Check("NY spring before", NewYorkTime(D'2026.03.08 06:59', ny, offset) && offset == -300);
   Check("NY spring boundary", NewYorkTime(D'2026.03.08 07:00', ny, offset) && offset == -240);
   Check("NY fall before", NewYorkTime(D'2026.11.01 05:59', ny, offset) && offset == -240);
   Check("NY fall boundary", NewYorkTime(D'2026.11.01 06:00', ny, offset) && offset == -300);
   Check("Session 08 included", SessionAt(D'2026.09.17 08:00', 8, 12) == 1);
   Check("Session 12 excluded", SessionAt(D'2026.09.17 12:00', 8, 12) == 0);
   OffsetInterval offsets[]; datetime utc; int server_offset;
   Check("Empty broker schedule", ParseSchedule("", offsets) && !ServerToUtc(D'2026.09.17 14:00', offsets, utc, server_offset));
   Check("Valid schedule", ParseSchedule("2026.01.01 00:00|2027.01.01 00:00|120", offsets) && ServerToUtc(D'2026.09.17 14:00', offsets, utc, server_offset) && utc == D'2026.09.17 12:00');
   Check("Ambiguous server hour", ParseSchedule("2026.01.01 00:00|2026.11.01 06:00|120;2026.11.01 06:00|2027.01.01 00:00|60", offsets) && !ServerToUtc(D'2026.11.01 07:30', offsets, utc, server_offset));
   Check("Overlapping UTC schedule rejected", !ParseSchedule("2026.01.01 00:00|2027.01.01 00:00|120;2026.06.01 00:00|2027.01.01 00:00|60", offsets));
   JournalSelfTests();
   PrintFormat("[Scanner] SELFTEST: %d passed; %d failed", g_passed, g_failed);
   return g_failed == 0;
}

// ----- EA lifecycle. -----
int OnInit()
{
   ResetEngine(g_engine, 0, 0);
   if(SelfTestOnly) return RunSelfTests() ? INIT_SUCCEEDED : INIT_FAILED;
   if(EMA_H1_Period < 2 || EMA_H1_Period > 200 || PullbackBars < 2 || PullbackBars > 20 ||
      BreakoutLookback < 1 || BreakoutLookback > 100 || CooldownBars < 0 || CooldownBars > 100 ||
      NYStartHour < 0 || NYEndHour > 24 || NYStartHour >= NYEndHour ||
      !ParseSchedule(BrokerUtcSchedule, g_offsets))
   {
      Print("[Scanner] Invalid parameters or broker UTC schedule.");
      return INIT_PARAMETERS_INCORRECT;
   }
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(MQLInfoInteger(MQL_OPTIMIZATION) ||
      (!tester && AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO))
   {
      Print("[Scanner] Use a demo account or a single diagnostic tester run.");
      return INIT_FAILED;
   }
   string run = RunId;
   if(!tester && run == "") run = "demo";
   if(!SafeId(run))
   {
      Print("[Scanner] RunId: 1-64 ASCII letters/digits/_/-. Required in tester.");
      return INIT_PARAMETERS_INCORRECT;
   }
   g_identity = SCHEMA+"|"+HexText(AccountInfoString(ACCOUNT_SERVER))+"|"+
                I(AccountInfoInteger(ACCOUNT_LOGIN))+"|"+HexText(_Symbol)+"|"+
                StringFormat("%I64u", MagicNumber)+"|"+(tester ? "tester" : "demo")+"|"+run+"|"+
                I(EMA_H1_Period)+"|"+I(PullbackBars)+"|"+I(BreakoutLookback)+"|"+I(CooldownBars)+"|"+
                I(NYStartHour)+"|"+I(NYEndHour)+"|"+HexText(BrokerUtcSchedule);
   g_filename = "XAUUSD_Scanner_"+Hash(g_identity)+Hash(g_identity, 2246822519)+".csv";
   if(!OpenJournal())
   {
      Print("[Scanner] Journal unavailable, locked, incompatible or corrupt: ", g_filename,
            ". Preserve it for inspection. Error=", GetLastError());
      return INIT_FAILED;
   }
   g_ema = iMA(_Symbol, PERIOD_H1, EMA_H1_Period, 0, MODE_EMA, PRICE_CLOSE);
   if(g_ema == INVALID_HANDLE)
   {
      Print("[Scanner] Cannot create H1 EMA. Error=", GetLastError());
      return INIT_FAILED;
   }
   if(StringFind(_Symbol, "XAUUSD") < 0)
      Print("[Scanner] WARNING: symbol name does not contain XAUUSD: ", _Symbol);
   Print("[Scanner] Diagnostic only. CSV=", g_filename, " watermark=", I(g_engine.last),
         " terminal=", TerminalInfoString(TERMINAL_DATA_PATH));
   if(ArraySize(g_offsets) == 0)
      Print("[Scanner] Broker UTC calendar missing: session will be UNKNOWN.");
   return INIT_SUCCEEDED;
}
void OnTick()
{
   if(SelfTestOnly || g_halted) return;
   datetime decision = iTime(_Symbol, PERIOD_M5, 0);
   if(decision <= 0)
   {
      long bucket = (long)TimeCurrent()/300;
      if(bucket != g_warning_bucket)
      {
         Print("[Scanner] M5 timestamp unavailable; waiting for data.");
         g_warning_bucket = bucket;
      }
      return;
   }
   if(decision < g_engine.last)
   {
      Halt("M5 time moved backwards; preserve journal and inspect history/RunId.");
      return;
   }
   if(!IsNewDecision(decision, g_engine.last)) return;
   Frame frame;
   ReadFrame(decision, frame);
   Engine next = g_engine;
   Verdict out[];
   Evaluate(frame, next, out, PullbackBars, BreakoutLookback, CooldownBars);
   if(!CommitFrame(frame, next, out))
   {
      Halt("CSV write/flush failed or size limit reached; no further processing.");
      return;
   }
   PrintFormat("[Scanner] %s H1=%d session=%d B0=%s/%s PB1=%s/%s",
               TimeToString(decision, TIME_DATE|TIME_MINUTES), frame.gate, frame.session,
               out[0].reason, out[1].reason, out[2].reason, out[3].reason);
}
void OnDeinit(const int reason)
{
   if(g_ema != INVALID_HANDLE) IndicatorRelease(g_ema);
   if(g_file != INVALID_HANDLE) FileClose(g_file);
   PrintFormat("[Scanner] Deinit reason=%d watermark=%I64d", reason, (long)g_engine.last);
}
