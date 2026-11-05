//+------------------------------------------------------------------+
//| SMA cross Expert Advisor (MQL4)                                  |
//+------------------------------------------------------------------+
#property copyright "Tickbench example"
#property strict

extern int    FastPeriod = 10;   // Fast SMA period
extern int    SlowPeriod = 30;   // Slow SMA period
extern double Lots       = 1.0;  // Lots per trade
extern int    Magic      = 2002;

int CountMyOrders()
{
   int count = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && OrderMagicNumber() == Magic && OrderType() == OP_BUY)
         count++;
   }
   return(count);
}

void OnTick()
{
   double fast1 = iMA(NULL, 0, FastPeriod, 0, MODE_SMA, PRICE_CLOSE, 1);
   double slow1 = iMA(NULL, 0, SlowPeriod, 0, MODE_SMA, PRICE_CLOSE, 1);
   double fast2 = iMA(NULL, 0, FastPeriod, 0, MODE_SMA, PRICE_CLOSE, 2);
   double slow2 = iMA(NULL, 0, SlowPeriod, 0, MODE_SMA, PRICE_CLOSE, 2);
   if(fast2 == 0 || slow2 == 0) return;   // indicators read 0 until they have enough bars

   if(CountMyOrders() == 0)
   {
      if(fast1 > slow1 && fast2 <= slow2)
      {
         int ticket = OrderSend(Symbol(), OP_BUY, Lots, Ask, 3, 0, 0, "SMA cross up", Magic, 0, clrGreen);
         if(ticket < 0) Print("OrderSend failed: ", GetLastError());
      }
   }
   else if(fast1 < slow1 && fast2 >= slow2)
   {
      for(int i = OrdersTotal() - 1; i >= 0; i--)
      {
         if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES) && OrderMagicNumber() == Magic)
            OrderClose(OrderTicket(), OrderLots(), Bid, 3, clrRed);
      }
   }
}
