//+------------------------------------------------------------------+
//| SMA cross Expert Advisor (MQL5)                                  |
//+------------------------------------------------------------------+
#property copyright "Tickbench example"
#property version   "1.00"
#include <Trade\Trade.mqh>

input int    FastPeriod = 10;    // Fast SMA period
input int    SlowPeriod = 30;    // Slow SMA period
input double Lots       = 0.1;   // Lots per trade

CTrade trade;
int fastHandle;
int slowHandle;

int OnInit()
{
   fastHandle = iMA(_Symbol, PERIOD_CURRENT, FastPeriod, 0, MODE_SMA, PRICE_CLOSE);
   slowHandle = iMA(_Symbol, PERIOD_CURRENT, SlowPeriod, 0, MODE_SMA, PRICE_CLOSE);
   if(fastHandle == INVALID_HANDLE || slowHandle == INVALID_HANDLE)
      return(INIT_FAILED);
   trade.SetExpertMagicNumber(1001);
   return(INIT_SUCCEEDED);
}

void OnTick()
{
   double fast[], slow[];
   ArraySetAsSeries(fast, true);
   ArraySetAsSeries(slow, true);
   // shift 1 = last closed bar, shift 2 = the one before
   if(CopyBuffer(fastHandle, 0, 1, 2, fast) < 2) return;
   if(CopyBuffer(slowHandle, 0, 1, 2, slow) < 2) return;
   if(slow[1] == 0) return;   // the slow MA is still warming up

   bool crossedUp   = fast[0] > slow[0] && fast[1] <= slow[1];
   bool crossedDown = fast[0] < slow[0] && fast[1] >= slow[1];

   if(!PositionSelect(_Symbol))
   {
      if(crossedUp)
         trade.Buy(Lots, _Symbol, 0, 0, 0, "SMA cross up");
   }
   else if(crossedDown)
   {
      trade.PositionClose(_Symbol);
   }
}
