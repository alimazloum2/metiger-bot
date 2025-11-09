<<<<<<< HEAD
import os
import logging
import requests
import time
from datetime import datetime, timedelta
from functools import lru_cache
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# ---- config: which coins to show (CoinGecko ids) ----
COINS = [("bitcoin","BTC"), ("ethereum","ETH"), ("binancecoin","BNB"), ("solana","SOL"), ("cardano","ADA")]

# ---- Caching ----
cache = {}
cache_time = {}

def get_cached(key, ttl=60):
    """Get cached data if not expired"""
    if key in cache and time.time() - cache_time.get(key, 0) < ttl:
        return cache[key]
    return None

def set_cache(key, value):
    """Set cache with timestamp"""
    cache[key] = value
    cache_time[key] = time.time()

# ---------- helpers ----------
def money(n):
    if n is None: return "—"
    if n >= 1_000_000_000: return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:     return f"${n/1_000_000:.2f}M"
    if n >= 1_000:         return f"${n/1_000:.2f}K"
    return f"${n:,.2f}"

def arrow(p):
    if p is None: return "—"
    return ("🔺" if p >= 0 else "🔻") + f"{abs(p):.2f}%"

def fetch_markets(ids):
    """Fetch from CoinGecko with caching"""
    cached = get_cached("markets")
    if cached:
        logger.info("Using cached market data")
        return cached
    
    url = "https://api.coingecko.com/api/v3/coins/markets"
    try:
        r = requests.get(url, params={
            "vs_currency": "usd",
            "ids": ",".join(ids),
            "price_change_percentage": "24h"
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        set_cache("markets", data)
        logger.info(f"Fetched {len(data)} coins from CoinGecko")
        return data
    except requests.Timeout:
        logger.error("CoinGecko API timeout")
        raise Exception("API timeout - try again in a moment")
    except requests.HTTPError as e:
        if e.response.status_code == 429:
            logger.warning("Rate limited by CoinGecko")
            raise Exception("Rate limited - wait a minute")
        logger.error(f"HTTP error: {e}")
        raise Exception("API error")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise

def table(rows):
    lines = ["`COIN   PRICE        24h     MCAP`"]
    for c in rows:
        sym = f"{c['symbol'].upper():<4}"
        price = f"${c['current_price']:>10,.2f}"
        ch24 = arrow(c.get("price_change_percentage_24h"))
        mcap = money(c.get("market_cap")).rjust(8)
        lines.append(f"`{sym} {price}  {ch24:>8}  {mcap}`")
    return "\n".join(lines)

# ---------- keyboards ----------
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💹 Price", callback_data="price"),
         InlineKeyboardButton("Refresh", callback_data="refresh")],
        [InlineKeyboardButton("💰 MC", callback_data="mc"),
         InlineKeyboardButton("📈 Gains", callback_data="gains")],
        [InlineKeyboardButton("📊 Charts", callback_data="charts"),
         InlineKeyboardButton("ℹ️ Help", callback_data="helpbtn")]
    ])

def charts_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("BTC chart", url="https://www.tradingview.com/symbols/BTCUSD/")],
        [InlineKeyboardButton("ETH chart", url="https://www.tradingview.com/symbols/ETHUSD/")],
        [InlineKeyboardButton("⬅ Back", callback_data="back")]
    ])

# ---------- commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started bot")
    await update.message.reply_text(
        "🤖 Crypto Price Bot\n\nLive prices from CoinGecko",
        reply_markup=main_kb()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Crypto Price Bot*\n\n"
        "Get live crypto data from CoinGecko.\n\n"
        "*Buttons:*\n"
        "- 💹 *Price*: Live prices for BTC/ETH/SOL/BNB/ADA\n"
        "- 🔄 *Refresh*: Re-fetch prices now\n"
        "- 💰 *MC*: Market caps\n"
        "- 📈 *Gains*: 24h top movers\n"
        "- 📊 *Charts*: Open TradingView links\n"
        "- ℹ️ *Help*: Show this message\n\n"
        "Type */start* to show buttons again."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ---------- button handler ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    
    await q.answer()
    data = (q.data or "").strip()
    logger.info(f"User {user_id} clicked: {data}")

    try:
        if data in ("price", "refresh"):
            ids = [c[0] for c in COINS]
            rows = fetch_markets(ids)
            text = "💰 *Live Prices (USD)*\n\n" + table(rows)
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_kb())

        elif data == "mc":
            ids = [c[0] for c in COINS]
            rows = fetch_markets(ids)
            rows = sorted(rows, key=lambda x: x.get("market_cap") or 0, reverse=True)
            text = "🦁 *Market Caps*\n\n" + "\n".join([
                f"`{r['symbol'].upper():<4}   {money(r.get('market_cap'))}`"
                for r in rows
            ])
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_kb())

        elif data == "gains":
            ids = [c[0] for c in COINS]
            rows = fetch_markets(ids)
            rows = sorted(rows, key=lambda x: x.get("price_change_percentage_24h") or -999, reverse=True)
            text = "📈 *24h Top Movers*\n\n" + "\n".join([
                f"`{r['symbol'].upper():<4}   {arrow(r.get('price_change_percentage_24h'))}`"
                for r in rows
            ])
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_kb())

        elif data == "charts":
            await q.edit_message_text("📊 Choose a chart:", reply_markup=charts_kb())

        elif data == "back":
            await q.edit_message_text("🤖 Crypto Price Bot:", reply_markup=main_kb())

        elif data == "helpbtn":
            help_text = (
                "🤖 *Crypto Price Bot*\n\n"
                "Live crypto prices from CoinGecko.\n\n"
                "*Features:*\n"
                "- 💹 Price: Current prices\n"
                "- 💰 MC: Market capitalizations\n"
                "- 📈 Gains: 24h movers\n"
                "- 📊 Charts: TradingView charts"
            )
            await q.edit_message_text(help_text, parse_mode="Markdown", reply_markup=main_kb())

        else:
            await q.edit_message_text(f"Unknown command: {data}", reply_markup=main_kb())

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}")
        error_msg = f"⚠️ {str(e)}"
        try:
            await q.edit_message_text(error_msg, reply_markup=main_kb())
        except:
            await q.answer(error_msg, show_alert=True)

# ---------- wiring ----------
if __name__ == "__main__":
    logger.info("Starting bot...")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.COMMAND, help_cmd))
    
    logger.info("Bot ready - polling started")
=======
import os
import logging
import requests
import time
from datetime import datetime, timedelta
from functools import lru_cache
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# ---- config: which coins to show (CoinGecko ids) ----
COINS = [("bitcoin","BTC"), ("ethereum","ETH"), ("binancecoin","BNB"), ("solana","SOL"), ("cardano","ADA")]

# ---- Caching ----
cache = {}
cache_time = {}

def get_cached(key, ttl=60):
    """Get cached data if not expired"""
    if key in cache and time.time() - cache_time.get(key, 0) < ttl:
        return cache[key]
    return None

def set_cache(key, value):
    """Set cache with timestamp"""
    cache[key] = value
    cache_time[key] = time.time()

# ---------- helpers ----------
def money(n):
    if n is None: return "—"
    if n >= 1_000_000_000: return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:     return f"${n/1_000_000:.2f}M"
    if n >= 1_000:         return f"${n/1_000:.2f}K"
    return f"${n:,.2f}"

def arrow(p):
    if p is None: return "—"
    return ("🔺" if p >= 0 else "🔻") + f"{abs(p):.2f}%"

def fetch_markets(ids):
    """Fetch from CoinGecko with caching"""
    cached = get_cached("markets")
    if cached:
        logger.info("Using cached market data")
        return cached
    
    url = "https://api.coingecko.com/api/v3/coins/markets"
    try:
        r = requests.get(url, params={
            "vs_currency": "usd",
            "ids": ",".join(ids),
            "price_change_percentage": "24h"
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        set_cache("markets", data)
        logger.info(f"Fetched {len(data)} coins from CoinGecko")
        return data
    except requests.Timeout:
        logger.error("CoinGecko API timeout")
        raise Exception("API timeout - try again in a moment")
    except requests.HTTPError as e:
        if e.response.status_code == 429:
            logger.warning("Rate limited by CoinGecko")
            raise Exception("Rate limited - wait a minute")
        logger.error(f"HTTP error: {e}")
        raise Exception("API error")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise

def table(rows):
    lines = ["`COIN   PRICE        24h     MCAP`"]
    for c in rows:
        sym = f"{c['symbol'].upper():<4}"
        price = f"${c['current_price']:>10,.2f}"
        ch24 = arrow(c.get("price_change_percentage_24h"))
        mcap = money(c.get("market_cap")).rjust(8)
        lines.append(f"`{sym} {price}  {ch24:>8}  {mcap}`")
    return "\n".join(lines)

# ---------- keyboards ----------
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧯 Price", callback_data="price"),
         InlineKeyboardButton("Refresh", callback_data="refresh")],
        [InlineKeyboardButton("💰 MC", callback_data="mc"),
         InlineKeyboardButton("📈 Gains", callback_data="gains")],
        [InlineKeyboardButton("📊 Charts", callback_data="charts"),
         InlineKeyboardButton("ℹ️ Help", callback_data="helpbtn")]
    ])

def charts_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("BTC chart", url="https://www.tradingview.com/symbols/BTCUSD/")],
        [InlineKeyboardButton("ETH chart", url="https://www.tradingview.com/symbols/ETHUSD/")],
        [InlineKeyboardButton("⬅ Back", callback_data="back")]
    ])

# ---------- commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started bot")
    await update.message.reply_text(
        "🤖 Crypto Price Bot\n\nLive prices from CoinGecko",
        reply_markup=main_kb()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Crypto Price Bot*\n\n"
        "Get live crypto data from CoinGecko.\n\n"
        "*Buttons:*\n"
        "- 🧯 *Price*: Live prices for BTC/ETH/SOL/BNB/ADA\n"
        "- 🔄 *Refresh*: Re-fetch prices now\n"
        "- 💰 *MC*: Market caps\n"
        "- 📈 *Gains*: 24h top movers\n"
        "- 📊 *Charts*: Open TradingView links\n"
        "- ℹ️ *Help*: Show this message\n\n"
        "Type */start* to show buttons again."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ---------- button handler ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    
    await q.answer()
    data = (q.data or "").strip()
    logger.info(f"User {user_id} clicked: {data}")

    try:
        if data in ("price", "refresh"):
            ids = [c[0] for c in COINS]
            rows = fetch_markets(ids)
            text = "💰 *Live Prices (USD)*\n\n" + table(rows)
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_kb())

        elif data == "mc":
            ids = [c[0] for c in COINS]
            rows = fetch_markets(ids)
            rows = sorted(rows, key=lambda x: x.get("market_cap") or 0, reverse=True)
            text = "🏦 *Market Caps*\n\n" + "\n".join([
                f"`{r['symbol'].upper():<4}   {money(r.get('market_cap'))}`"
                for r in rows
            ])
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_kb())

        elif data == "gains":
            ids = [c[0] for c in COINS]
            rows = fetch_markets(ids)
            rows = sorted(rows, key=lambda x: x.get("price_change_percentage_24h") or -999, reverse=True)
            text = "📈 *24h Top Movers*\n\n" + "\n".join([
                f"`{r['symbol'].upper():<4}   {arrow(r.get('price_change_percentage_24h'))}`"
                for r in rows
            ])
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_kb())

        elif data == "charts":
            await q.edit_message_text("📊 Choose a chart:", reply_markup=charts_kb())

        elif data == "back":
            await q.edit_message_text("🤖 Crypto Price Bot:", reply_markup=main_kb())

        elif data == "helpbtn":
            help_text = (
                "🤖 *Crypto Price Bot*\n\n"
                "Live crypto prices from CoinGecko.\n\n"
                "*Features:*\n"
                "- 🧯 Price: Current prices\n"
                "- 💰 MC: Market capitalizations\n"
                "- 📈 Gains: 24h movers\n"
                "- 📊 Charts: TradingView charts"
            )
            await q.edit_message_text(help_text, parse_mode="Markdown", reply_markup=main_kb())

        else:
            await q.edit_message_text(f"Unknown command: {data}", reply_markup=main_kb())

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}")
        error_msg = f"⚠️ {str(e)}"
        try:
            await q.edit_message_text(error_msg, reply_markup=main_kb())
        except:
            await q.answer(error_msg, show_alert=True)

# ---------- wiring ----------
if __name__ == "__main__":
    logger.info("Starting bot...")
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.COMMAND, help_cmd))
    
    logger.info("Bot ready - polling started")
>>>>>>> 8bb44d2a440526cee99d7f6119203e0c019ce4e7
    app.run_polling()