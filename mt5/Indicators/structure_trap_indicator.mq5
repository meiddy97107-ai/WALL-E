#property strict
#property indicator_chart_window
#property indicator_plots 0
#property version "1.00"
#property description "Structure Trap visual indicator (signals only)."

enum ContextMode
{
   CONTEXT_AUTO = 0,
   CONTEXT_ASIAN_BOX = 1,
   CONTEXT_BOLLINGER = 2,
   CONTEXT_ORB = 3
};

input ContextMode InpContextMode = CONTEXT_AUTO;
input int    InpLookbackBarsM1 = 12000;
input bool   InpOneSignalPerDay = true;
input int    InpCooldownBars = 30;
input int    InpTimeoutH2 = 20;
input double InpAtrFilter = 1.8;
input string InpAsianStart = "02:00";
input string InpAsianEnd = "08:00";
input string InpSignalCutoff = "11:30";
input string InpOrbStart = "15:30";
input string InpOrbEnd = "16:00";
input string InpSessionStart = "16:00";
input string InpSessionEnd = "21:45";
input bool   InpPrintLogs = true;

string PREFIX = "STI_";

string ETAT_ATTENTE_H1 = "ATTENTE_H1";
string ETAT_ATTENTE_L1 = "ATTENTE_L1";
string ETAT_ATTENTE_H2 = "ATTENTE_H2";
string ETAT_ATTENTE_L2 = "ATTENTE_L2";
string ETAT_DECISION   = "DECISION";

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

void ClearObjects()
{
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, PREFIX) == 0) ObjectDelete(0, name);
   }
}

void PlotSignal(datetime t, double price, string scenario, string direction)
{
   string name = PREFIX + scenario + "_" + IntegerToString((int)t);
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

bool GetLastValidatedHigh(const MqlRates &arr[], int upto_idx, double seuil, double &out_high)
{
   if(upto_idx < 5) return false;
   for(int i = upto_idx - 2; i >= 2; i--)
   {
      if(arr[i].high > arr[i - 1].high && arr[i].high > arr[i + 1].high)
      {
         double low_after = MinLowFrom(arr, i, upto_idx);
         if(arr[i].high - low_after >= seuil)
         {
            out_high = arr[i].high;
            return true;
         }
      }
   }
   return false;
}

bool GetLastValidatedLow(const MqlRates &arr[], int upto_idx, double seuil, double &out_low)
{
   if(upto_idx < 5) return false;
   for(int i = upto_idx - 2; i >= 2; i--)
   {
      if(arr[i].low < arr[i - 1].low && arr[i].low < arr[i + 1].low)
      {
         double high_after = MaxHighFrom(arr, i, upto_idx);
         if(high_after - arr[i].low >= seuil)
         {
            out_low = arr[i].low;
            return true;
         }
      }
   }
   return false;
}

double LastCloseM15Before(const MqlRates &m15[], int n15, datetime t)
{
   double v = 0.0;
   bool found = false;
   for(int i = 0; i < n15; i++)
   {
      if(m15[i].time <= t) { v = m15[i].close; found = true; }
      else break;
   }
   if(!found) return 0.0;
   return v;
}

bool ComputeAsianContext(const MqlRates &m15[], int n15, datetime t, int &cache_day, bool &cache_ready, double &cache_hi, double &cache_lo, string &breakout_dir, double &mid_ref)
{
   int day_key = DayKey(t);
   if(cache_day != day_key)
   {
      cache_day = day_key;
      cache_ready = false;
      cache_hi = 0.0;
      cache_lo = 0.0;
   }

   if(!cache_ready)
   {
      double hi = -DBL_MAX, lo = DBL_MAX;
      bool found = false;
      for(int i = 0; i < n15; i++)
      {
         if(m15[i].time > t) break;
         if(DayKey(m15[i].time) != day_key) continue;
         if(!IsBetweenHHMM(m15[i].time, InpAsianStart, InpAsianEnd)) continue;
         found = true;
         hi = MathMax(hi, m15[i].high);
         lo = MathMin(lo, m15[i].low);
      }
      if(!found) return false;
      cache_hi = hi;
      cache_lo = lo;
      cache_ready = true;
   }

   if(!IsBetweenHHMM(t, InpAsianStart, InpSignalCutoff)) return false;
   double px = LastCloseM15Before(m15, n15, t);
   if(px <= 0.0) return false;

   if(px > cache_hi) breakout_dir = "HAUT";
   else if(px < cache_lo) breakout_dir = "BAS";
   else return false;

   mid_ref = (cache_hi + cache_lo) * 0.5;
   return true;
}

bool ComputeOrbContext(const MqlRates &m15[], int n15, datetime t, string &breakout_dir, double &mid_ref)
{
   if(!IsBetweenHHMM(t, InpSessionStart, InpSessionEnd)) return false;
   int day_key = DayKey(t);
   double hi = -DBL_MAX, lo = DBL_MAX;
   bool found = false;

   for(int i = 0; i < n15; i++)
   {
      if(m15[i].time > t) break;
      if(DayKey(m15[i].time) != day_key) continue;
      if(!IsBetweenHHMM(m15[i].time, InpOrbStart, InpOrbEnd)) continue;
      found = true;
      hi = MathMax(hi, m15[i].high);
      lo = MathMin(lo, m15[i].low);
   }
   if(!found) return false;

   double px = LastCloseM15Before(m15, n15, t);
   if(px <= 0.0) return false;
   if(px > hi) breakout_dir = "HAUT";
   else if(px < lo) breakout_dir = "BAS";
   else return false;
   mid_ref = (hi + lo) * 0.5;
   return true;
}

bool ComputeBollingerContext(const MqlRates &m15[], int n15, datetime t, int bb_handle, string &breakout_dir, double &mid_ref)
{
   int shift = iBarShift(_Symbol, PERIOD_M15, t, false);
   if(shift < 1) return false;

   double up[1], mid[1], low[1];
   if(CopyBuffer(bb_handle, 1, shift, 1, up) < 1) return false;
   if(CopyBuffer(bb_handle, 0, shift, 1, mid) < 1) return false;
   if(CopyBuffer(bb_handle, 2, shift, 1, low) < 1) return false;

   double o = iOpen(_Symbol, PERIOD_M15, shift);
   double c = iClose(_Symbol, PERIOD_M15, shift);

   if(c > up[0] && c > o) breakout_dir = "HAUT";
   else if(c < low[0] && c < o) breakout_dir = "BAS";
   else return false;

   mid_ref = mid[0];
   return true;
}

bool BuildContext(const string context_name, const MqlRates &m15[], int n15, datetime t, int bb_handle, int &cache_day, bool &cache_ready, double &cache_hi, double &cache_lo, string &breakout_dir, double &mid_ref)
{
   if(context_name == "asian_box")
      return ComputeAsianContext(m15, n15, t, cache_day, cache_ready, cache_hi, cache_lo, breakout_dir, mid_ref);
   if(context_name == "orb")
      return ComputeOrbContext(m15, n15, t, breakout_dir, mid_ref);
   return ComputeBollingerContext(m15, n15, t, bb_handle, breakout_dir, mid_ref);
}

int OnInit()
{
   IndicatorSetString(INDICATOR_SHORTNAME, "StructureTrap Visual");
   ClearObjects();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   ClearObjects();
}

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total < 300) return rates_total;

   MqlRates m1[];
   int n1 = CopyRates(_Symbol, PERIOD_M1, 0, MathMax(InpLookbackBarsM1, 1000), m1);
   if(n1 < 300) return rates_total;
   ArraySetAsSeries(m1, false);

   MqlRates m15[];
   int n15 = CopyRates(_Symbol, PERIOD_M15, 0, 2000, m15);
   if(n15 < 100) return rates_total;
   ArraySetAsSeries(m15, false);

   int atr_handle = iATR(_Symbol, PERIOD_M1, 14);
   int bb_handle = iBands(_Symbol, PERIOD_M15, 20, 0, 2.0, PRICE_CLOSE);
   if(atr_handle == INVALID_HANDLE || bb_handle == INVALID_HANDLE) return rates_total;

   ClearObjects();

   string context_name = ResolveContext();

   string etat = "";
   string cassure = "";
   string breakout_initial = "";
   int compteur = 0, cooldown = 0, last_trade_day = -1, total_signals = 0;
   double h1v = 0.0, l1v = 0.0, h2v = 0.0, l2v = 0.0;

   int asian_cache_day = -1;
   bool asian_cache_ready = false;
   double asian_cache_hi = 0.0, asian_cache_lo = 0.0;

   int start = MathMax(220, n1 - InpLookbackBarsM1);
   for(int i = start; i < n1 - 1; i++)
   {
      datetime t = m1[i].time;
      int day_key = DayKey(t);

      if(InpOneSignalPerDay && day_key == last_trade_day) continue;
      if(cooldown > 0) { cooldown--; continue; }

      string breakout_dir = "";
      double mid_ref = 0.0;
      if(!BuildContext(context_name, m15, n15, t, bb_handle, asian_cache_day, asian_cache_ready, asian_cache_hi, asian_cache_lo, breakout_dir, mid_ref))
         continue;

      double atrv_arr[1];
      int shift = iBarShift(_Symbol, PERIOD_M1, t, false);
      if(shift < 1) continue;
      if(CopyBuffer(atr_handle, 0, shift, 1, atrv_arr) < 1) continue;
      double atr_m1 = atrv_arr[0];
      if(atr_m1 <= 0.0) continue;

      if(etat == "")
      {
         if(breakout_dir == "HAUT")
         {
            etat = ETAT_ATTENTE_H1;
            cassure = "HAUT";
            breakout_initial = "HAUT";
         }
         else
         {
            etat = ETAT_ATTENTE_L1;
            cassure = "BAS";
            breakout_initial = "BAS";
         }
         compteur = 0;
         h1v = 0.0; l1v = 0.0; h2v = 0.0; l2v = 0.0;
      }

      if(breakout_initial != breakout_dir)
      {
         etat = "";
         continue;
      }

      compteur++;
      if(compteur > InpTimeoutH2)
      {
         etat = "";
         continue;
      }

      double seuil = InpAtrFilter * atr_m1;
      double tmp = 0.0;
      string scenario = "";

      if(cassure == "HAUT")
      {
         if(etat == ETAT_ATTENTE_H1)
         {
            if(GetLastValidatedHigh(m1, i + 1, seuil, tmp)) { h1v = tmp; etat = ETAT_ATTENTE_L1; }
            continue;
         }
         if(etat == ETAT_ATTENTE_L1)
         {
            if(GetLastValidatedLow(m1, i + 1, seuil, tmp)) { l1v = tmp; etat = ETAT_ATTENTE_H2; compteur = 0; }
            continue;
         }
         if(etat == ETAT_ATTENTE_H2)
         {
            if(GetLastValidatedHigh(m1, i + 1, seuil, tmp)) { h2v = tmp; etat = ETAT_DECISION; }
            continue;
         }
         if(etat == ETAT_DECISION)
         {
            if(h2v > 0.0 && h1v > 0.0)
            {
               if(h2v < h1v) scenario = "SWEEP_SELL";
               else if(h2v > h1v) scenario = "CONTINUATION_BUY";
            }
            etat = "";
         }
      }
      else
      {
         if(etat == ETAT_ATTENTE_L1)
         {
            if(GetLastValidatedLow(m1, i + 1, seuil, tmp)) { l1v = tmp; etat = ETAT_ATTENTE_H1; }
            continue;
         }
         if(etat == ETAT_ATTENTE_H1)
         {
            if(GetLastValidatedHigh(m1, i + 1, seuil, tmp)) { h1v = tmp; etat = ETAT_ATTENTE_L2; compteur = 0; }
            continue;
         }
         if(etat == ETAT_ATTENTE_L2)
         {
            if(GetLastValidatedLow(m1, i + 1, seuil, tmp)) { l2v = tmp; etat = ETAT_DECISION; }
            continue;
         }
         if(etat == ETAT_DECISION)
         {
            if(l2v > 0.0 && l1v > 0.0)
            {
               if(l2v > l1v) scenario = "SWEEP_BUY";
               else if(l2v < l1v) scenario = "CONTINUATION_SELL";
            }
            etat = "";
         }
      }

      if(scenario == "") continue;
      string direction = (StringFind(scenario, "BUY") >= 0) ? "BUY" : "SELL";
      double entry = m1[i].close;
      PlotSignal(t, entry, scenario, direction);
      total_signals++;

      if(InpPrintLogs)
      {
         PrintFormat("ST_INDICATOR SIGNAL #%d | %s | %s | entry=%.5f | %s",
                     total_signals, scenario, direction, entry, TimeToString(t, TIME_DATE | TIME_MINUTES));
      }

      cooldown = InpCooldownBars;
      last_trade_day = day_key;
   }

   Comment(StringFormat("StructureTrap indicator | context=%s | signals=%d", context_name, total_signals));
   IndicatorRelease(atr_handle);
   IndicatorRelease(bb_handle);
   return rates_total;
}
