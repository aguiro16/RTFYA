import time
import pytz
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import init_db, get_next_signal_number, save_signal, update_signal_message_id, get_open_signals
from analyzer import scan_all_markets
from monitor import monitor_open_signals
from report import send_daily_report, send_weekly_report
from telegram_bot import send_message, format_signal_message
from execution import execute_signal, load_protected_coins
from config import ENABLE_FUTURES_TRADING, ENABLE_SPOT_TRADING

# ← الحد الأقصى للصفقات المفتوحة في نفس الوقت
MAX_OPEN_POSITIONS = 3

active_symbols = set()

def format_execution_message(signal: dict, exec_result: dict) -> str:
    if exec_result["executed"]:
        return (
            f"⚡ <b>تم التنفيذ التلقائي</b>\n"
            f"📌 {exec_result['symbol']} | {exec_result['market_type']}\n"
            f"{'📈' if exec_result['direction'] == 'LONG' else '📉'} {exec_result['direction']}\n"
            f"🔢 الكمية: <code>{exec_result['qty']}</code>\n"
            f"🆔 Order ID: <code>{exec_result.get('order_id', '—')}</code>"
        )
    else:
        return (
            f"⚠️ <b>لم يتم التنفيذ</b>\n"
            f"📌 {exec_result['symbol']} | {exec_result['market_type']}\n"
            f"❌ السبب: {exec_result.get('error', 'خطأ غير معروف')}"
        )

def run_scan():
    import gc
    print("Running market scan...")
    try:
        open_signals = get_open_signals()
        db_keys = {f"{s['symbol']}_{s['market_type']}" for s in open_signals}
        active_symbols.update(db_keys)

        # ← فحص الحد الأقصى للصفقات المفتوحة
        current_open = len(open_signals)
        if current_open >= MAX_OPEN_POSITIONS:
            print(f"Max open positions reached ({current_open}/{MAX_OPEN_POSITIONS}). Skipping execution.")

        signals = scan_all_markets()
        for signal in signals:
            key = f"{signal['symbol']}_{signal['market_type']}"
            if key in active_symbols or key in db_keys:
                continue

            signal['signal_number'] = get_next_signal_number()
            save_signal(signal)

            msg = format_signal_message(signal)
            message_id = send_message(msg)
            if message_id:
                update_signal_message_id(signal['signal_number'], message_id)

            active_symbols.add(key)
            print(f"Signal #{signal['signal_number']} sent: {signal['symbol']} {signal['direction']}")

            # ← لا ينفذ إذا وصل الحد الأقصى
            should_execute = (
                (signal['market_type'] == 'FUTURES' and ENABLE_FUTURES_TRADING) or
                (signal['market_type'] == 'SPOT'    and ENABLE_SPOT_TRADING)
            )
            if should_execute and current_open < MAX_OPEN_POSITIONS:
                exec_result = execute_signal(signal)
                exec_msg    = format_execution_message(signal, exec_result)
                send_message(exec_msg)
                if exec_result.get("executed"):
                    current_open += 1  # ← تحديث العداد بعد كل تنفيذ
            elif should_execute and current_open >= MAX_OPEN_POSITIONS:
                send_message(
                    f"⏸ <b>تم تأجيل التنفيذ</b>\n"
                    f"📌 {signal['symbol']} | {signal['market_type']}\n"
                    f"⚠️ الحد الأقصى للصفقات المفتوحة ({MAX_OPEN_POSITIONS}) وصل"
                )

    except Exception as e:
        print(f"Error in run_scan: {e}")
    finally:
        gc.collect()

def cleanup_active_symbols():
    open_signals = get_open_signals()
    open_keys    = {f"{s['symbol']}_{s['market_type']}" for s in open_signals}
    closed_keys  = active_symbols - open_keys
    for k in closed_keys:
        active_symbols.discard(k)
    print(f"Cleaned {len(closed_keys)} closed symbols from memory.")

def main():
    print("Fibonacci Signal Bot Starting...")
    init_db()

    load_protected_coins()

    open_signals = get_open_signals()
    for s in open_signals:
        key = f"{s['symbol']}_{s['market_type']}"
        active_symbols.add(key)
    print(f"Loaded {len(active_symbols)} open signals from database.")

    trading_status = []
    if ENABLE_FUTURES_TRADING:
        trading_status.append("✅ Futures مفعّل")
    if ENABLE_SPOT_TRADING:
        trading_status.append("✅ Spot مفعّل")
    if not trading_status:
        trading_status.append("⚠️ التداول الآلي معطّل")

    send_message(
        "🚀 <b>بوت التداول الآلي يعمل الآن!</b>\n"
        "📊 يراقب أعلى 60 عملة\n"
        "⏰ فحص كل 15 دقيقة\n"
        f"📊 الحد الأقصى للصفقات: {MAX_OPEN_POSITIONS}\n"
        "⚡ <b>التداول الآلي:</b>\n" +
        "\n".join(trading_status)
    )

    scheduler = BackgroundScheduler(timezone=pytz.utc)

    scheduler.add_job(
        run_scan,
        IntervalTrigger(minutes=15),
        id="market_scan",
        next_run_time=datetime.datetime.now(pytz.utc)
    )
    scheduler.add_job(
        monitor_open_signals,
        IntervalTrigger(minutes=1),
        id="monitor_signals"
    )
    scheduler.add_job(
        cleanup_active_symbols,
        IntervalTrigger(hours=1),
        id="cleanup"
    )
    scheduler.add_job(
        send_daily_report,
        CronTrigger(hour=8, minute=0, timezone=pytz.utc),
        id="daily_report"
    )
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week='sat', hour=8, minute=0, timezone=pytz.utc),
        id="weekly_report"
    )

    scheduler.start()
    print("Bot is running...")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Bot stopped.")

if __name__ == "__main__":
    main()
