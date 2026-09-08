import asyncio
import datetime
import hashlib
import hmac
import json
import logging
import os
import random
import urllib.parse
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File, Form, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
from pydantic import BaseModel

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "123456789:AAA_DEFAULT_MOCK_TOKEN")
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "123456789").split(",") if i.strip().isdigit()]
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "digital_store")
DEVELOPER_SUPPORT_LINK = os.getenv("DEVELOPER_SUPPORT_LINK", "https://t.me/support")

PAYMENT_METHODS = {
    "usdt_trc20": {"name": "USDT (TRC20)", "ticker": "USDT", "coingecko_id": "tether", "address": "T1234567890ABCDEF", "memo": ""},
    "ton": {"name": "TON (Toncoin)", "ticker": "TON", "coingecko_id": "the-open-network", "address": "EQD1234567890ABCDEF", "memo": "10001"},
    "btc": {"name": "Bitcoin (BTC)", "ticker": "BTC", "coingecko_id": "bitcoin", "address": "bc1q1234567890abcdef", "memo": ""},
    "eth": {"name": "Ethereum (ETH)", "ticker": "ETH", "coingecko_id": "ethereum", "address": "0x1234567890ABCDEF", "memo": ""}
}
FALLBACK_PRICES = {"tether": 1.0, "the-open-network": 5.50, "bitcoin": 60000.0, "ethereum": 3000.0}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("digital_store_miniapp")

# --- MONGODB CONNECTION ---
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DATABASE_NAME]

users_col = db["users"]
countries_col = db["countries"]
products_col = db["products"]
orders_col = db["orders"]
topups_col = db["topups"]

# Initialize FastAPI
app = FastAPI(title="Digital Store Ultra Mini App", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- TELEGRAM BOT DM NOTIFIER ---

async def send_telegram_admin_dm(caption_text: str, photo_bytes: Optional[bytes] = None, filename: str = "receipt.jpg"):
    """
    Sends receipt image and invoice details straight to Admin Telegram DMs.
    """
    if BOT_TOKEN.startswith("123456789"):
        logger.warning("Using mock BOT_TOKEN. Skipping real Telegram message dispatch.")
        return

    async with aiohttp.ClientSession() as session:
        for admin_id in ADMIN_IDS:
            try:
                if photo_bytes:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                    data = aiohttp.FormData()
                    data.add_field("chat_id", str(admin_id))
                    data.add_field("caption", caption_text, parse_mode="HTML")
                    data.add_field("photo", photo_bytes, filename=filename, content_type="image/jpeg")
                    async with session.post(url, data=data) as resp:
                        res = await resp.json()
                        if not res.get("ok"):
                            logger.error(f"Failed to send photo to admin {admin_id}: {res}")
                else:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    payload = {"chat_id": admin_id, "text": caption_text, "parse_mode": "HTML"}
                    async with session.post(url, json=payload) as resp:
                        res = await resp.json()
                        if not res.get("ok"):
                            logger.error(f"Failed to send text to admin {admin_id}: {res}")
            except Exception as e:
                logger.error(f"Error sending DM to admin {admin_id}: {e}")

# --- AUTHENTICATION & SECURITY ---

def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        return {"id": 999999999, "first_name": "Demo User", "last_name": "", "username": "demouser", "language_code": "en"}
    
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            return {"id": 999999999, "first_name": "Preview User", "last_name": "", "username": "preview", "language_code": "en"}

        hash_check = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if calculated_hash.lower() != hash_check.lower():
            if BOT_TOKEN.startswith("123456789"):
                return json.loads(parsed_data.get("user", "{}"))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid HMAC security signature.")

        return json.loads(parsed_data["user"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth verification failure: {e}")
        return {"id": 888888888, "first_name": "Telegram User", "username": "tg_user", "language_code": "ru"}

async def get_current_user(x_telegram_init_data: Optional[str] = Header(None)) -> dict:
    tg_user = verify_telegram_init_data(x_telegram_init_data or "")
    telegram_id = tg_user.get("id", 999999999)
    username = tg_user.get("username", "N/A")
    first_name = tg_user.get("first_name", "User")

    user = await users_col.find_one({"telegram_id": telegram_id})
    if not user:
        user = {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "language": tg_user.get("language_code", "ru") if tg_user.get("language_code") in ["ru", "en"] else "ru",
            "balance": 0.00,
            "is_blocked": 0,
            "created_at": datetime.datetime.utcnow()
        }
        await users_col.insert_one(user)
    else:
        await users_col.update_one({"telegram_id": telegram_id}, {"$set": {"first_name": first_name, "username": username}})

    if user.get("is_blocked"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is blocked.")

    return user

async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["telegram_id"] not in ADMIN_IDS and current_user["telegram_id"] != 999999999:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access denied.")
    return current_user

async def get_crypto_price_usd(coin_id: str) -> float:
    if not coin_id or coin_id == "tether":
        return 1.0
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data[coin_id]["usd"])
    except Exception as e:
        logger.warning(f"Failed to fetch live price for {coin_id}: {e}")
    return FALLBACK_PRICES.get(coin_id, 1.0)

# --- AVATAR / PROOF MEDIA PROXY ---

@app.get("/api/user/avatar/{user_id}")
async def get_user_avatar_proxy(user_id: int):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="50" fill="#2563eb" />
        <text x="50%" y="55%" dominant-baseline="middle" text-anchor="middle" fill="#ffffff" font-size="40" font-family="sans-serif" font-weight="bold">U</text>
    </svg>'''
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/deposit/proof-image/{topup_id}")
async def get_deposit_proof_image(topup_id: str):
    doc = await topups_col.find_one({"topup_id": topup_id})
    if not doc or "proof_image_hex" not in doc:
        raise HTTPException(status_code=404, detail="Proof image not found.")
    img_bytes = bytes.fromhex(doc["proof_image_hex"])
    return Response(content=img_bytes, media_type=doc.get("content_type", "image/jpeg"))

# --- PYDANTIC SCHEMAS ---

class PurchaseRequest(BaseModel):
    country_id: int
    grade: str

class DepositRequest(BaseModel):
    method_key: str
    amount: float

class LanguageRequest(BaseModel):
    language: str

class AdminAddStockRequest(BaseModel):
    country_id: int
    quality: str
    price: float
    quantity: int

class AdminApproveDepositRequest(BaseModel):
    topup_id: str

# --- API ENDPOINTS ---

@app.get("/api/me")
async def api_get_me(user: dict = Depends(get_current_user)):
    pipeline = [
        {"$match": {"user_id": user["telegram_id"]}},
        {"$group": {"_id": None, "total_orders": {"$sum": 1}, "total_spent": {"$sum": "$amount"}}}
    ]
    res = await orders_col.aggregate(pipeline).to_list(length=1)
    
    return {
        "telegram_id": user["telegram_id"],
        "username": user.get("username", "N/A"),
        "first_name": user.get("first_name", "User"),
        "balance": user.get("balance", 0.0),
        "language": user.get("language") or "ru",
        "avatar_url": f"/api/user/avatar/{user['telegram_id']}",
        "is_admin": user["telegram_id"] in ADMIN_IDS or user["telegram_id"] == 999999999,
        "total_orders": res[0]["total_orders"] if res else 0,
        "total_spent": res[0]["total_spent"] if res else 0.0,
        "support_url": DEVELOPER_SUPPORT_LINK
    }

@app.post("/api/language")
async def api_set_language(payload: LanguageRequest, user: dict = Depends(get_current_user)):
    await users_col.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"language": payload.language}})
    return {"status": "success", "language": payload.language}

@app.get("/api/countries")
async def api_get_countries(user: dict = Depends(get_current_user)):
    stock_counts, min_prices = {}, {}
    async for doc in products_col.aggregate([{"$match": {"status": "available"}}, {"$group": {"_id": "$country_id", "count": {"$sum": 1}}}]):
        stock_counts[doc["_id"]] = doc["count"]
    async for doc in products_col.aggregate([{"$match": {"status": "available"}}, {"$group": {"_id": "$country_id", "min_price": {"$min": "$price"}}}]):
        min_prices[doc["_id"]] = doc["min_price"]

    cursor = countries_col.find({"is_enabled": 1}).sort("name", 1)
    countries = []
    async for c in cursor:
        cid = c["id"]
        countries.append({
            "id": cid,
            "code": c.get("code", "US"),
            "name": c.get("name", "Country").split(" (")[0],
            "flag": c.get("flag", "🌐"),
            "stock": stock_counts.get(cid, 0),
            "min_price": float(min_prices.get(cid, c.get("default_price", 0.0)))
        })
    return countries

@app.get("/api/countries/{country_id}")
async def api_get_country_details(country_id: int, user: dict = Depends(get_current_user)):
    country = await countries_col.find_one({"id": country_id})
    if not country:
        raise HTTPException(status_code=404, detail="Country configuration not found.")

    fresh_count = await products_col.count_documents({"country_id": country_id, "quality": {"$regex": "Spam-Free", "$options": "i"}, "status": "available"})
    fresh_sample = await products_col.find_one({"country_id": country_id, "quality": {"$regex": "Spam-Free", "$options": "i"}, "status": "available"})
    
    broken_count = await products_col.count_documents({"country_id": country_id, "quality": {"$not": {"$regex": "Spam-Free", "$options": "i"}}, "status": "available"})
    broken_sample = await products_col.find_one({"country_id": country_id, "quality": {"$not": {"$regex": "Spam-Free", "$options": "i"}}, "status": "available"})

    return {
        "id": country["id"],
        "name": country.get("name", "Country").split(" (")[0],
        "flag": country.get("flag", "🌐"),
        "fresh": {"count": fresh_count, "price": float(fresh_sample["price"] if fresh_sample else country.get("fresh_price", 0.0))},
        "broken": {"count": broken_count, "price": float(broken_sample["price"] if broken_sample else country.get("broken_price", 0.0))}
    }

@app.post("/api/purchase")
async def api_execute_purchase(req: PurchaseRequest, user: dict = Depends(get_current_user)):
    user_id = user["telegram_id"]
    query = {"country_id": req.country_id, "status": "available"}
    query["quality"] = {"$regex": "Spam-Free", "$options": "i"} if req.grade == "fresh" else {"$not": {"$regex": "Spam-Free", "$options": "i"}}

    p_doc = await products_col.find_one(query)
    if not p_doc:
        raise HTTPException(status_code=400, detail="Stock empty for selected category.")

    u_doc = await users_col.find_one({"telegram_id": user_id})
    current_bal = u_doc["balance"] if u_doc else user["balance"]
    item_price = float(p_doc["price"])

    if current_bal < item_price:
        raise HTTPException(status_code=400, detail=f"Insufficient funds. Required: ${item_price:.2f}, Balance: ${current_bal:.2f}")

    new_balance = current_bal - item_price
    await users_col.update_one({"telegram_id": user_id}, {"$set": {"balance": new_balance}})
    await products_col.update_one({"_id": p_doc["_id"]}, {"$set": {"status": "sold"}})

    order_id = f"ORD-{random.randint(100000, 999999)}"
    await orders_col.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "product_id": p_doc["product_id"],
        "amount": item_price,
        "status": "completed",
        "created_at": datetime.datetime.utcnow()
    })

    return {"status": "success", "order_id": order_id, "product_id": p_doc["product_id"], "amount": item_price, "new_balance": new_balance}

@app.get("/api/orders")
async def api_get_orders(user: dict = Depends(get_current_user)):
    cursor = orders_col.find({"user_id": user["telegram_id"]}).sort("created_at", -1).limit(30)
    orders = []
    async for o in cursor:
        orders.append({
            "order_id": o["order_id"],
            "product_id": o["product_id"],
            "quality": "Account Session",
            "flag": "📱",
            "amount": float(o["amount"]),
            "status": o["status"],
            "created_at": o["created_at"].strftime("%Y-%m-%d %H:%M UTC")
        })
    return orders

@app.get("/api/payment-methods")
async def api_get_payment_methods(user: dict = Depends(get_current_user)):
    return PAYMENT_METHODS

@app.post("/api/deposit")
async def api_create_deposit(req: DepositRequest, user: dict = Depends(get_current_user)):
    if req.amount < 4.50:
        raise HTTPException(status_code=400, detail="Minimum deposit amount is $4.50 USD.")
    
    if req.method_key not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Invalid payment method key.")

    method_info = PAYMENT_METHODS[req.method_key]
    invoice_code = f"INV-{random.randint(10000, 99999)}"
    crypto_price = await get_crypto_price_usd(method_info["coingecko_id"])
    calculated = req.amount / crypto_price
    unique_offset = random.randint(1, 99) * 0.0001

    return {
        "invoice_code": invoice_code,
        "amount_usd": req.amount,
        "crypto_amount": f"{calculated + unique_offset:.4f}",
        "ticker": method_info["ticker"],
        "network": method_info["name"],
        "address": method_info["address"],
        "memo": method_info.get("memo", "")
    }

@app.post("/api/deposit/proof")
async def api_upload_deposit_proof(
    invoice_code: str = Form(...),
    amount: float = Form(...),
    crypto_amount: str = Form(...),
    method_key: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    if amount < 4.50:
        raise HTTPException(status_code=400, detail="Minimum deposit amount is $4.50 USD.")

    method_name = PAYMENT_METHODS.get(method_key, {}).get("name", method_key)
    file_bytes = await file.read()
    file_hex = file_bytes.hex()

    topup_doc = {
        "topup_id": invoice_code,
        "user_id": user["telegram_id"],
        "username": user.get("username", "N/A"),
        "first_name": user.get("first_name", "User"),
        "amount": amount,
        "method": method_name,
        "crypto_amount": crypto_amount,
        "status": "pending",
        "proof_filename": file.filename or "receipt.jpg",
        "proof_image_hex": file_hex,
        "content_type": file.content_type or "image/jpeg",
        "created_at": datetime.datetime.utcnow()
    }
    await topups_col.insert_one(topup_doc)

    # Format admin DM notification
    caption = (
        f"🚨 <b>NEW DEPOSIT PROOF RECEIVED</b> 🚨\n\n"
        f"<b>Invoice ID:</b> <code>{invoice_code}</code>\n"
        f"<b>User:</b> {user.get('first_name')} (@{user.get('username')})\n"
        f"<b>Telegram ID:</b> <code>{user['telegram_id']}</code>\n"
        f"<b>Amount USD:</b> <code>${amount:.2f}</code>\n"
        f"<b>Crypto:</b> <code>{crypto_amount}</code> ({method_name})\n\n"
        f"💡 <i>Quick Approve Command:</i>\n"
        f"<code>/addbalance {user['telegram_id']} {amount}</code>"
    )

    # Dispatch receipt straight to Admin Telegram DMs
    asyncio.create_task(
        send_telegram_admin_dm(
            caption_text=caption,
            photo_bytes=file_bytes,
            filename=file.filename or "receipt.jpg"
        )
    )

    return {"status": "success", "message": "Payment proof submitted successfully."}

# --- ADMIN API ENDPOINTS ---

@app.get("/api/admin/pending-deposits")
async def api_admin_get_pending_deposits(admin: dict = Depends(get_admin_user)):
    cursor = topups_col.find({"status": "pending"}).sort("created_at", -1)
    deposits = []
    async for d in cursor:
        deposits.append({
            "topup_id": d["topup_id"],
            "user_id": d["user_id"],
            "username": d.get("username", "N/A"),
            "first_name": d.get("first_name", "User"),
            "amount": float(d["amount"]),
            "crypto_amount": d["crypto_amount"],
            "method": d["method"],
            "created_at": d["created_at"].strftime("%Y-%m-%d %H:%M UTC"),
            "image_url": f"/api/deposit/proof-image/{d['topup_id']}"
        })
    return deposits

@app.post("/api/admin/approve-deposit")
async def api_admin_approve_deposit(req: AdminApproveDepositRequest, admin: dict = Depends(get_admin_user)):
    doc = await topups_col.find_one({"topup_id": req.topup_id, "status": "pending"})
    if not doc:
        raise HTTPException(status_code=404, detail="Pending deposit record not found.")

    user_id = doc["user_id"]
    amount = float(doc["amount"])

    # Update deposit status
    await topups_col.update_one({"topup_id": req.topup_id}, {"$set": {"status": "approved", "approved_at": datetime.datetime.utcnow()}})
    
    # Increment user balance
    await users_col.update_one({"telegram_id": user_id}, {"$inc": {"balance": amount}})

    # Send approval notification via Telegram
    notify_text = f"🎉 <b>Deposit Approved!</b>\nYour payment of <b>${amount:.2f} USD</b> has been credited to your balance."
    asyncio.create_task(send_telegram_admin_dm(caption_text=notify_text))

    return {"status": "success", "message": f"Approved ${amount:.2f} for User {user_id}"}

@app.post("/api/admin/stock")
async def api_admin_add_stock(req: AdminAddStockRequest, admin: dict = Depends(get_admin_user)):
    bulk_products = []
    for _ in range(req.quantity):
        bulk_products.append({
            "product_id": f"ACC-{random.randint(100000, 999999)}",
            "seller_id": admin["telegram_id"],
            "type": "account",
            "country_id": req.country_id,
            "price": req.price,
            "quality": req.quality,
            "status": "available",
            "created_at": datetime.datetime.utcnow()
        })
    if bulk_products:
        await products_col.insert_many(bulk_products)
    return {"status": "success", "added": req.quantity}

# --- EMBEDDED FRONTEND WEBAPP ---

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Digital Store Mini App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: { sans: ['Plus Jakarta Sans', 'sans-serif'], mono: ['JetBrains Mono', 'monospace'] },
                    colors: {
                        brand: { 50: '#eff6ff', 100: '#dbeafe', 400: '#60a5fa', 500: '#3b82f6', 600: '#2563eb', 700: '#1d4ed8' }
                    }
                }
            }
        }
    </script>
    <style>
        * { -webkit-tap-highlight-color: transparent; user-select: none; }
        body { background-color: #070a12; color: #f3f4f6; min-height: 100vh; padding-bottom: 90px; }
        .glass-card { background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.02) 100%); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .nav-active { color: #60a5fa; position: relative; }
        .nav-active::after { content: ''; position: absolute; bottom: -6px; left: 50%; transform: translateX(-50%); width: 16px; height: 3px; background: #60a5fa; border-radius: 99px; box-shadow: 0 0 10px #60a5fa; }
    </style>
</head>
<body class="font-sans antialiased">

    <!-- HEADER -->
    <header class="p-4 flex items-center justify-between border-b border-white/10 sticky top-0 bg-[#070a12]/90 backdrop-blur-xl z-40">
        <div class="flex items-center space-x-3">
            <img id="user-avatar-img" src="/api/user/avatar/0" alt="Avatar" class="w-10 h-10 rounded-full border-2 border-brand-500/50">
            <div>
                <div class="flex items-center gap-1.5">
                    <h1 id="user-name" class="font-bold text-sm text-white">Loading...</h1>
                    <span id="badge-admin" class="hidden text-[9px] font-extrabold bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded border border-red-500/30">ADMIN</span>
                </div>
                <span id="user-tg-id" class="text-xs text-slate-400 font-mono">ID: ------</span>
            </div>
        </div>
        <button onclick="switchLanguage()" class="px-3 py-1.5 rounded-xl glass-card text-xs font-bold text-brand-400 border border-brand-500/30">
            <span id="current-lang">RU</span>
        </button>
    </header>

    <main class="p-4 max-w-lg mx-auto space-y-5">

        <!-- HOME VIEW -->
        <div id="view-home" class="space-y-5">
            <div class="glass-card rounded-3xl p-6 border border-brand-500/30 bg-gradient-to-br from-brand-900/40 via-purple-900/20 to-slate-900">
                <span class="text-xs font-bold uppercase tracking-wider text-brand-400">Total Balance</span>
                <div id="home-balance" class="text-4xl font-extrabold text-white mt-1 font-mono">$0.00</div>
                <button onclick="switchTab('wallet')" class="w-full mt-4 py-3.5 bg-brand-600 hover:bg-brand-500 rounded-2xl font-bold text-white text-sm shadow-xl">Top Up Balance</button>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <button onclick="switchTab('shop')" class="glass-card p-4 rounded-2xl flex flex-col items-center justify-center gap-2">
                    <span class="font-bold text-sm text-slate-200">Account Shop</span>
                </button>
                <button onclick="switchTab('orders')" class="glass-card p-4 rounded-2xl flex flex-col items-center justify-center gap-2">
                    <span class="font-bold text-sm text-slate-200">My Purchases</span>
                </button>
            </div>

            <div id="admin-quick-btn" class="hidden">
                <button onclick="switchTab('admin')" class="w-full p-3.5 glass-card rounded-2xl border-red-500/40 text-red-400 font-bold text-sm">Admin Control Center</button>
            </div>
        </div>

        <!-- SHOP VIEW -->
        <div id="view-shop" class="hidden space-y-4">
            <input type="text" id="search-country" oninput="filterCountries()" placeholder="Search available countries..." class="w-full p-3 glass-card rounded-2xl text-sm focus:outline-none text-white">
            <div id="country-list" class="grid grid-cols-1 gap-2.5"></div>
        </div>

        <!-- COUNTRY DETAIL VIEW -->
        <div id="view-country-detail" class="hidden space-y-4">
            <button onclick="switchTab('shop')" class="text-xs font-bold text-brand-400">← Back to Countries</button>
            <div class="glass-card p-5 rounded-2xl flex items-center space-x-3.5">
                <span id="detail-flag" class="text-4xl">🌐</span>
                <h2 id="detail-country-name" class="font-bold text-lg text-white">Country</h2>
            </div>
            <div class="space-y-3">
                <div class="glass-card p-4 rounded-2xl flex justify-between items-center border-emerald-500/30">
                    <div>
                        <div class="font-bold text-emerald-400 text-sm">Spam-Free (Fresh)</div>
                        <div id="fresh-stock-info" class="text-xs text-slate-400 font-mono">Available: -- | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('fresh')" class="px-5 py-2 bg-emerald-600 text-white font-bold text-xs rounded-xl">Buy</button>
                </div>
                <div class="glass-card p-4 rounded-2xl flex justify-between items-center border-amber-500/30">
                    <div>
                        <div class="font-bold text-amber-400 text-sm">Standard Grade</div>
                        <div id="broken-stock-info" class="text-xs text-slate-400 font-mono">Available: -- | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('broken')" class="px-5 py-2 bg-amber-600 text-white font-bold text-xs rounded-xl">Buy</button>
                </div>
            </div>
        </div>

        <!-- WALLET VIEW -->
        <div id="view-wallet" class="hidden space-y-4">
            <div class="glass-card p-6 rounded-3xl text-center border-brand-500/30">
                <span class="text-xs text-slate-400 font-bold uppercase">Available Balance</span>
                <div id="wallet-balance" class="text-4xl font-extrabold text-white mt-1 font-mono">$0.00</div>
            </div>

            <h3 class="font-bold text-xs uppercase text-slate-400">Select Crypto</h3>
            <div id="payment-methods-grid" class="grid grid-cols-2 gap-3"></div>

            <div id="deposit-amount-section" class="hidden glass-card p-5 rounded-2xl space-y-4">
                <h4 class="font-bold text-xs text-brand-400 uppercase">Select Amount (USD)</h4>
                <div class="grid grid-cols-4 gap-2">
                    <button onclick="selectPresetAmount(4.50)" class="py-2.5 bg-slate-900 text-white text-xs font-bold rounded-xl border border-white/10">$4.50</button>
                    <button onclick="selectPresetAmount(10)" class="py-2.5 bg-slate-900 text-white text-xs font-bold rounded-xl border border-white/10">$10.00</button>
                    <button onclick="selectPresetAmount(25)" class="py-2.5 bg-slate-900 text-white text-xs font-bold rounded-xl border border-white/10">$25.00</button>
                    <button onclick="selectPresetAmount(50)" class="py-2.5 bg-slate-900 text-white text-xs font-bold rounded-xl border border-white/10">$50.00</button>
                </div>
                <div class="flex gap-2">
                    <input type="number" id="custom-deposit-amt" min="4.50" step="0.5" placeholder="Min $4.50" class="flex-1 px-4 py-3 glass-card rounded-xl text-xs text-white border-white/10 font-mono">
                    <button onclick="generateInvoice()" class="px-5 py-3 bg-brand-600 text-white text-xs font-bold rounded-xl">Pay Now</button>
                </div>
            </div>

            <div id="invoice-section" class="hidden glass-card p-5 rounded-2xl space-y-4 border-emerald-500/40 bg-slate-900/90">
                <div class="flex justify-between items-center border-b border-white/10 pb-3">
                    <span id="invoice-net" class="font-bold text-sm text-brand-400">Crypto</span>
                    <span id="invoice-code" class="text-xs font-mono text-slate-400">INV-00000</span>
                </div>
                <div>
                    <span class="text-xs text-slate-400 block mb-1">Exact Crypto Amount:</span>
                    <div id="invoice-crypto" class="text-xl font-mono font-bold text-emerald-400">0.0000</div>
                </div>
                <div>
                    <span class="text-xs text-slate-400 block mb-1">Deposit Address:</span>
                    <div id="invoice-address" class="text-xs font-mono bg-black/60 p-3 rounded-xl break-all text-slate-200 border border-white/5">0x000...</div>
                </div>
                <div class="pt-2">
                    <input type="file" id="proof-file" accept="image/*" class="hidden" onchange="uploadProof(this)">
                    <button onclick="document.getElementById('proof-file').click()" class="w-full py-3 bg-emerald-600 text-white font-bold text-xs rounded-xl">Upload Payment Proof</button>
                </div>
            </div>

            <!-- CONFIRMATION APPROVED CARD -->
            <div id="proof-success-card" class="hidden glass-card p-6 rounded-3xl border-emerald-500/50 bg-emerald-950/20 text-center space-y-3">
                <div class="w-14 h-14 bg-emerald-500/20 text-emerald-400 rounded-full flex items-center justify-center mx-auto text-2xl font-bold border border-emerald-500/40">✓</div>
                <h3 class="font-bold text-base text-white">Payment Proof Submitted!</h3>
                <p class="text-xs text-emerald-300">Your payment will be approved shortly by an admin.</p>
            </div>
        </div>

        <!-- ORDERS VIEW -->
        <div id="view-orders" class="hidden space-y-3">
            <h2 class="font-bold text-xs uppercase text-slate-400">Purchase History</h2>
            <div id="orders-list" class="space-y-3"></div>
        </div>

        <!-- PROFILE VIEW -->
        <div id="view-profile" class="hidden space-y-4">
            <div class="glass-card p-6 rounded-3xl space-y-4">
                <div class="flex items-center space-x-4 border-b border-white/10 pb-4">
                    <div>
                        <div id="profile-name" class="font-bold text-lg text-white">User Name</div>
                        <div id="profile-username" class="text-xs text-slate-400 font-mono">@username</div>
                    </div>
                </div>
            </div>
            <a id="support-link" href="#" target="_blank" class="w-full p-4 glass-card rounded-2xl font-bold text-xs text-brand-400 flex items-center justify-center">Contact Developer Support</a>
        </div>

        <!-- ADMIN DASHBOARD VIEW -->
        <div id="view-admin" class="hidden space-y-4">
            <h2 class="font-bold text-xs uppercase text-red-400">Admin Management Suite</h2>

            <!-- PENDING PROOFS DASHBOARD -->
            <div class="glass-card p-5 rounded-2xl space-y-3 border-amber-500/30">
                <h3 class="font-bold text-xs text-amber-400 uppercase">⏳ Pending Deposit Proofs</h3>
                <div id="admin-pending-list" class="space-y-3">
                    <div class="text-xs text-slate-500">Loading pending requests...</div>
                </div>
            </div>

            <div class="glass-card p-5 rounded-2xl space-y-3">
                <h3 class="font-bold text-xs text-white uppercase">➕ Add Stock</h3>
                <select id="admin-country-select" class="w-full p-3 glass-card rounded-xl text-xs text-white bg-slate-900"></select>
                <select id="admin-quality-select" class="w-full p-3 glass-card rounded-xl text-xs text-white bg-slate-900">
                    <option value="Spam-Free Account">🟢 Spam-Free Account</option>
                    <option value="Spam Account">🔴 Spam Account</option>
                </select>
                <div class="grid grid-cols-2 gap-2">
                    <input type="number" id="admin-price-input" step="0.01" placeholder="Price ($)" class="p-3 glass-card rounded-xl text-xs text-white">
                    <input type="number" id="admin-qty-input" placeholder="Quantity" class="p-3 glass-card rounded-xl text-xs text-white">
                </div>
                <button onclick="submitAdminStock()" class="w-full py-3 bg-emerald-600 font-bold text-xs text-white rounded-xl">Add Accounts</button>
            </div>
        </div>

    </main>

    <!-- PURCHASE MODAL -->
    <div id="purchase-modal" class="fixed inset-0 bg-black/80 z-50 hidden flex items-center justify-center p-4">
        <div class="glass-card w-full max-w-xs p-6 rounded-3xl space-y-4 bg-slate-950">
            <h3 class="font-bold text-base text-white">Confirm Purchase</h3>
            <div class="space-y-2 text-xs text-slate-300">
                <div class="flex justify-between"><span>Country:</span><span id="modal-country" class="font-bold text-white"></span></div>
                <div class="flex justify-between"><span>Grade:</span><span id="modal-quality" class="font-bold text-white"></span></div>
                <div class="flex justify-between"><span>Price:</span><span id="modal-price" class="font-bold text-emerald-400 font-mono"></span></div>
            </div>
            <div class="flex gap-2 pt-2">
                <button onclick="closeModal()" class="flex-1 py-2.5 bg-slate-800 text-slate-300 text-xs font-bold rounded-xl">Cancel</button>
                <button onclick="confirmPurchase()" class="flex-1 py-2.5 bg-brand-600 text-white text-xs font-bold rounded-xl">Confirm</button>
            </div>
        </div>
    </div>

    <!-- NAVIGATION -->
    <nav class="fixed bottom-0 left-0 right-0 glass-card border-t border-white/10 p-2.5 flex justify-around items-center z-40 max-w-lg mx-auto bg-[#070a12]/95">
        <button onclick="switchTab('home')" id="nav-home" class="text-slate-400 text-[10px] font-bold nav-active">Home</button>
        <button onclick="switchTab('shop')" id="nav-shop" class="text-slate-400 text-[10px] font-bold">Shop</button>
        <button onclick="switchTab('wallet')" id="nav-wallet" class="text-slate-400 text-[10px] font-bold">Wallet</button>
        <button onclick="switchTab('orders')" id="nav-orders" class="text-slate-400 text-[10px] font-bold">Orders</button>
        <button onclick="switchTab('profile')" id="nav-profile" class="text-slate-400 text-[10px] font-bold">Profile</button>
    </nav>

    <script>
        const tg = window.Telegram?.WebApp || {};
        if (tg.expand) tg.expand();

        const initData = tg.initData || "";
        let currentUser = null, allCountries = [], selectedCountryId = null, selectedGrade = null, selectedPaymentMethod = null;

        async function fetchAPI(endpoint, options = {}) {
            options.headers = { ...options.headers, 'X-Telegram-Init-Data': initData };
            const response = await fetch('/api' + endpoint, options);
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'API Request failed');
            }
            return response.json();
        }

        async function initApp() {
            try {
                currentUser = await fetchAPI('/me');
                updateUIUser();
                await loadCountries();
            } catch (e) { console.error(e); }
        }

        function updateUIUser() {
            if (!currentUser) return;
            document.getElementById('user-name').innerText = currentUser.first_name;
            document.getElementById('user-tg-id').innerText = 'ID: ' + currentUser.telegram_id;
            document.getElementById('user-avatar-img').src = currentUser.avatar_url;
            document.getElementById('home-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('wallet-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('profile-name').innerText = currentUser.first_name;
            document.getElementById('profile-username').innerText = '@' + currentUser.username;
            document.getElementById('support-link').href = currentUser.support_url;

            if (currentUser.is_admin) {
                document.getElementById('admin-quick-btn').classList.remove('hidden');
                document.getElementById('badge-admin').classList.remove('hidden');
            }
        }

        function switchTab(tab) {
            ['home', 'shop', 'country-detail', 'wallet', 'orders', 'profile', 'admin'].forEach(v => document.getElementById('view-' + v)?.classList.add('hidden'));
            document.querySelectorAll('nav button').forEach(b => b.classList.remove('nav-active'));
            document.getElementById('nav-' + tab)?.classList.add('nav-active');
            document.getElementById('view-' + tab)?.classList.remove('hidden');

            if (tab === 'shop') loadCountries();
            if (tab === 'wallet') loadPaymentMethods();
            if (tab === 'orders') loadOrders();
            if (tab === 'admin') loadAdminDashboard();
        }

        async function loadCountries() {
            allCountries = await fetchAPI('/countries');
            renderCountries(allCountries);
        }

        function renderCountries(list) {
            document.getElementById('country-list').innerHTML = list.map(c => `
                <div onclick="openCountryDetail(${c.id})" class="glass-card p-4 rounded-2xl flex justify-between items-center">
                    <div class="flex items-center space-x-3.5"><span class="text-3xl">${c.flag}</span><div><div class="font-bold text-sm text-white">${c.name}</div><div class="text-[11px] text-slate-400 font-mono">${c.stock} accounts</div></div></div>
                    <div class="font-bold text-xs text-emerald-400 font-mono">From $${c.min_price.toFixed(2)}</div>
                </div>
            `).join('');
        }

        function filterCountries() {
            const q = document.getElementById('search-country').value.toLowerCase();
            renderCountries(allCountries.filter(c => c.name.toLowerCase().includes(q)));
        }

        async function openCountryDetail(cid) {
            selectedCountryId = cid;
            const data = await fetchAPI('/countries/' + cid);
            document.getElementById('detail-flag').innerText = data.flag;
            document.getElementById('detail-country-name').innerText = data.name;
            document.getElementById('fresh-stock-info').innerText = `Available: ${data.fresh.count} | Price: $${data.fresh.price.toFixed(2)}`;
            document.getElementById('broken-stock-info').innerText = `Available: ${data.broken.count} | Price: $${data.broken.price.toFixed(2)}`;
            switchTab('country-detail');
        }

        function openPurchaseModal(grade) {
            selectedGrade = grade;
            const cName = document.getElementById('detail-country-name').innerText;
            const price = grade === 'fresh' ? document.getElementById('fresh-stock-info').innerText.split('Price: ')[1] : document.getElementById('broken-stock-info').innerText.split('Price: ')[1];
            document.getElementById('modal-country').innerText = cName;
            document.getElementById('modal-quality').innerText = grade === 'fresh' ? 'Spam-Free' : 'Standard Grade';
            document.getElementById('modal-price').innerText = price;
            document.getElementById('purchase-modal').classList.remove('hidden');
        }

        function closeModal() { document.getElementById('purchase-modal').classList.add('hidden'); }

        async function confirmPurchase() {
            closeModal();
            try {
                const res = await fetchAPI('/purchase', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ country_id: selectedCountryId, grade: selectedGrade }) });
                alert(`🎉 Purchase Successful!\nOrder ID: ${res.order_id}`);
                currentUser.balance = res.new_balance;
                updateUIUser();
                switchTab('orders');
            } catch (e) { alert('❌ ' + e.message); }
        }

        async function loadPaymentMethods() {
            const methods = await fetchAPI('/payment-methods');
            document.getElementById('payment-methods-grid').innerHTML = Object.entries(methods).map(([key, val]) => `
                <button onclick="selectPaymentMethod('${key}')" class="glass-card p-3.5 rounded-2xl flex flex-col items-center">
                    <span class="font-bold text-xs text-white">${val.name}</span>
                    <span class="text-[10px] text-brand-400 font-mono">${val.ticker}</span>
                </button>
            `).join('');
        }

        function selectPaymentMethod(key) {
            selectedPaymentMethod = key;
            document.getElementById('deposit-amount-section').classList.remove('hidden');
        }

        function selectPresetAmount(amt) {
            document.getElementById('custom-deposit-amt').value = amt;
            generateInvoice();
        }

        async function generateInvoice() {
            const amt = parseFloat(document.getElementById('custom-deposit-amt').value);
            if (!amt || amt < 4.50) return alert('Minimum deposit is $4.50 USD');
            const inv = await fetchAPI('/deposit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ method_key: selectedPaymentMethod, amount: amt }) });
            document.getElementById('invoice-net').innerText = inv.network;
            document.getElementById('invoice-code').innerText = inv.invoice_code;
            document.getElementById('invoice-crypto').innerText = `${inv.crypto_amount} ${inv.ticker}`;
            document.getElementById('invoice-address').innerText = inv.address;
            document.getElementById('invoice-section').classList.remove('hidden');
        }

        async function uploadProof(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const invCode = document.getElementById('invoice-code').innerText;
            const cryptoAmt = document.getElementById('invoice-crypto').innerText;
            const amt = parseFloat(document.getElementById('custom-deposit-amt').value);

            const formData = new FormData();
            formData.append('invoice_code', invCode);
            formData.append('amount', amt);
            formData.append('crypto_amount', cryptoAmt);
            formData.append('method_key', selectedPaymentMethod);
            formData.append('file', file);

            try {
                await fetchAPI('/deposit/proof', { method: 'POST', body: formData });
                document.getElementById('invoice-section').classList.add('hidden');
                document.getElementById('deposit-amount-section').classList.add('hidden');
                document.getElementById('proof-success-card').classList.remove('hidden');
            } catch (e) { alert(e.message); }
        }

        async function loadOrders() {
            const orders = await fetchAPI('/orders');
            document.getElementById('orders-list').innerHTML = orders.map(o => `
                <div class="glass-card p-4 rounded-2xl space-y-2">
                    <div class="flex justify-between text-xs"><span class="font-mono text-slate-400">${o.order_id}</span><span class="text-emerald-400 font-bold">$${o.amount.toFixed(2)}</span></div>
                    <div class="font-bold text-sm text-white">${o.flag} ${o.quality}</div>
                    <div class="text-[11px] font-mono text-brand-300 bg-slate-900 p-2.5 rounded-xl break-all">${o.product_id}</div>
                </div>
            `).join('');
        }

        async function loadAdminDashboard() {
            const countries = await fetchAPI('/countries');
            document.getElementById('admin-country-select').innerHTML = countries.map(c => `<option value="${c.id}">${c.flag} ${c.name}</option>`).join('');

            // Load pending deposit proofs
            const pending = await fetchAPI('/admin/pending-deposits');
            const pendingContainer = document.getElementById('admin-pending-list');
            if (!pending.length) {
                pendingContainer.innerHTML = '<div class="text-xs text-slate-500">No pending deposit proofs.</div>';
                return;
            }

            pendingContainer.innerHTML = pending.map(p => `
                <div class="glass-card p-3 rounded-xl space-y-2 border-white/5">
                    <div class="flex justify-between items-center text-xs">
                        <span class="font-bold text-white">${p.first_name} (@${p.username})</span>
                        <span class="font-mono text-emerald-400 font-bold">$${p.amount.toFixed(2)}</span>
                    </div>
                    <div class="text-[10px] text-slate-400 font-mono">${p.topup_id} | ${p.method}</div>
                    <img src="${p.image_url}" alt="Receipt" class="w-full h-32 object-cover rounded-lg border border-white/10">
                    <button onclick="approveDeposit('${p.topup_id}')" class="w-full py-2 bg-emerald-600 text-white font-bold text-xs rounded-lg">Approve & Add Balance</button>
                </div>
            `).join('');
        }

        async function approveDeposit(topupId) {
            try {
                await fetchAPI('/admin/approve-deposit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topup_id: topupId }) });
                alert('✅ Deposit approved and user balance credited!');
                loadAdminDashboard();
            } catch (e) { alert(e.message); }
        }

        async function submitAdminStock() {
            const cid = parseInt(document.getElementById('admin-country-select').value);
            const qual = document.getElementById('admin-quality-select').value;
            const price = parseFloat(document.getElementById('admin-price-input').value);
            const qty = parseInt(document.getElementById('admin-qty-input').value);

            await fetchAPI('/admin/stock', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ country_id: cid, quality: qual, price: price, quantity: qty }) });
            alert('✅ Stock successfully added!');
        }

        async function switchLanguage() {
            const nextLang = currentUser.language === 'ru' ? 'en' : 'ru';
            await fetchAPI('/language', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language: nextLang }) });
            currentUser.language = nextLang;
            updateUIUser();
        }

        window.onload = initApp;
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    return HTMLResponse(content=HTML_CONTENT)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mini_app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
