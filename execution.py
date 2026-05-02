import hmac
import hashlib
import time
import requests
from config import (
   BINANCE_API_KEY, BINANCE_API_SECRET,
   BINANCE_BASE_URL, BINANCE_FUTURES_BASE_URL,
   MAX_LEVERAGE, ENABLE_SPOT_TRADING, ENABLE_FUTURES_TRADING
)

# ─── توقيع الطلبات ────────────────────────────────────────────────────────────

def _sign(params: dict, secret: str) -> str:
   query = "&".join(f"{k}={v}" for k, v in params.items())
   return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

def _headers():
   return {"X-MBX-APIKEY": BINANCE_API_KEY}

def _ts():
   return int(time.time() * 1000)

# ─── جلب رصيد USDT ────────────────────────────────────────────────────────────

def get_futures_balance() -> float:
   try:
       params = {"timestamp": _ts()}
       params["signature"] = _sign(params, BINANCE_API_SECRET)
       r = requests.get(
           f"{BINANCE_FUTURES_BASE_URL}/fapi/v2/balance",
           headers=_headers(), params=params, timeout=10
       )
       for asset in r.json():
           if asset.get("asset") == "USDT":
               return float(asset.get("availableBalance", 0))
   except Exception as e:
       print(f"Futures balance error: {e}")
   return 0.0

def get_spot_balance_usdt() -> float:
   try:
       params = {"timestamp": _ts()}
       params["signature"] = _sign(params, BINANCE_API_SECRET)
       r = requests.get(
           f"{BINANCE_BASE_URL}/api/v3/account",
           headers=_headers(), params=params, timeout=10
       )
       for asset in r.json().get("balances", []):
           if asset.get("asset") == "USDT":
               return float(asset.get("free", 0))
   except Exception as e:
       print(f"Spot balance error: {e}")
   return 0.0

def get_spot_existing_coins() -> set:
   try:
       params = {"timestamp": _ts()}
       params["signature"] = _sign(params, BINANCE_API_SECRET)
       r = requests.get(
           f"{BINANCE_BASE_URL}/api/v3/account",
           headers=_headers(), params=params, timeout=10
       )
       coins = set()
       for asset in r.json().get("balances", []):
           if float(asset.get("free", 0)) > 0 or float(asset.get("locked", 0)) > 0:
               coins.add(asset["asset"])
       return coins
   except Exception as e:
       print(f"Spot coins error: {e}")
   return set()

# ─── معلومات الرمز ────────────────────────────────────────────────────────────

def get_symbol_info(symbol: str, market_type: str) -> dict:
   try:
       if market_type == "FUTURES":
           r = requests.get(f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
       else:
           r = requests.get(f"{BINANCE_BASE_URL}/api/v3/exchangeInfo", timeout=10)
       for s in r.json().get("symbols", []):
           if s["symbol"] == symbol:
               info = {"stepSize": "0.001", "tickSize": "0.01", "minQty": "0.001"}
               for f in s.get("filters", []):
                   if f["filterType"] == "LOT_SIZE":
                       info["stepSize"] = f["stepSize"]
                       info["minQty"]   = f["minQty"]
                   if f["filterType"] == "PRICE_FILTER":
                       info["tickSize"] = f["tickSize"]
               return info
   except Exception as e:
       print(f"Symbol info error {symbol}: {e}")
   return {"stepSize": "0.001", "tickSize": "0.01", "minQty": "0.001"}

def round_step(value: float, step: str) -> float:
   decimals = len(step.rstrip("0").split(".")[-1]) if "." in step else 0
   return round(value - (value % float(step)), decimals)

def calc_quantity(symbol: str, entry_price: float, usdt_amount: float, market_type: str) -> float:
   info = get_symbol_info(symbol, market_type)
   qty  = usdt_amount / entry_price
   qty  = round_step(qty, info["stepSize"])
   if qty < float(info["minQty"]):
       return 0.0
   return qty

# ─── ضبط Leverage للـ Futures ─────────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int) -> bool:
   try:
       params = {"symbol": symbol, "leverage": leverage, "timestamp": _ts()}
       params["signature"] = _sign(params, BINANCE_API_SECRET)
       r = requests.post(
           f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/leverage",
           headers=_headers(), params=params, timeout=10
       )
       return r.json().get("leverage") == leverage
   except Exception as e:
       print(f"Leverage error: {e}")
   return False

# ─── تنفيذ أوامر Futures ──────────────────────────────────────────────────────

def place_futures_order(symbol: str, side: str, qty: float) -> dict:
   try:
       params = {
           "symbol":    symbol,
           "side":      side,
           "type":      "MARKET",
           "quantity":  qty,
           "timestamp": _ts()
       }
       params["signature"] = _sign(params, BINANCE_API_SECRET)
       r = requests.post(
           f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/order",
           headers=_headers(), params=params, timeout=10
       )
       return r.json()
   except Exception as e:
       print(f"Futures order error: {e}")
   return {}

def place_futures_sl_tp(symbol: str, direction: str, qty: float, sl: float, tp: float) -> bool:
   try:
       close_side = "SELL" if direction == "LONG" else "BUY"

       # ─── وقف الخسارة ──────────────────────────────────────────────────────
       sl_params = {
           "symbol":     symbol,
           "side":       close_side,
           "type":       "STOP_MARKET",
           "stopPrice":  round(sl, 4),
           "quantity":   qty,
           "reduceOnly": "true",
           "timestamp":  _ts()
       }
       sl_params["signature"] = _sign(sl_params, BINANCE_API_SECRET)
       sl_resp = requests.post(
           f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/order",
           headers=_headers(), params=sl_params, timeout=10
       )
       print(f"SL order: {sl_resp.json()}")

       # ─── هدف الربح ────────────────────────────────────────────────────────
       tp_params = {
           "symbol":     symbol,
           "side":       close_side,
           "type":       "TAKE_PROFIT_MARKET",
           "stopPrice":  round(tp, 4),
           "quantity":   qty,
           "reduceOnly": "true",
           "timestamp":  _ts()
       }
       tp_params["signature"] = _sign(tp_params, BINANCE_API_SECRET)
       tp_resp = requests.post(
           f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/order",
           headers=_headers(), params=tp_params, timeout=10
       )
       print(f"TP order: {tp_resp.json()}")

       return True
   except Exception as e:
       print(f"SL/TP error: {e}")
   return False

# ─── تنفيذ أوامر Spot ─────────────────────────────────────────────────────────

def place_spot_order(symbol: str, side: str, qty: float) -> dict:
   try:
       params = {
           "symbol":    symbol,
           "side":      side,
           "type":      "MARKET",
           "quantity":  qty,
           "timestamp": _ts()
       }
       params["signature"] = _sign(params, BINANCE_API_SECRET)
       r = requests.post(
           f"{BINANCE_BASE_URL}/api/v3/order",
           headers=_headers(), params=params, timeout=10
       )
       return r.json()
   except Exception as e:
       print(f"Spot order error: {e}")
   return {}

# ─── الدالة الرئيسية للتنفيذ ─────────────────────────────────────────────────

_protected_spot_coins: set = set()

def load_protected_coins():
   global _protected_spot_coins
   _protected_spot_coins = get_spot_existing_coins()
   _protected_spot_coins.discard("USDT")
   print(f"Protected Spot coins: {_protected_spot_coins}")

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
       side  = "BUY" if direction == "LONG" else "SELL"
       order = place_futures_order(symbol, side, qty)

       if order.get("orderId"):
           place_futures_sl_tp(symbol, direction, qty, sl, tp)
           result["executed"] = True
           result["qty"]      = qty
           result["order_id"] = order["orderId"]
           print(f"✅ Futures {direction} {symbol} qty={qty} executed")
       else:
           result["error"] = str(order)

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

       order = place_spot_order(symbol, "BUY", qty)
       if order.get("orderId"):
           result["executed"] = True
           result["qty"]      = qty
           result["order_id"] = order["orderId"]
           print(f"✅ Spot BUY {symbol} qty={qty} executed")
       else:
           result["error"] = str(order)

   return result
