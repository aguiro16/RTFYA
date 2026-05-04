import time
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from config import (
   BINANCE_API_KEY, BINANCE_API_SECRET,
   BINANCE_BASE_URL, BINANCE_FUTURES_BASE_URL,
   MAX_LEVERAGE, ENABLE_SPOT_TRADING, ENABLE_FUTURES_TRADING
)

logging.basicConfig(
   level=logging.INFO,
   format="%(asctime)s [%(levelname)s] %(message)s",
   handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── Client مشترك ─────────────────────────────────────────────────────────────
_client = None

def get_client() -> Client:
   global _client
   if _client is None:
       _client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
   return _client

# ─── Cache لمعلومات الرموز ─────────────────────────────────────────────────────
_futures_symbol_cache = {}
_spot_symbol_cache = {}

def get_symbol_info_futures(symbol: str) -> dict:
   if symbol in _futures_symbol_cache:
       return _futures_symbol_cache[symbol]
   try:
       client = get_client()
       info = client.futures_exchange_info()
       for s in info["symbols"]:
           result = {"stepSize": "0.001", "tickSize": "0.0001", "minQty": "0.001"}
           for f in s.get("filters", []):
               if f["filterType"] == "LOT_SIZE":
                   result["stepSize"] = f["stepSize"]
                   result["minQty"]   = f["minQty"]
               if f["filterType"] == "PRICE_FILTER":
                   result["tickSize"] = f["tickSize"]
           _futures_symbol_cache[s["symbol"]] = result
       if symbol in _futures_symbol_cache:
           return _futures_symbol_cache[symbol]
   except Exception as e:
       log.error(f"Symbol info error {symbol}: {e}")
   return {"stepSize": "0.001", "tickSize": "0.0001", "minQty": "0.001"}

def get_symbol_info_spot(symbol: str) -> dict:
   if symbol in _spot_symbol_cache:
       return _spot_symbol_cache[symbol]
   try:
       client = get_client()
       info = client.get_exchange_info()
       for s in info["symbols"]:
           result = {"stepSize": "0.001", "tickSize": "0.0001", "minQty": "0.001"}
           for f in s.get("filters", []):
               if f["filterType"] == "LOT_SIZE":
                   result["stepSize"] = f["stepSize"]
                   result["minQty"]   = f["minQty"]
               if f["filterType"] == "PRICE_FILTER":
                   result["tickSize"] = f["tickSize"]
           _spot_symbol_cache[s["symbol"]] = result
       if symbol in _spot_symbol_cache:
           return _spot_symbol_cache[symbol]
   except Exception as e:
       log.error(f"Spot symbol info error {symbol}: {e}")
   return {"stepSize": "0.001", "tickSize": "0.0001", "minQty": "0.001"}

# ─── جلب رصيد USDT ────────────────────────────────────────────────────────────

def get_futures_balance() -> float:
   try:
       client = get_client()
       for b in client.futures_account_balance():
           if b["asset"] == "USDT":
               return float(b["availableBalance"])
   except Exception as e:
       log.error(f"Futures balance error: {e}")
   return 0.0

def get_spot_balance_usdt() -> float:
   try:
       client = get_client()
       account = client.get_account()
       for asset in account["balances"]:
           if asset["asset"] == "USDT":
               return float(asset["free"])
   except Exception as e:
       log.error(f"Spot balance error: {e}")
   return 0.0

def get_spot_existing_coins() -> set:
   try:
       client = get_client()
       account = client.get_account()
       coins = set()
       for asset in account["balances"]:
           if float(asset["free"]) > 0 or float(asset["locked"]) > 0:
               coins.add(asset["asset"])
       return coins
   except Exception as e:
       log.error(f"Spot coins error: {e}")
   return set()

# ─── أدوات التقريب ────────────────────────────────────────────────────────────

def round_step(value: float, step: str) -> float:
   decimals = len(step.rstrip("0").split(".")[-1]) if "." in step else 0
   return round(value - (value % float(step)), decimals)

def round_price(price: float, tick_size: str) -> float:
   decimals = len(tick_size.rstrip("0").split(".")[-1]) if "." in tick_size else 0
   return round(price - (price % float(tick_size)), decimals)

def calc_quantity(symbol: str, entry_price: float, usdt_amount: float, market_type: str) -> float:
   if market_type == "FUTURES":
       info = get_symbol_info_futures(symbol)
   else:
       info = get_symbol_info_spot(symbol)
   qty = usdt_amount / entry_price
   qty = round_step(qty, info["stepSize"])
   if qty < float(info["minQty"]):
       return 0.0
   return qty

# ─── ضبط Leverage ─────────────────────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int) -> bool:
   try:
       client = get_client()
       client.futures_change_leverage(symbol=symbol, leverage=leverage)
       return True
   except Exception as e:
       log.error(f"Leverage error: {e}")
   return False

# ─── تنفيذ Futures ────────────────────────────────────────────────────────────

def place_futures_order_and_sltp(symbol: str, direction: str, qty: float,
                                 sl: float, tp: float) -> dict:
   try:
       client = get_client()
       side    = "BUY"  if direction == "LONG" else "SELL"
       sl_side = "SELL" if direction == "LONG" else "BUY"
       tp_side = "SELL" if direction == "LONG" else "BUY"

       info      = get_symbol_info_futures(symbol)
       tick_size = info["tickSize"]
       sl_price  = round_price(sl, tick_size)
       tp_price  = round_price(tp, tick_size)

       log.info(f"Opening {direction} {symbol} qty={qty} SL={sl_price} TP={tp_price}")

       # ─── فتح المركز ───────────────────────────────────────────────────────
       order = client.futures_create_order(
           symbol=symbol,
           side=side,
           type="MARKET",
           quantity=qty
       )
       log.info(f"Market order: {order.get('orderId')}")

       # ─── وقف الخسارة ──────────────────────────────────────────────────────
       sl_order = client.futures_create_order(
           symbol=symbol,
           side=sl_side,
           type="STOP_MARKET",
           stopPrice=sl_price,
           closePosition=True,
           workingType="MARK_PRICE"
       )
       log.info(f"SL order: {sl_order.get('orderId')} ✅")

       # ─── هدف الربح ────────────────────────────────────────────────────────
       tp_order = client.futures_create_order(
           symbol=symbol,
           side=tp_side,
           type="TAKE_PROFIT_MARKET",
           stopPrice=tp_price,
           closePosition=True,
           workingType="MARK_PRICE"
       )
       log.info(f"TP order: {tp_order.get('orderId')} ✅")

       return order

   except BinanceAPIException as e:
       log.error(f"Binance API error {symbol}: code={e.status_code} msg={e.message}")
   except Exception as e:
       import traceback
       log.error(f"Futures order error {symbol}: {traceback.format_exc()}")
   return {}

# ─── تنفيذ Spot ───────────────────────────────────────────────────────────────

def place_spot_order(symbol: str, qty: float) -> dict:
   try:
       client = get_client()
       order = client.order_market_buy(symbol=symbol, quantity=qty)
       log.info(f"Spot BUY order: {order.get('orderId')} ✅")
       return order
   except BinanceAPIException as e:
       log.error(f"Spot API error {symbol}: code={e.status_code} msg={e.message}")
   except Exception as e:
       log.error(f"Spot order error {symbol}: {e}")
   return {}

# ─── الدالة الرئيسية ──────────────────────────────────────────────────────────

_protected_spot_coins: set = set()

def load_protected_coins():
   global _protected_spot_coins
   _protected_spot_coins = get_spot_existing_coins()
   _protected_spot_coins.discard("USDT")
   log.info(f"Protected Spot coins: {_protected_spot_coins}")

def execute_signal(signal: dict) -> dict:
   symbol      = signal["symbol"]
   direction   = signal["direction"]
   entry_price = signal["entry_price"]
   market_type = signal["market_type"]
   sl          = signal["sl"]
   tp          = signal["tp3"]

   result = {
       "executed":    False,
       "market_type": market_type,
       "symbol":      symbol,
       "direction":   direction,
       "qty":         0,
       "error":       None
   }

   # ─── Futures ──────────────────────────────────────────────────────────────
   if market_type == "FUTURES":
       if not ENABLE_FUTURES_TRADING:
           result["error"] = "Futures trading disabled"
           return result

       balance = get_futures_balance()
       if balance < 10:
           result["error"] = f"Insufficient futures balance: {balance} USDT"
           return result

       usdt_to_use = round(balance * 0.10, 2)
       qty = calc_quantity(symbol, entry_price, usdt_to_use * MAX_LEVERAGE, market_type)
       if qty == 0:
           result["error"] = "Quantity too small"
           return result

       set_leverage(symbol, MAX_LEVERAGE)
       order = place_futures_order_and_sltp(symbol, direction, qty, sl, tp)

       if order.get("orderId"):
           result["executed"] = True
           result["qty"]      = qty
           result["order_id"] = order["orderId"]
           log.info(f"✅ Futures {direction} {symbol} qty={qty} executed")
       else:
           result["error"] = "Order failed"

   # ─── Spot ─────────────────────────────────────────────────────────────────
   elif market_type == "SPOT":
       if not ENABLE_SPOT_TRADING:
           result["error"] = "Spot trading disabled"
           return result

       base_coin = symbol.replace("USDT", "")
       if base_coin in _protected_spot_coins:
           result["error"] = f"Protected coin: {base_coin} already in wallet"
           return result

       if direction != "LONG":
           result["error"] = "Spot only supports LONG (BUY)"
           return result

       balance = get_spot_balance_usdt()
       if balance < 10:
           result["error"] = f"Insufficient spot balance: {balance} USDT"
           return result

       usdt_to_use = round(balance * 0.10, 2)
       qty = calc_quantity(symbol, entry_price, usdt_to_use, market_type)
       if qty == 0:
           result["error"] = "Quantity too small"
           return result

       order = place_spot_order(symbol, qty)
       if order.get("orderId"):
           result["executed"] = True
           result["qty"]      = qty
           result["order_id"] = order["orderId"]
           log.info(f"✅ Spot BUY {symbol} qty={qty} executed")
       else:
           result["error"] = "Spot order failed"

   return result
