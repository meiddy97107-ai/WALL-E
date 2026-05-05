#property strict
#property version   "1.00"
#property description "Structure Trap real-order execution + chart visualization."
#include <Trade/Trade.mqh>

enum ContextMode
{
   CONTEXT_AUTO = 0,
   CONTEXT_ASIAN_BOX = 1,
   CONTEXT_BOLLINGER = 2,
   CONTEXT_ORB = 3
};

input ContextMode InpContextMode = CONTEXT_AUTO;
input bool   InpShowObjects = true;

CTrade g_trade;

string ETAT_ATTENTE_H1 = "ATTENTE_H1";
string ETAT_ATTENTE_L1 = "ATTENTE_L1";
string ETAT_ATTENTE_H2 = "ATTENTE_H2";
string ETAT_ATTENTE_L2 = "ATTENTE_L2";
string ETAT_DECISION   = "DECISION";

datetime g_last_m1_bar = 0;
int g_cooldown = 0;
int g_traded_day_key = -1;

string g_etat = "";
string g_cassure = "";
string g_breakout_initial = "";
int g_compteur = 0;
double g_h1 = 0.0, g_l1 = 0.0, g_h2 = 0.0, g_l2 = 0.0;

int g_asian_day_key = -1;
double g_asian_high = 0.0;
double g_asian_low = 0.0;
bool g_asian_ready = false;

int g_total_signals = 0;
int g_total_trades = 0;
double g_daily_snapshot_balance = 0.0;
int g_daily_snapshot_day = -1;
double g_last_reference_mid = 0.0;
int g_consecutive_losses = 0;
bool g_kill_switch = false;

bool g_pulse_active = false;
ulong g_pulse_ticket = 0;
string g_pulse_direction = "";
double g_pulse_entry = 0.0;
double g_pulse_sl = 0.0;
string g_pulse_state = "SHIELD";
int g_pulse_rocket_counter = 0;
string g_pulse_conviction = "STANDARD";

double GetFixedLotBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 0.30;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 0.30;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 0.02;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 0.01;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 1.00;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 3.00;
   if(_Symbol == "US30"  || _Symbol == "DJ30.") return 1.00;
   return 0.01;
}

double GetPointValueBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 10.0;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 10.0;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 10.0;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 50.0;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 2.0;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 5.0;
   if(_Symbol == "US30" || _Symbol == "DJ30.") return 1.0;
   return 10.0;
}

double GetPricePerPointBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 0.0001;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 0.0001;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 0.01;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 0.001;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 0.01;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 0.1;
   if(_Symbol == "US30" || _Symbol == "DJ30.") return 1.0;
   return _Point;
}

double GetRiskFractionByPhase(const double balance)
{
   // Mirror phase_config.py / phase_detector.py
   const double challenge_start = 2492.0;
   const double p1_max = challenge_start * 1.08;
   const double p2_max = challenge_start * (1.08 * 1.05);
   if(balance < p1_max) return 0.50;
   if(balance < p2_max) return 0.45;
   return 0.33;
}

void UpdateDailySnapshot(const datetime t)
{
   int day_key = DayKey(t);
   if(g_daily_snapshot_day != day_key)
   {
      g_daily_snapshot_day = day_key;
      g_daily_snapshot_balance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_consecutive_losses = 0;
      g_kill_switch = false;
   }
}

double ComputeRiskEur(const datetime t)
{
   UpdateDailySnapshot(t);
   double snapshot = g_daily_snapshot_balance;
   if(snapshot <= 0.0) snapshot = AccountInfoDouble(ACCOUNT_BALANCE);
   double daily_budget = snapshot * 0.04;
   double frac = GetRiskFractionByPhase(AccountInfoDouble(ACCOUNT_BALANCE));
   return daily_budget * frac;
}

int TimeToMinutes(const string hhmm)
{
   if(StringLen(hhmm) < 5) return -1;
   int h = (int)StringToInteger(StringSubstr(hhmm, 0, 2));
   int m = (int)StringToInteger(StringSubstr(hhmm, 3, 2));
   return h * 60 + m;
}

int DayKey(const datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return dt.year * 10000 + dt.mon * 100 + dt.day;
}

bool IsBetweenHHMM(const datetime t, const string start_hhmm, const string end_hhmm)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   int cur = dt.hour * 60 + dt.min;
   int st = TimeToMinutes(start_hhmm);
   int en = TimeToMinutes(end_hhmm);
   if(st < 0 || en < 0) return false;
   if(st <= en) return (cur >= st && cur <= en);
   return (cur >= st || cur <= en);
}

string GetAsianStart() { return "02:00"; }
string GetAsianEnd() { return "08:00"; }
string GetSignalCutoff() { return "11:30"; }
string GetOrbStart() { return "15:30"; }
string GetOrbEnd() { return "16:00"; }
string GetSessionStart() { return "16:00"; }
string GetSessionEnd() { return "21:45"; }
int GetTimeoutH2BySymbol() { return 20; }
int GetCooldownBars() { return 30; }

double GetAtrFilterBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 1.8;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 2.0;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 2.0;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 2.5;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 2.5;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 1.5;
   if(_Symbol == "US30" || _Symbol == "DJ30.") return 2.0;
   return 1.8;
}

double GetSLBufferBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 1.0;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 1.2;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 1.5;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 2.0;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 1.0;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 1.0;
   if(_Symbol == "US30" || _Symbol == "DJ30.") return 1.0;
   return 1.0;
}

double GetBEThresholdBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 1.5;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 2.0;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 1.5;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 2.0;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 2.0;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 1.5;
   if(_Symbol == "US30" || _Symbol == "DJ30.") return 1.8;
   return 1.5;
}

double GetRocketAtrMultBySymbol() { return 1.8; }
int GetEmaFastBySymbol() { return 5; }
int GetEmaSlowBySymbol()
{
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP" || _Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 13;
   return 8;
}
double GetSlopeThresholdBySymbol()
{
   if(_Symbol == "EURUSD" || _Symbol == "EURUSD-VIP") return 0.00008;
   if(_Symbol == "GBPUSD" || _Symbol == "GBPUSD-VIP") return 0.00010;
   if(_Symbol == "XAUUSD" || _Symbol == "XAUUSD-VIP") return 0.40;
   if(_Symbol == "XAGUSD" || _Symbol == "XAGUSD-VIP") return 0.05;
   if(_Symbol == "US100" || _Symbol == "NAS100.") return 2.5;
   if(_Symbol == "US500" || _Symbol == "SP500.") return 0.25;
   if(_Symbol == "US30" || _Symbol == "DJ30.") return 1.5;
   return 0.00008;
}

void ResetPulse()
{
   g_pulse_active = false;
   g_pulse_ticket = 0;
   g_pulse_direction = "";
   g_pulse_entry = 0.0;
   g_pulse_sl = 0.0;
   g_pulse_state = "SHIELD";
   g_pulse_rocket_counter = 0;
}

string ResolveContext()
{
   if(InpContextMode == CONTEXT_ASIAN_BOX) return "asian_box";
   if(InpContextMode == CONTEXT_BOLLINGER) return "bollinger";
   if(InpContextMode == CONTEXT_ORB) return "orb";

   if(_Symbol == "EURUSD" || _Symbol == "GBPUSD" || _Symbol == "EURUSD-VIP" || _Symbol == "GBPUSD-VIP")
      return "asian_box";
   if(_Symbol == "US100" || _Symbol == "US500" || _Symbol == "US30" || _Symbol == "NAS100." || _Symbol == "SP500." || _Symbol == "DJ30.")
      return "orb";
   return "bollinger";
}

void ResetState()
{
   g_etat = "";
   g_cassure = "";
   g_breakout_initial = "";
   g_compteur = 0;
   g_h1 = 0.0; g_l1 = 0.0; g_h2 = 0.0; g_l2 = 0.0;
}

double MinLowFrom(const MqlRates &arr[], int from_idx, int size)
{
   double v = arr[from_idx].low;
   for(int j = from_idx; j < size; j++) v = MathMin(v, arr[j].low);
   return v;
}

double MaxHighFrom(const MqlRates &arr[], int from_idx, int size)
{
   double v = arr[from_idx].high;
   for(int j = from_idx; j < size; j++) v = MathMax(v, arr[j].high);
   return v;
}

bool GetLastValidatedHigh(const MqlRates &arr[], int size, double seuil, double &out_high)
{
   if(size < 5) return false;
   for(int i = size - 2; i >= 2; i--)
   {
      if(arr[i].high > arr[i - 1].high && arr[i].high > arr[i + 1].high)
      {
         double low_after = MinLowFrom(arr, i, size);
         if(arr[i].high - low_after >= seuil)
         {
            out_high = arr[i].high;
            return true;
         }
      }
   }
   return false;
}

bool GetLastValidatedLow(const MqlRates &arr[], int size, double seuil, double &out_low)
{
   if(size < 5) return false;
   for(int i = size - 2; i >= 2; i--)
   {
      if(arr[i].low < arr[i - 1].low && arr[i].low < arr[i + 1].low)
      {
         double high_after = MaxHighFrom(arr, i, size);
         if(high_after - arr[i].low >= seuil)
         {
            out_low = arr[i].low;
            return true;
         }
      }
   }
   return false;
}

bool ComputeAsianContext(const datetime bar_time, string &breakout_dir, double &mid_ref)
{
   MqlRates m15[300];
   int n = CopyRates(_Symbol, PERIOD_M15, 0, 300, m15);
   if(n <= 0) return false;
   ArraySetAsSeries(m15, false);

   int today_key = DayKey(bar_time);
   if(g_asian_day_key != today_key)
   {
      g_asian_day_key = today_key;
      g_asian_ready = false;
      g_asian_high = 0.0;
      g_asian_low = 0.0;
   }

   if(!g_asian_ready)
   {
      double hi = -DBL_MAX, lo = DBL_MAX;
      bool found = false;
      for(int i = 0; i < n; i++)
      {
         if(DayKey(m15[i].time) != today_key) continue;
         if(!IsBetweenHHMM(m15[i].time, GetAsianStart(), GetAsianEnd())) continue;
         found = true;
         hi = MathMax(hi, m15[i].high);
         lo = MathMin(lo, m15[i].low);
      }
      if(!found) return false;
      g_asian_high = hi;
      g_asian_low = lo;
      g_asian_ready = true;
   }

   if(!IsBetweenHHMM(bar_time, GetAsianStart(), GetSignalCutoff())) return false;

   double close_m15 = m15[n - 1].close;
   if(close_m15 > g_asian_high) breakout_dir = "HAUT";
   else if(close_m15 < g_asian_low) breakout_dir = "BAS";
   else return false;

   mid_ref = (g_asian_high + g_asian_low) * 0.5;
   return true;
}

bool ComputeBollingerContext(string &breakout_dir, double &mid_ref)
{
   int h = iBands(_Symbol, PERIOD_M15, 20, 0, 2.0, PRICE_CLOSE);
   if(h == INVALID_HANDLE) return false;

   double up[2], mid[2], low[2];
   if(CopyBuffer(h, 1, 0, 2, up) < 2 || CopyBuffer(h, 0, 0, 2, mid) < 2 || CopyBuffer(h, 2, 0, 2, low) < 2)
   {
      IndicatorRelease(h);
      return false;
   }

   MqlRates m15[3];
   int n = CopyRates(_Symbol, PERIOD_M15, 0, 3, m15);
   IndicatorRelease(h);
   if(n < 2) return false;
   ArraySetAsSeries(m15, true);
   double last_close = m15[1].close;
   double last_open = m15[1].open;

   if(last_close > up[1] && last_close > last_open) breakout_dir = "HAUT";
   else if(last_close < low[1] && last_close < last_open) breakout_dir = "BAS";
   else return false;

   mid_ref = mid[1];
   return true;
}

bool ComputeOrbContext(const datetime bar_time, string &breakout_dir, double &mid_ref)
{
   if(!IsBetweenHHMM(bar_time, GetSessionStart(), GetSessionEnd())) return false;

   MqlRates m15[200];
   int n = CopyRates(_Symbol, PERIOD_M15, 0, 200, m15);
   if(n <= 0) return false;
   ArraySetAsSeries(m15, false);

   int day_key = DayKey(bar_time);
   double orb_hi = -DBL_MAX, orb_lo = DBL_MAX;
   bool found = false;
   for(int i = 0; i < n; i++)
   {
      if(DayKey(m15[i].time) != day_key) continue;
      if(!IsBetweenHHMM(m15[i].time, GetOrbStart(), GetOrbEnd())) continue;
      found = true;
      orb_hi = MathMax(orb_hi, m15[i].high);
      orb_lo = MathMin(orb_lo, m15[i].low);
   }
   if(!found) return false;

   double close_m15 = m15[n - 1].close;
   if(close_m15 > orb_hi) breakout_dir = "HAUT";
   else if(close_m15 < orb_lo) breakout_dir = "BAS";
   else return false;

   mid_ref = (orb_hi + orb_lo) * 0.5;
   return true;
}

bool BuildContext(const datetime bar_time, string &breakout_dir, double &mid_ref)
{
   string ctx = ResolveContext();
   if(ctx == "asian_box") return ComputeAsianContext(bar_time, breakout_dir, mid_ref);
   if(ctx == "orb") return ComputeOrbContext(bar_time, breakout_dir, mid_ref);
   return ComputeBollingerContext(breakout_dir, mid_ref);
}

string RunStateMachine(const string breakout_dir, const MqlRates &m1[], int n, double atr_m1)
{
   if(g_etat == "")
   {
      if(breakout_dir == "HAUT")
      {
         g_etat = ETAT_ATTENTE_H1;
         g_cassure = "HAUT";
         g_breakout_initial = "HAUT";
      }
      else
      {
         g_etat = ETAT_ATTENTE_L1;
         g_cassure = "BAS";
         g_breakout_initial = "BAS";
      }
      g_compteur = 0;
   }

   if(g_breakout_initial != breakout_dir)
   {
      ResetState();
      return "";
   }

   g_compteur++;
   if(g_compteur > GetTimeoutH2BySymbol())
   {
      ResetState();
      return "";
   }

   double seuil = GetAtrFilterBySymbol() * atr_m1;
   double tmp = 0.0;

   if(g_cassure == "HAUT")
   {
      if(g_etat == ETAT_ATTENTE_H1)
      {
         if(GetLastValidatedHigh(m1, n, seuil, tmp)) { g_h1 = tmp; g_etat = ETAT_ATTENTE_L1; }
         return "";
      }
      if(g_etat == ETAT_ATTENTE_L1)
      {
         if(GetLastValidatedLow(m1, n, seuil, tmp)) { g_l1 = tmp; g_etat = ETAT_ATTENTE_H2; g_compteur = 0; }
         return "";
      }
      if(g_etat == ETAT_ATTENTE_H2)
      {
         if(GetLastValidatedHigh(m1, n, seuil, tmp)) { g_h2 = tmp; g_etat = ETAT_DECISION; }
         return "";
      }
      if(g_etat == ETAT_DECISION)
      {
         if(g_h2 <= 0.0 || g_h1 <= 0.0) { ResetState(); return ""; }
         if(g_h2 < g_h1) return "SWEEP_SELL";
         if(g_h2 > g_h1) return "CONTINUATION_BUY";
         ResetState();
         return "";
      }
   }
   else
   {
      if(g_etat == ETAT_ATTENTE_L1)
      {
         if(GetLastValidatedLow(m1, n, seuil, tmp)) { g_l1 = tmp; g_etat = ETAT_ATTENTE_H1; }
         return "";
      }
      if(g_etat == ETAT_ATTENTE_H1)
      {
         if(GetLastValidatedHigh(m1, n, seuil, tmp)) { g_h1 = tmp; g_etat = ETAT_ATTENTE_L2; g_compteur = 0; }
         return "";
      }
      if(g_etat == ETAT_ATTENTE_L2)
      {
         if(GetLastValidatedLow(m1, n, seuil, tmp)) { g_l2 = tmp; g_etat = ETAT_DECISION; }
         return "";
      }
      if(g_etat == ETAT_DECISION)
      {
         if(g_l2 <= 0.0 || g_l1 <= 0.0) { ResetState(); return ""; }
         if(g_l2 > g_l1) return "SWEEP_BUY";
         if(g_l2 < g_l1) return "CONTINUATION_SELL";
         ResetState();
         return "";
      }
   }
   return "";
}

void PlotSignal(const datetime t, const double price, const string scenario, const string direction)
{
   if(!InpShowObjects) return;
   string name = StringFormat("ST_%s_%I64d", scenario, (long)t);
   if(ObjectFind(0, name) >= 0) return;

   int code = (direction == "BUY") ? 241 : 242;
   color c = (direction == "BUY") ? clrLime : clrTomato;
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, code);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);

   string txt = name + "_TXT";
   ObjectCreate(0, txt, OBJ_TEXT, 0, t, price);
   ObjectSetString(0, txt, OBJPROP_TEXT, scenario);
   ObjectSetInteger(0, txt, OBJPROP_COLOR, c);
   ObjectSetInteger(0, txt, OBJPROP_FONTSIZE, 8);
}

void DrawTradeLevels(const datetime t, const string tag, const double entry, const double sl, const string direction)
{
   if(!InpShowObjects) return;
   color dir_color = (direction == "BUY") ? clrLime : clrTomato;

   string e_name = "ST_TRD_" + tag + "_ENTRY";
   string s_name = "ST_TRD_" + tag + "_SL";

   ObjectCreate(0, e_name, OBJ_HLINE, 0, t, entry);
   ObjectSetInteger(0, e_name, OBJPROP_COLOR, clrAqua);
   ObjectSetInteger(0, e_name, OBJPROP_STYLE, STYLE_DOT);

   ObjectCreate(0, s_name, OBJ_HLINE, 0, t, sl);
   ObjectSetInteger(0, s_name, OBJPROP_COLOR, clrOrangeRed);
   ObjectSetInteger(0, s_name, OBJPROP_STYLE, STYLE_SOLID);

   string lbl = "ST_TRD_" + tag + "_LBL";
   ObjectCreate(0, lbl, OBJ_TEXT, 0, t, entry);
   ObjectSetString(0, lbl, OBJPROP_TEXT, "TRADE " + direction);
   ObjectSetInteger(0, lbl, OBJPROP_COLOR, dir_color);
   ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE, 8);
}

bool HasOpenPositionOnSymbol()
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      if(sym == _Symbol) return true;
   }
   return false;
}

bool OpenTrade(const string direction, const datetime m1_time, const double entry, const int today_key)
{
   double lot_size = GetFixedLotBySymbol();
   double point_value = GetPointValueBySymbol();
   double price_per_point = GetPricePerPointBySymbol();
   double risk_eur = ComputeRiskEur(m1_time);
   double sl_distance = (risk_eur * price_per_point) / (lot_size * point_value);

   double sl = 0.0;

   if(direction == "BUY")
   {
      sl = entry - sl_distance;
   }
   else
   {
      sl = entry + sl_distance;
   }

   string tag = IntegerToString((int)m1_time);
   DrawTradeLevels(m1_time, tag, entry, sl, direction);

   if(HasOpenPositionOnSymbol()) return false;
   bool ok = false;
   if(direction == "BUY")
      ok = g_trade.Buy(lot_size, _Symbol, 0.0, sl, 0.0, "STRUCTURE_TRAP");
   else
      ok = g_trade.Sell(lot_size, _Symbol, 0.0, sl, 0.0, "STRUCTURE_TRAP");

   if(!ok)
   {
      PrintFormat("ORDER FAILED | %s | retcode=%d", direction, g_trade.ResultRetcode());
      return false;
   }
   PrintFormat("ORDER OPENED | %s | lot=%.2f sl=%.5f risk=%.2f", direction, lot_size, sl, risk_eur);

   g_total_trades++;
   g_cooldown = GetCooldownBars();
   g_traded_day_key = today_key;
   g_last_reference_mid = 0.0;
   g_pulse_active = true;
   g_pulse_direction = direction;
   g_pulse_entry = entry;
   g_pulse_sl = sl;
   g_pulse_state = "SHIELD";
   g_pulse_rocket_counter = 0;
   g_pulse_ticket = (ulong)g_trade.ResultOrder();
   return true;
}

double ComputeAtrM1AtShift(const int shift)
{
   int h = iATR(_Symbol, PERIOD_M1, 14);
   if(h == INVALID_HANDLE) return 0.0;
   double b[1];
   if(CopyBuffer(h, 0, shift, 1, b) < 1)
   {
      IndicatorRelease(h);
      return 0.0;
   }
   IndicatorRelease(h);
   return b[0];
}

double GetAtrMeanM1(const int start_shift, const int count)
{
   int h = iATR(_Symbol, PERIOD_M1, 14);
   if(h == INVALID_HANDLE) return 0.0;
   double vals[];
   ArrayResize(vals, count);
   int got = CopyBuffer(h, 0, start_shift, count, vals);
   IndicatorRelease(h);
   if(got <= 0) return 0.0;
   double s = 0.0;
   for(int i = 0; i < got; i++) s += vals[i];
   return s / (double)got;
}

bool FindLastValidLowTracker(const MqlRates &candles[], int n, double min_distance, double &out_val)
{
   if(n < 5) return false;
   for(int i = n - 2; i >= 2; i--)
   {
      if(candles[i].low < candles[i - 1].low && candles[i].low < candles[i + 1].low)
      {
         double prev_low = candles[i - 1].low;
         if(MathAbs(candles[i].low - prev_low) >= min_distance)
         {
            out_val = candles[i].low;
            return true;
         }
      }
   }
   return false;
}

bool FindLastValidHighTracker(const MqlRates &candles[], int n, double min_distance, double &out_val)
{
   if(n < 5) return false;
   for(int i = n - 2; i >= 2; i--)
   {
      if(candles[i].high > candles[i - 1].high && candles[i].high > candles[i + 1].high)
      {
         double prev_high = candles[i - 1].high;
         if(MathAbs(candles[i].high - prev_high) >= min_distance)
         {
            out_val = candles[i].high;
            return true;
         }
      }
   }
   return false;
}

int FindHighIndex(const MqlRates &candles[], int n, double target)
{
   for(int i = n - 1; i >= 2; i--)
      if(MathAbs(candles[i].high - target) < 0.00001) return i;
   return -1;
}

int FindLowIndex(const MqlRates &candles[], int n, double target)
{
   for(int i = n - 1; i >= 2; i--)
      if(MathAbs(candles[i].low - target) < 0.00001) return i;
   return -1;
}

bool DetectStructuralReversal(const string direction, const MqlRates &candles[], int n, double seuil)
{
   if(n < 20) return false;
   double v1 = 0.0, v2 = 0.0;
   if(direction == "BUY")
   {
      if(!FindLastValidHighTracker(candles, n, seuil, v1) || v1 <= 0.0) return false;
      int idx = FindHighIndex(candles, n, v1);
      if(idx < 0 || idx >= n - 3) return false;
      MqlRates sub[];
      int m = n - idx;
      ArrayResize(sub, m);
      for(int i = 0; i < m; i++) sub[i] = candles[idx + i];
      if(!FindLastValidHighTracker(sub, m, seuil, v2) || v2 <= 0.0) return false;
      return (v2 < v1);
   }
   else
   {
      if(!FindLastValidLowTracker(candles, n, seuil, v1) || v1 <= 0.0) return false;
      int idx = FindLowIndex(candles, n, v1);
      if(idx < 0 || idx >= n - 3) return false;
      MqlRates sub2[];
      int m2 = n - idx;
      ArrayResize(sub2, m2);
      for(int i = 0; i < m2; i++) sub2[i] = candles[idx + i];
      if(!FindLastValidLowTracker(sub2, m2, seuil, v2) || v2 <= 0.0) return false;
      return (v2 > v1);
   }
}

bool DetectEmaReversal(const string direction)
{
   int ema_fast_p = GetEmaFastBySymbol();
   int ema_slow_p = GetEmaSlowBySymbol();
   int h_fast = iMA(_Symbol, PERIOD_M1, ema_fast_p, 0, MODE_EMA, PRICE_CLOSE);
   int h_slow = iMA(_Symbol, PERIOD_M1, ema_slow_p, 0, MODE_EMA, PRICE_CLOSE);
   if(h_fast == INVALID_HANDLE || h_slow == INVALID_HANDLE) return false;
   double ef[7], es[7];
   int g1 = CopyBuffer(h_fast, 0, 1, 7, ef);
   int g2 = CopyBuffer(h_slow, 0, 1, 7, es);
   IndicatorRelease(h_fast);
   IndicatorRelease(h_slow);
   if(g1 < 6 || g2 < 6) return false;
   double last_close = iClose(_Symbol, PERIOD_M1, 1);
   double slope = es[0] - es[5];
   double seuil = GetSlopeThresholdBySymbol();
   if(direction == "BUY")
      return (last_close < es[0] && ef[0] < es[0] && slope < -seuil);
   return (last_close > es[0] && ef[0] > es[0] && slope > seuil);
}

void ManagePulseOnNewBar(const datetime m1_time)
{
   if(!PositionSelect(_Symbol))
   {
      ResetPulse();
      return;
   }

   ulong ticket = (ulong)PositionGetInteger(POSITION_TICKET);
   string direction = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double current_sl = PositionGetDouble(POSITION_SL);

   if(!g_pulse_active || g_pulse_ticket != ticket)
   {
      g_pulse_active = true;
      g_pulse_ticket = ticket;
      g_pulse_direction = direction;
      g_pulse_entry = entry;
      g_pulse_sl = current_sl;
      g_pulse_state = "SHIELD";
      g_pulse_rocket_counter = 0;
      g_pulse_conviction = "STANDARD";
   }

   MqlRates m1[120];
   int n = CopyRates(_Symbol, PERIOD_M1, 0, 120, m1);
   if(n < 40) return;
   ArraySetAsSeries(m1, false);

   double atr_m1 = ComputeAtrM1AtShift(1);
   if(atr_m1 <= 0.0) return;

   if(g_pulse_state == "SHIELD")
   {
      MqlTick tk;
      if(!SymbolInfoTick(_Symbol, tk)) return;
      double current_px = (g_pulse_direction == "BUY") ? tk.bid : tk.ask;
      double profit_pts = (g_pulse_direction == "BUY") ? (current_px - g_pulse_entry) : (g_pulse_entry - current_px);
      double be_threshold = GetBEThresholdBySymbol();
      if(g_pulse_conviction == "HIGH") be_threshold *= 0.80;
      double target = be_threshold * atr_m1;
      if(profit_pts >= target)
      {
         g_pulse_state = "TRACKER";
         if((g_pulse_direction == "BUY" && g_pulse_entry > current_sl) ||
            (g_pulse_direction == "SELL" && (current_sl <= 0.0 || g_pulse_entry < current_sl)))
         {
            g_trade.PositionModify(_Symbol, g_pulse_entry, 0.0);
            g_pulse_sl = g_pulse_entry;
         }
      }
   }

   if(g_pulse_state == "TRACKER")
   {
      double min_dist = GetAtrFilterBySymbol() * atr_m1;
      double sl_buffer = GetSLBufferBySymbol();
      double pivot = 0.0;
      double new_sl = current_sl;

      if(g_pulse_direction == "BUY")
      {
        if(FindLastValidLowTracker(m1, n, min_dist, pivot))
           new_sl = pivot - (sl_buffer * atr_m1 * 0.2);
        if(new_sl > current_sl) { g_trade.PositionModify(_Symbol, new_sl, 0.0); g_pulse_sl = new_sl; current_sl = new_sl; }
      }
      else
      {
        if(FindLastValidHighTracker(m1, n, min_dist, pivot))
           new_sl = pivot + (sl_buffer * atr_m1 * 0.2);
        if(current_sl <= 0.0 || new_sl < current_sl) { g_trade.PositionModify(_Symbol, new_sl, 0.0); g_pulse_sl = new_sl; current_sl = new_sl; }
      }

      if(DetectStructuralReversal(g_pulse_direction, m1, n, min_dist))
      {
         g_trade.PositionClose(_Symbol);
         ResetPulse();
         return;
      }

      // Anti-chop M5: retour sous/au-dessus du mid de référence
      if(g_last_reference_mid > 0.0)
      {
         double m5_close = iClose(_Symbol, PERIOD_M5, 1);
         if((g_pulse_direction == "BUY" && m5_close < g_last_reference_mid) ||
            (g_pulse_direction == "SELL" && m5_close > g_last_reference_mid))
         {
            g_trade.PositionClose(_Symbol);
            ResetPulse();
            return;
         }
      }

      double atr_mean = GetAtrMeanM1(1, 20);
      if(atr_mean > 0.0 && atr_m1 > GetRocketAtrMultBySymbol() * atr_mean)
      {
         g_pulse_rocket_counter++;
         if(g_pulse_rocket_counter >= 3) g_pulse_state = "ROCKET";
      }
      else g_pulse_rocket_counter = 0;
   }

   if(g_pulse_state == "ROCKET")
   {
      double seuil_rocket = 1.3 * atr_m1;
      double sl_buffer_r = GetSLBufferBySymbol() * 0.3;
      double pivot2 = 0.0;
      double new_sl2 = current_sl;
      if(g_pulse_direction == "BUY")
      {
         if(FindLastValidLowTracker(m1, n, seuil_rocket, pivot2))
            new_sl2 = pivot2 - (seuil_rocket * sl_buffer_r);
         if(new_sl2 > current_sl) { g_trade.PositionModify(_Symbol, new_sl2, 0.0); g_pulse_sl = new_sl2; current_sl = new_sl2; }
      }
      else
      {
         if(FindLastValidHighTracker(m1, n, seuil_rocket, pivot2))
            new_sl2 = pivot2 + (seuil_rocket * sl_buffer_r);
         if(current_sl <= 0.0 || new_sl2 < current_sl) { g_trade.PositionModify(_Symbol, new_sl2, 0.0); g_pulse_sl = new_sl2; current_sl = new_sl2; }
      }

      if(DetectEmaReversal(g_pulse_direction))
      {
         g_trade.PositionClose(_Symbol);
         ResetPulse();
         return;
      }

      if(g_last_reference_mid > 0.0)
      {
         double m5_close2 = iClose(_Symbol, PERIOD_M5, 1);
         if((g_pulse_direction == "BUY" && m5_close2 < g_last_reference_mid) ||
            (g_pulse_direction == "SELL" && m5_close2 > g_last_reference_mid))
         {
            g_trade.PositionClose(_Symbol);
            ResetPulse();
            return;
         }
      }
   }
}

int OnInit()
{
   Print("structure_trap.mq5 initialise (REAL ORDERS mode).");
   ResetPulse();
   return(INIT_SUCCEEDED);
}

void OnTick()
{
   datetime m1_time = iTime(_Symbol, PERIOD_M1, 1);
   if(m1_time == 0 || m1_time == g_last_m1_bar) return;
   g_last_m1_bar = m1_time;
   ManagePulseOnNewBar(m1_time);

   int today_key = DayKey(m1_time);
   if(g_traded_day_key == today_key)
   {
      Comment(StringFormat("StructureTrap | signals=%d trades=%d | mode=REAL", g_total_signals, g_total_trades));
      return;
   }

   if(g_cooldown > 0)
   {
      g_cooldown--;
      return;
   }

    // Daily kill switch (4%)
   UpdateDailySnapshot(m1_time);
   if(g_daily_snapshot_balance > 0.0)
   {
      double loss_today = g_daily_snapshot_balance - AccountInfoDouble(ACCOUNT_BALANCE);
      if(loss_today >= (g_daily_snapshot_balance * 0.04))
         return;
   }

   if(g_kill_switch) return;
   if(g_consecutive_losses == 2) return;

   if(HasOpenPositionOnSymbol())
   {
      Comment(StringFormat("StructureTrap | open=1 | pulse=%s | signals=%d trades=%d | mode=REAL",
                           g_pulse_state, g_total_signals, g_total_trades));
      return;
   }

   if(!IsBetweenHHMM(m1_time, "00:00", "21:44"))
      return;

   string breakout_dir = "";
   double mid_ref = 0.0;
   if(!BuildContext(m1_time, breakout_dir, mid_ref)) return;

   MqlRates m1[220];
   int n = CopyRates(_Symbol, PERIOD_M1, 0, 220, m1);
   if(n < 50) return;
   ArraySetAsSeries(m1, false);

   int atr_handle = iATR(_Symbol, PERIOD_M1, 14);
   if(atr_handle == INVALID_HANDLE) return;
   double atr_buf[3];
   if(CopyBuffer(atr_handle, 0, 0, 3, atr_buf) < 2)
   {
      IndicatorRelease(atr_handle);
      return;
   }
   IndicatorRelease(atr_handle);
   double atr_m1 = atr_buf[1];
   if(atr_m1 <= 0.0) return;

   string scenario = RunStateMachine(breakout_dir, m1, n, atr_m1);
   if(scenario == "") return;

   string direction = "";
   if(scenario == "CONTINUATION_BUY" || scenario == "SWEEP_BUY") direction = "BUY";
   if(scenario == "CONTINUATION_SELL" || scenario == "SWEEP_SELL") direction = "SELL";
   if(direction == "") return;

   double entry = m1[n - 1].close;
   g_total_signals++;
   PrintFormat("STRUCTURE_TRAP SIGNAL #%d | %s | %s | entry=%.5f | time=%s",
               g_total_signals, scenario, direction, entry, TimeToString(m1_time, TIME_DATE | TIME_MINUTES));

   PlotSignal(m1_time, entry, scenario, direction);
   g_last_reference_mid = mid_ref;
   OpenTrade(direction, m1_time, entry, today_key);
   Comment(StringFormat("StructureTrap last: %s %s @ %.5f | signals=%d trades=%d | mode=REAL",
                        scenario, direction, entry, g_total_signals, g_total_trades));

   ResetState();
}

void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal = trans.deal;
   if(deal == 0) return;

   string deal_symbol = HistoryDealGetString(deal, DEAL_SYMBOL);
   if(deal_symbol != _Symbol) return;

   long entry_type = HistoryDealGetInteger(deal, DEAL_ENTRY);
   if(entry_type != DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT);
   if(profit < 0)
   {
      g_consecutive_losses++;
      if(g_consecutive_losses >= 3) g_kill_switch = true;
   }
   else
   {
      g_consecutive_losses = 0;
      g_kill_switch = false;
   }
}
