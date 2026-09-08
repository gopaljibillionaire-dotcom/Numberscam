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

from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
from pydantic import BaseModel

# --- IMPORT EXISTING BOT CONFIGURATION ---
from config import (
    BOT_TOKEN,
    ADMIN_IDS,
    MONGO_URI,
    DATABASE_NAME,
    DEVELOPER_SUPPORT_LINK,
    PAYMENT_METHODS,
    FALLBACK_PRICES,
    TEXTS,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger("digital_store_miniapp")

# --- MONGODB CONNECTION ---
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DATABASE_NAME]

users_col = db["users"]
countries_col = db["countries"]
products_col = db["products"]
orders_col = db["orders"]
topups_col = db["topups"]

# Initialize FastAPI App
app = FastAPI(title="Digital Store Mini App", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- AUTHENTICATION & SECURITY ---

def verify_telegram_init_data(init_data: str) -> dict:
    """
    Validates Telegram WebApp initData using HMAC-SHA256 according to Telegram's protocol.
    Returns parsed user dict if valid; raises HTTP 401 otherwise.
    """
    if not init_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Telegram authorization initData.")
    
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization payload.")

        hash_check = parsed_data.pop("hash")
        
        # Sort key-value pairs alphabetically
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        # WebApp secret key calculation: HMAC-SHA256 of bot_token with key "WebAppData"
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if calculated_hash.lower() != hash_check.lower():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid HMAC security signature.")

        if "user" not in parsed_data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user field in authorization payload.")

        user_data = json.loads(parsed_data["user"])
        return user_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth verification failure: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed.")

async def get_current_user(x_telegram_init_data: Optional[str] = Header(None)) -> dict:
    if not x_telegram_init_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing.")
    
    tg_user = verify_telegram_init_data(x_telegram_init_data)
    telegram_id = tg_user.get("id")
    username = tg_user.get("username")
    first_name = tg_user.get("first_name")

    user = await users_col.find_one({"telegram_id": telegram_id})
    if not user:
        user = {
            "telegram_id": telegram_id,
            "username": username or "N/A",
            "first_name": first_name or "User",
            "language": tg_user.get("language_code", "ru") if tg_user.get("language_code") in ["ru", "en"] else "ru",
            "balance": 0.0,
            "is_blocked": 0,
            "created_at": datetime.datetime.utcnow()
        }
        await users_col.insert_one(user)

    if user.get("is_blocked"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is blocked.")

    return user

async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["telegram_id"] not in ADMIN_IDS:
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
        logger.warning(f"Failed to fetch live price for {coin_id}: {e}. Using fallback.")
    return FALLBACK_PRICES.get(coin_id, 1.0)

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

# --- API ENDPOINTS ---

@app.get("/api/me")
async def api_get_me(user: dict = Depends(get_current_user)):
    pipeline = [
        {"$match": {"user_id": user["telegram_id"]}},
        {"$group": {"_id": None, "total_orders": {"$sum": 1}, "total_spent": {"$sum": "$amount"}}}
    ]
    res = await orders_col.aggregate(pipeline).to_list(length=1)
    
    total_orders = res[0]["total_orders"] if res else 0
    total_spent = res[0]["total_spent"] if res else 0.0

    return {
        "telegram_id": user["telegram_id"],
        "username": user.get("username", "N/A"),
        "first_name": user.get("first_name", "User"),
        "balance": user.get("balance", 0.0),
        "language": user.get("language") or "ru",
        "is_admin": user["telegram_id"] in ADMIN_IDS,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "support_url": DEVELOPER_SUPPORT_LINK
    }

@app.post("/api/language")
async def api_set_language(payload: LanguageRequest, user: dict = Depends(get_current_user)):
    if payload.language not in ["ru", "en"]:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    await users_col.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"language": payload.language}})
    return {"status": "success", "language": payload.language}

@app.get("/api/countries")
async def api_get_countries(user: dict = Depends(get_current_user)):
    # Optimized query to get count of available items grouped by country
    stock_counts = {}
    pipeline = [
        {"$match": {"status": "available"}},
        {"$group": {"_id": "$country_id", "count": {"$sum": 1}}}
    ]
    async for doc in products_col.aggregate(pipeline):
        stock_counts[doc["_id"]] = doc["count"]

    min_prices = {}
    min_price_pipeline = [
        {"$match": {"status": "available"}},
        {"$group": {"_id": "$country_id", "min_price": {"$min": "$price"}}}
    ]
    async for doc in products_col.aggregate(min_price_pipeline):
        min_prices[doc["_id"]] = doc["min_price"]

    cursor = countries_col.find({"is_enabled": 1}).sort("name", 1)
    countries = []
    async for c in cursor:
        cid = c["id"]
        countries.append({
            "id": cid,
            "code": c["code"],
            "name": c["name"].split(" (")[0],
            "flag": c["flag"],
            "stock": stock_counts.get(cid, 0),
            "min_price": min_prices.get(cid, 0.0)
        })
    return countries

@app.get("/api/countries/{country_id}")
async def api_get_country_details(country_id: int, user: dict = Depends(get_current_user)):
    country = await countries_col.find_one({"id": country_id, "is_enabled": 1})
    if not country:
        raise HTTPException(status_code=404, detail="Country not found or disabled.")

    fresh_count = await products_col.count_documents({
        "country_id": country_id,
        "quality": {"$regex": "Spam-Free", "$options": "i"},
        "status": "available"
    })
    
    fresh_sample = await products_col.find_one({
        "country_id": country_id,
        "quality": {"$regex": "Spam-Free", "$options": "i"},
        "status": "available"
    })

    broken_count = await products_col.count_documents({
        "country_id": country_id,
        "quality": {"$not": {"$regex": "Spam-Free", "$options": "i"}},
        "status": "available"
    })

    broken_sample = await products_col.find_one({
        "country_id": country_id,
        "quality": {"$not": {"$regex": "Spam-Free", "$options": "i"}},
        "status": "available"
    })

    return {
        "id": country["id"],
        "name": country["name"].split(" (")[0],
        "flag": country["flag"],
        "fresh": {
            "count": fresh_count,
            "price": fresh_sample["price"] if fresh_sample else 0.0
        },
        "broken": {
            "count": broken_count,
            "price": broken_sample["price"] if broken_sample else 0.0
        }
    }

@app.post("/api/purchase")
async def api_execute_purchase(req: PurchaseRequest, user: dict = Depends(get_current_user)):
    user_id = user["telegram_id"]
    
    query = {"country_id": req.country_id, "status": "available"}
    if req.grade == "fresh":
        query["quality"] = {"$regex": "Spam-Free", "$options": "i"}
    else:
        query["quality"] = {"$not": {"$regex": "Spam-Free", "$options": "i"}}

    async with await mongo_client.start_session() as session:
        async with session.start_transaction():
            p_doc = await products_col.find_one(query, session=session)
            if not p_doc:
                raise HTTPException(status_code=400, detail="Stock empty or item already sold out!")

            u_doc = await users_col.find_one({"telegram_id": user_id}, session=session)
            if u_doc["balance"] < p_doc["price"]:
                raise HTTPException(status_code=400, detail=f"Insufficient funds. Required: ${p_doc['price']:.2f}")

            new_balance = u_doc["balance"] - p_doc["price"]
            await users_col.update_one({"telegram_id": user_id}, {"$set": {"balance": new_balance}}, session=session)
            await products_col.update_one({"product_id": p_doc["product_id"]}, {"$set": {"status": "sold"}}, session=session)

            order_id = f"ORD-{random.randint(100000, 999999)}"
            await orders_col.insert_one({
                "order_id": order_id,
                "user_id": user_id,
                "product_id": p_doc["product_id"],
                "amount": p_doc["price"],
                "status": "completed",
                "created_at": datetime.datetime.utcnow()
            }, session=session)

            return {
                "status": "success",
                "order_id": order_id,
                "product_id": p_doc["product_id"],
                "amount": p_doc["price"],
                "new_balance": new_balance
            }

@app.get("/api/orders")
async def api_get_orders(user: dict = Depends(get_current_user)):
    cursor = orders_col.find({"user_id": user["telegram_id"]}).sort("created_at", -1).limit(20)
    orders = []
    async for o in cursor:
        prod = await products_col.find_one({"product_id": o["product_id"]})
        quality = prod["quality"] if prod and "quality" in prod else "Standard Account"
        country_flag = "📱"
        if prod:
            c = await countries_col.find_one({"id": prod.get("country_id")})
            if c: country_flag = c.get("flag", "📱")

        orders.append({
            "order_id": o["order_id"],
            "product_id": o["product_id"],
            "quality": quality,
            "flag": country_flag,
            "amount": o["amount"],
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
    coin_amount = f"{calculated + unique_offset:.4f}"

    return {
        "invoice_code": invoice_code,
        "amount_usd": req.amount,
        "crypto_amount": coin_amount,
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
    method_name = PAYMENT_METHODS.get(method_key, {}).get("name", method_key)

    topup_doc = {
        "topup_id": invoice_code,
        "user_id": user["telegram_id"],
        "amount": amount,
        "method": method_name,
        "crypto_amount": crypto_amount,
        "status": "pending",
        "proof_filename": file.filename,
        "created_at": datetime.datetime.utcnow()
    }
    await topups_col.insert_one(topup_doc)

    # Forward photo proof to Admins via Telegram API session if reachable
    try:
        content = await file.read()
        bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        admin_text = (
            f"🚨 <b>NEW MINI APP TOP-UP PROOF</b>\n"
            f"═══════════════════════\n\n"
            f"🧾 <b>Invoice:</b> <code>{invoice_code}</code>\n"
            f"👤 <b>User ID:</b> <code>{user['telegram_id']}</code>\n"
            f"🌐 <b>Network:</b> {method_name}\n"
            f"💎 <b>Crypto Amount:</b> <code>{crypto_amount}</code>\n"
            f"💵 <b>USD Value:</b> <code>${amount:.2f}</code>"
        )
        for admin_id in ADMIN_IDS:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(admin_id))
            form.add_field("caption", admin_text)
            form.add_field("parse_mode", "HTML")
            form.add_field("photo", content, filename=file.filename)
            
            async with aiohttp.ClientSession() as session:
                await session.post(bot_url, data=form)
    except Exception as e:
        logger.error(f"Failed sending admin notification: {e}")

    return {"status": "success", "message": "Proof uploaded successfully. Pending admin review."}

# --- ADMIN API ENDPOINTS ---

@app.get("/api/admin/stats")
async def api_admin_stats(admin: dict = Depends(get_admin_user)):
    try:
        stats = await db.command("dbStats")
        data_size_mb = stats.get("dataSize", 0) / (1024 * 1024)
        storage_size_mb = stats.get("storageSize", 0) / (1024 * 1024)
        index_size_mb = stats.get("indexSize", 0) / (1024 * 1024)
        max_storage_mb = 512.0
        
        return {
            "data_size_mb": round(data_size_mb, 2),
            "storage_size_mb": round(storage_size_mb, 2),
            "index_size_mb": round(index_size_mb, 2),
            "available_space_mb": round(max(0.0, max_storage_mb - storage_size_mb), 2),
            "collections": stats.get("collections", 0),
            "total_users": await users_col.count_documents({}),
            "total_products": await products_col.count_documents({}),
            "available_stock": await products_col.count_documents({"status": "available"}),
            "total_orders": await orders_col.count_documents({})
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/stock")
async def api_admin_add_stock(req: AdminAddStockRequest, admin: dict = Depends(get_admin_user)):
    c_doc = await countries_col.find_one({"id": req.country_id})
    if not c_doc:
        raise HTTPException(status_code=404, detail="Country ID invalid.")

    country_code = c_doc["code"].upper()
    bulk_products = []
    for _ in range(req.quantity):
        rand_num = random.randint(100000, 999999)
        prod_id = f"{country_code}-{rand_num}"
        bulk_products.append({
            "product_id": prod_id,
            "seller_id": admin["telegram_id"],
            "type": "account",
            "country_id": req.country_id,
            "price": req.price,
            "quality": req.quality,
            "bin_link": "",
            "status": "available",
            "created_at": datetime.datetime.utcnow()
        })

    if bulk_products:
        await products_col.insert_many(bulk_products)

    return {"status": "success", "added": req.quantity}

@app.get("/api/admin/export")
async def api_admin_export_stock(admin: dict = Depends(get_admin_user)):
    pipeline = [
        {"$lookup": {"from": "countries", "localField": "country_id", "foreignField": "id", "as": "country_info"}},
        {"$unwind": "$country_info"},
        {"$sort": {"country_info.name": 1, "quality": 1}}
    ]
    products = await products_col.aggregate(pipeline).to_list(length=None)

    output_lines = ["==========================================", "       FULL STOCK DATABASE EXPORT         ", "==========================================\n"]
    current_country = ""

    for p in products:
        c_name = p["country_info"]["name"]
        flag = p["country_info"]["flag"]
        if c_name != current_country:
            current_country = c_name
            output_lines.append(f"\n--- {flag} {current_country.upper()} ---")
        output_lines.append(f"ID: {p['product_id']} | Quality: {p['quality']} | Price: ${p['price']:.2f} | Status: {p['status']}")

    return {"export_text": "\n".join(output_lines)}

# --- EMBEDDED ULTRA-PREMIUM FRONTEND WEBAPP ---

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Digital Store Mini App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/@lucide/web"></script>
    <style>
        * { font-family: 'Plus Jakarta Sans', sans-serif; -webkit-tap-highlight-color: transparent; }
        body { background-color: var(--tg-theme-bg-color, #0f172a); color: var(--tg-theme-text-color, #f8fafc); min-height: 100vh; padding-bottom: 90px; }
        .glass-card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .glow-accent { box-shadow: 0 0 25px -5px rgba(59, 130, 246, 0.5); }
        .nav-active { color: #3b82f6; transform: translateY(-2px); }
        .skeleton { background: linear-gradient(90deg, #1e293b 25%, #334155 50%, #1e293b 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; }
        @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
    </style>
</head>
<body>
    <header class="p-4 flex items-center justify-between border-b border-slate-800/80 sticky top-0 bg-slate-900/80 backdrop-blur-md z-40">
        <div class="flex items-center space-x-3">
            <div id="user-avatar" class="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center font-bold text-lg text-white shadow-md">U</div>
            <div>
                <h1 id="user-name" class="font-bold text-sm tracking-tight text-white leading-none">Loading...</h1>
                <span id="user-tg-id" class="text-xs text-slate-400 font-mono">ID: ------</span>
            </div>
        </div>
        <button onclick="switchLanguage()" class="px-2.5 py-1 rounded-lg glass-card text-xs font-semibold text-blue-400 border border-blue-500/30 flex items-center gap-1">
            <i data-lucide="globe" class="w-3.5 h-3.5"></i> <span id="current-lang">RU</span>
        </button>
    </header>

    <main class="p-4 max-w-lg mx-auto">
        <div id="view-home" class="space-y-5">
            <div class="glass-card rounded-2xl p-5 relative overflow-hidden glow-accent border border-blue-500/20 bg-gradient-to-br from-slate-800 via-slate-900 to-blue-950/40">
                <div class="flex justify-between items-start mb-4">
                    <div>
                        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Total Wallet Balance</span>
                        <div id="home-balance" class="text-3xl font-extrabold text-white mt-1">$0.00</div>
                    </div>
                    <span class="p-2 bg-blue-500/10 rounded-xl border border-blue-500/20 text-blue-400"><i data-lucide="wallet"></i></span>
                </div>
                <button onclick="switchTab('wallet')" class="w-full py-3 bg-blue-600 hover:bg-blue-500 active:scale-95 transition-all rounded-xl font-semibold text-white text-sm shadow-lg flex items-center justify-center gap-2">
                    <i data-lucide="plus-circle" class="w-4 h-4"></i> Deposit Funds
                </button>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <button onclick="switchTab('shop')" class="glass-card p-4 rounded-xl flex flex-col items-center justify-center gap-2 hover:border-blue-500/40 active:scale-95 transition-all">
                    <div class="p-3 bg-blue-500/10 rounded-full text-blue-400"><i data-lucide="shopping-bag" class="w-6 h-6"></i></div>
                    <span class="font-bold text-sm">Buy Accounts</span>
                </button>
                <button onclick="switchTab('orders')" class="glass-card p-4 rounded-xl flex flex-col items-center justify-center gap-2 hover:border-blue-500/40 active:scale-95 transition-all">
                    <div class="p-3 bg-emerald-500/10 rounded-full text-emerald-400"><i data-lucide="package" class="w-6 h-6"></i></div>
                    <span class="font-bold text-sm">My Orders</span>
                </button>
            </div>

            <div id="admin-quick-btn" class="hidden">
                <button onclick="switchTab('admin')" class="w-full p-3 glass-card rounded-xl border-red-500/30 text-red-400 font-bold text-sm flex items-center justify-center gap-2">
                    <i data-lucide="shield-alert" class="w-4 h-4"></i> Admin Control Dashboard
                </button>
            </div>
        </div>

        <div id="view-shop" class="hidden space-y-4">
            <div class="relative">
                <i data-lucide="search" class="w-4 h-4 absolute left-3.5 top-3.5 text-slate-400"></i>
                <input type="text" id="search-country" oninput="filterCountries()" placeholder="Search available countries..." class="w-full pl-10 pr-4 py-2.5 glass-card rounded-xl text-sm focus:outline-none focus:border-blue-500 text-white placeholder-slate-500">
            </div>
            <div id="country-list" class="grid grid-cols-1 gap-2.5">
                <div class="skeleton h-16 rounded-xl w-full"></div>
                <div class="skeleton h-16 rounded-xl w-full"></div>
                <div class="skeleton h-16 rounded-xl w-full"></div>
            </div>
        </div>

        <div id="view-country-detail" class="hidden space-y-4">
            <button onclick="switchTab('shop')" class="text-xs font-semibold text-blue-400 flex items-center gap-1 mb-2">
                <i data-lucide="arrow-left" class="w-4 h-4"></i> Back to Countries
            </button>
            <div class="glass-card p-4 rounded-xl flex items-center justify-between border-blue-500/30">
                <div class="flex items-center space-x-3">
                    <span id="detail-flag" class="text-3xl">🇦🇫</span>
                    <h2 id="detail-country-name" class="font-bold text-lg text-white">Country</h2>
                </div>
            </div>

            <div class="space-y-3">
                <div class="glass-card p-4 rounded-xl flex items-center justify-between border-emerald-500/30">
                    <div>
                        <div class="flex items-center gap-1.5 font-bold text-emerald-400 text-sm">
                            <i data-lucide="shield-check" class="w-4 h-4"></i> Spam-Free (Fresh)
                        </div>
                        <div id="fresh-stock-info" class="text-xs text-slate-400 mt-1">Available: 0 | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('fresh')" id="btn-buy-fresh" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-lg active:scale-95 transition-all">Buy</button>
                </div>

                <div class="glass-card p-4 rounded-xl flex items-center justify-between border-rose-500/30">
                    <div>
                        <div class="flex items-center gap-1.5 font-bold text-rose-400 text-sm">
                            <i data-lucide="alert-triangle" class="w-4 h-4"></i> Spam (Broken)
                        </div>
                        <div id="broken-stock-info" class="text-xs text-slate-400 mt-1">Available: 0 | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('broken')" id="btn-buy-broken" class="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs rounded-lg active:scale-95 transition-all">Buy</button>
                </div>
            </div>
        </div>

        <div id="view-wallet" class="hidden space-y-4">
            <div class="glass-card p-5 rounded-2xl text-center border-blue-500/30">
                <span class="text-xs text-slate-400 font-semibold uppercase">Current Balance</span>
                <div id="wallet-balance" class="text-3xl font-extrabold text-white mt-1">$0.00</div>
            </div>

            <h3 class="font-bold text-sm text-slate-300">Select Deposit Method</h3>
            <div id="payment-methods-grid" class="grid grid-cols-2 gap-2.5"></div>

            <div id="deposit-amount-section" class="hidden glass-card p-4 rounded-xl space-y-3">
                <h4 class="font-bold text-xs text-blue-400 uppercase tracking-wider">Select Amount (USD)</h4>
                <div class="grid grid-cols-4 gap-2">
                    <button onclick="selectPresetAmount(4.5)" class="py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg border border-slate-700">$4.50</button>
                    <button onclick="selectPresetAmount(10)" class="py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg border border-slate-700">$10.00</button>
                    <button onclick="selectPresetAmount(15)" class="py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg border border-slate-700">$15.00</button>
                    <button onclick="selectPresetAmount(25)" class="py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg border border-slate-700">$25.00</button>
                </div>
                <div class="flex gap-2">
                    <input type="number" id="custom-deposit-amt" min="4.5" step="0.5" placeholder="Custom Amount ($)" class="flex-1 px-3 py-2 glass-card rounded-lg text-xs text-white focus:outline-none border-slate-700">
                    <button onclick="generateInvoice()" class="px-4 py-2 bg-blue-600 text-white text-xs font-bold rounded-lg hover:bg-blue-500">Pay</button>
                </div>
            </div>

            <div id="invoice-section" class="hidden glass-card p-5 rounded-xl space-y-4 border-blue-500/40">
                <div class="flex justify-between items-center border-b border-slate-800 pb-3">
                    <span id="invoice-net" class="font-bold text-sm text-blue-400">USDT</span>
                    <span id="invoice-code" class="text-xs font-mono text-slate-400">INV-00000</span>
                </div>
                <div>
                    <span class="text-xs text-slate-400">Exact Amount to Send:</span>
                    <div id="invoice-crypto" class="text-lg font-mono font-bold text-emerald-400">0.0000 USDT</div>
                </div>
                <div>
                    <span class="text-xs text-slate-400">Wallet Address:</span>
                    <div id="invoice-address" class="text-xs font-mono bg-slate-900/80 p-2.5 rounded-lg break-all text-slate-200 mt-1 select-all">0x000...</div>
                </div>
                <div class="space-y-2 pt-2">
                    <input type="file" id="proof-file" accept="image/*" class="hidden" onchange="uploadProof(this)">
                    <button onclick="document.getElementById('proof-file').click()" class="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-lg transition-all flex items-center justify-center gap-2">
                        <i data-lucide="upload" class="w-4 h-4"></i> Upload Payment Proof
                    </button>
                </div>
            </div>
        </div>

        <div id="view-orders" class="hidden space-y-3">
            <h2 class="font-bold text-sm text-slate-300">Order History</h2>
            <div id="orders-list" class="space-y-2.5"></div>
        </div>

        <div id="view-profile" class="hidden space-y-4">
            <div class="glass-card p-5 rounded-2xl space-y-3 border-blue-500/20">
                <div class="flex items-center space-x-3 border-b border-slate-800 pb-3">
                    <div id="profile-avatar" class="w-12 h-12 rounded-full bg-blue-600 flex items-center justify-center font-bold text-xl text-white">U</div>
                    <div>
                        <div id="profile-name" class="font-bold text-base text-white">User Name</div>
                        <div id="profile-username" class="text-xs text-slate-400">@username</div>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-2 text-xs pt-1">
                    <div class="bg-slate-900/50 p-2.5 rounded-xl border border-slate-800/80">
                        <span class="text-slate-400 block">Total Orders</span>
                        <span id="profile-total-orders" class="font-bold text-base text-white">0</span>
                    </div>
                    <div class="bg-slate-900/50 p-2.5 rounded-xl border border-slate-800/80">
                        <span class="text-slate-400 block">Total Spent</span>
                        <span id="profile-total-spent" class="font-bold text-base text-emerald-400">$0.00</span>
                    </div>
                </div>
            </div>
            <a id="support-link" href="#" target="_blank" class="w-full p-3 glass-card rounded-xl font-semibold text-xs text-blue-400 border-blue-500/30 flex items-center justify-center gap-2">
                <i data-lucide="headphone-off" class="w-4 h-4"></i> Contact Developer Support
            </a>
        </div>

        <div id="view-admin" class="hidden space-y-4">
            <h2 class="font-bold text-sm text-red-400 flex items-center gap-1.5"><i data-lucide="shield" class="w-4 h-4"></i> Admin Panel</h2>
            <div class="grid grid-cols-2 gap-2.5 text-xs">
                <div class="glass-card p-3 rounded-xl border-slate-800">
                    <span class="text-slate-400 block">Users</span>
                    <span id="admin-users" class="font-bold text-sm text-white">0</span>
                </div>
                <div class="glass-card p-3 rounded-xl border-slate-800">
                    <span class="text-slate-400 block">Available Stock</span>
                    <span id="admin-stock" class="font-bold text-sm text-emerald-400">0</span>
                </div>
            </div>

            <div class="glass-card p-4 rounded-xl space-y-3">
                <h3 class="font-bold text-xs text-white">➕ Add Bulk Stock</h3>
                <select id="admin-country-select" class="w-full p-2 glass-card rounded-lg text-xs text-white border-slate-800"></select>
                <select id="admin-quality-select" class="w-full p-2 glass-card rounded-lg text-xs text-white border-slate-800">
                    <option value="Spam-Free Account">🟢 Spam-Free Account</option>
                    <option value="Spam Account">🔴 Spam Account</option>
                </select>
                <input type="number" id="admin-price-input" step="0.01" placeholder="Price ($)" class="w-full p-2 glass-card rounded-lg text-xs text-white border-slate-800">
                <input type="number" id="admin-qty-input" placeholder="Quantity" class="w-full p-2 glass-card rounded-lg text-xs text-white border-slate-800">
                <button onclick="submitAdminStock()" class="w-full py-2 bg-emerald-600 hover:bg-emerald-500 font-bold text-xs text-white rounded-lg">Add Stock</button>
            </div>
        </div>
    </main>

    <div id="purchase-modal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
        <div class="glass-card w-full max-w-xs p-5 rounded-2xl border-blue-500/40 space-y-4">
            <h3 class="font-bold text-base text-white">Confirm Purchase</h3>
            <div class="space-y-1.5 text-xs text-slate-300">
                <div class="flex justify-between"><span>Country:</span><span id="modal-country" class="font-bold"></span></div>
                <div class="flex justify-between"><span>Quality:</span><span id="modal-quality" class="font-bold"></span></div>
                <div class="flex justify-between"><span>Price:</span><span id="modal-price" class="font-bold text-emerald-400"></span></div>
            </div>
            <div class="flex gap-2 pt-2">
                <button onclick="closeModal()" class="flex-1 py-2 bg-slate-800 text-slate-300 text-xs font-bold rounded-lg">Cancel</button>
                <button onclick="confirmPurchase()" class="flex-1 py-2 bg-blue-600 text-white text-xs font-bold rounded-lg shadow-lg">Confirm</button>
            </div>
        </div>
    </div>

    <nav class="fixed bottom-0 left-0 right-0 glass-card border-t border-slate-800/80 p-2 flex justify-around items-center z-40 max-w-lg mx-auto">
        <button onclick="switchTab('home')" id="nav-home" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-semibold nav-active">
            <i data-lucide="home" class="w-5 h-5"></i> Home
        </button>
        <button onclick="switchTab('shop')" id="nav-shop" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-semibold">
            <i data-lucide="shopping-bag" class="w-5 h-5"></i> Shop
        </button>
        <button onclick="switchTab('wallet')" id="nav-wallet" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-semibold">
            <i data-lucide="wallet" class="w-5 h-5"></i> Wallet
        </button>
        <button onclick="switchTab('orders')" id="nav-orders" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-semibold">
            <i data-lucide="package" class="w-5 h-5"></i> Orders
        </button>
        <button onclick="switchTab('profile')" id="nav-profile" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-semibold">
            <i data-lucide="user" class="w-5 h-5"></i> Profile
        </button>
    </nav>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.enableClosingConfirmation();

        const initData = tg.initData || "";
        let currentUser = null;
        let allCountries = [];
        let selectedCountryId = null;
        let selectedGrade = null;
        let selectedPaymentMethod = null;

        async function fetchAPI(endpoint, options = {}) {
            options.headers = {
                ...options.headers,
                'X-Telegram-Init-Data': initData
            };
            const response = await fetch('/api' + endpoint, options);
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'API Request failed');
            }
            return response.json();
        }

        async function initApp() {
            lucide.createIcons();
            try {
                currentUser = await fetchAPI('/me');
                updateUIUser();
                await loadCountries();
            } catch (e) {
                console.error(e);
                alert('Authentication Failed: ' + e.message);
            }
        }

        function updateUIUser() {
            document.getElementById('user-name').innerText = currentUser.first_name;
            document.getElementById('user-tg-id').innerText = 'ID: ' + currentUser.telegram_id;
            document.getElementById('user-avatar').innerText = currentUser.first_name.charAt(0).toUpperCase();
            document.getElementById('home-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('wallet-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('current-lang').innerText = currentUser.language.toUpperCase();

            document.getElementById('profile-avatar').innerText = currentUser.first_name.charAt(0).toUpperCase();
            document.getElementById('profile-name').innerText = currentUser.first_name;
            document.getElementById('profile-username').innerText = '@' + currentUser.username;
            document.getElementById('profile-total-orders').innerText = currentUser.total_orders;
            document.getElementById('profile-total-spent').innerText = '$' + currentUser.total_spent.toFixed(2);
            document.getElementById('support-link').href = currentUser.support_url;

            if (currentUser.is_admin) {
                document.getElementById('admin-quick-btn').classList.remove('hidden');
            }
        }

        function switchTab(tab) {
            tg.HapticFeedback.impactOccurred('light');
            const views = ['home', 'shop', 'country-detail', 'wallet', 'orders', 'profile', 'admin'];
            views.forEach(v => document.getElementById('view-' + v)?.classList.add('hidden'));
            
            document.querySelectorAll('nav button').forEach(b => b.classList.remove('nav-active'));
            
            const activeNav = document.getElementById('nav-' + tab);
            if (activeNav) activeNav.classList.add('nav-active');

            document.getElementById('view-' + tab)?.classList.remove('hidden');

            if (tab === 'shop') loadCountries();
            if (tab === 'wallet') loadPaymentMethods();
            if (tab === 'orders') loadOrders();
            if (tab === 'admin') loadAdminDashboard();
        }

        async function loadCountries() {
            try {
                allCountries = await fetchAPI('/countries');
                renderCountries(allCountries);
            } catch (e) { console.error(e); }
        }

        function renderCountries(list) {
            const container = document.getElementById('country-list');
            if (!list.length) {
                container.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs">No countries currently available.</div>`;
                return;
            }
            container.innerHTML = list.map(c => `
                <div onclick="openCountryDetail(${c.id})" class="glass-card p-3.5 rounded-xl flex items-center justify-between hover:border-blue-500/40 active:scale-[0.98] transition-all">
                    <div class="flex items-center space-x-3">
                        <span class="text-2xl">${c.flag}</span>
                        <div>
                            <div class="font-bold text-sm text-white">${c.name}</div>
                            <div class="text-[11px] text-slate-400">${c.stock} accounts available</div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="font-bold text-xs text-emerald-400">From $${c.min_price.toFixed(2)}</div>
                        <i data-lucide="chevron-right" class="w-4 h-4 text-slate-500 ml-auto mt-0.5"></i>
                    </div>
                </div>
            `).join('');
            lucide.createIcons();
        }

        function filterCountries() {
            const q = document.getElementById('search-country').value.toLowerCase();
            renderCountries(allCountries.filter(c => c.name.toLowerCase().includes(q)));
        }

        async function openCountryDetail(cid) {
            selectedCountryId = cid;
            try {
                const data = await fetchAPI('/countries/' + cid);
                document.getElementById('detail-flag').innerText = data.flag;
                document.getElementById('detail-country-name').innerText = data.name;
                
                document.getElementById('fresh-stock-info').innerText = `Available: ${data.fresh.count} | Price: $${data.fresh.price.toFixed(2)}`;
                document.getElementById('broken-stock-info').innerText = `Available: ${data.broken.count} | Price: $${data.broken.price.toFixed(2)}`;
                
                document.getElementById('btn-buy-fresh').disabled = data.fresh.count === 0;
                document.getElementById('btn-buy-broken').disabled = data.broken.count === 0;

                switchTab('country-detail');
            } catch (e) { alert(e.message); }
        }

        function openPurchaseModal(grade) {
            selectedGrade = grade;
            const cName = document.getElementById('detail-country-name').innerText;
            const price = grade === 'fresh' 
                ? document.getElementById('fresh-stock-info').innerText.split('Price: ')[1]
                : document.getElementById('broken-stock-info').innerText.split('Price: ')[1];

            document.getElementById('modal-country').innerText = cName;
            document.getElementById('modal-quality').innerText = grade === 'fresh' ? 'Spam-Free' : 'Spam';
            document.getElementById('modal-price').innerText = price;
            document.getElementById('purchase-modal').classList.remove('hidden');
        }

        function closeModal() {
            document.getElementById('purchase-modal').classList.add('hidden');
        }

        async function confirmPurchase() {
            closeModal();
            try {
                const res = await fetchAPI('/purchase', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ country_id: selectedCountryId, grade: selectedGrade })
                });
                tg.HapticFeedback.notificationOccurred('success');
                alert(`🎉 Purchase Successful!\nOrder ID: ${res.order_id}\nKey: ${res.product_id}`);
                currentUser.balance = res.new_balance;
                updateUIUser();
                switchTab('orders');
            } catch (e) {
                tg.HapticFeedback.notificationOccurred('error');
                alert('❌ ' + e.message);
            }
        }

        async function loadPaymentMethods() {
            try {
                const methods = await fetchAPI('/payment-methods');
                const grid = document.getElementById('payment-methods-grid');
                grid.innerHTML = Object.entries(methods).map(([key, val]) => `
                    <button onclick="selectPaymentMethod('${key}')" class="glass-card p-3 rounded-xl flex flex-col items-center justify-center gap-1.5 hover:border-blue-500/40 text-center">
                        <span class="font-bold text-xs text-white">${val.name}</span>
                        <span class="text-[10px] text-slate-400 font-mono">${val.ticker}</span>
                    </button>
                `).join('');
            } catch (e) { console.error(e); }
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
            if (!amt || amt < 4.5) return alert('Minimum deposit is $4.50 USD');
            try {
                const inv = await fetchAPI('/deposit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ method_key: selectedPaymentMethod, amount: amt })
                });
                document.getElementById('invoice-net').innerText = inv.network;
                document.getElementById('invoice-code').innerText = inv.invoice_code;
                document.getElementById('invoice-crypto').innerText = `${inv.crypto_amount} ${inv.ticker}`;
                document.getElementById('invoice-address').innerText = inv.address;
                document.getElementById('invoice-section').classList.remove('hidden');
            } catch (e) { alert(e.message); }
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
                alert('✅ Proof uploaded successfully! Admin will verify shortly.');
                document.getElementById('invoice-section').classList.add('hidden');
            } catch (e) { alert(e.message); }
        }

        async function loadOrders() {
            try {
                const orders = await fetchAPI('/orders');
                const container = document.getElementById('orders-list');
                if (!orders.length) {
                    container.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs">No purchase history found.</div>`;
                    return;
                }
                container.innerHTML = orders.map(o => `
                    <div class="glass-card p-3.5 rounded-xl space-y-1.5 border-slate-800">
                        <div class="flex justify-between items-center text-xs">
                            <span class="font-mono text-slate-400">${o.order_id}</span>
                            <span class="text-emerald-400 font-bold">$${o.amount.toFixed(2)}</span>
                        </div>
                        <div class="font-bold text-sm text-white flex items-center gap-1.5">
                            <span>${o.flag}</span> <span>${o.quality}</span>
                        </div>
                        <div class="text-[11px] font-mono text-slate-400 bg-slate-900/60 p-1.5 rounded break-all">
                            ID: ${o.product_id}
                        </div>
                    </div>
                `).join('');
            } catch (e) { console.error(e); }
        }

        async function loadAdminDashboard() {
            try {
                const stats = await fetchAPI('/admin/stats');
                document.getElementById('admin-users').innerText = stats.total_users;
                document.getElementById('admin-stock').innerText = stats.available_stock;

                const countries = await fetchAPI('/countries');
                document.getElementById('admin-country-select').innerHTML = countries.map(c => `<option value="${c.id}">${c.flag} ${c.name}</option>`).join('');
            } catch (e) { console.error(e); }
        }

        async function submitAdminStock() {
            const cid = parseInt(document.getElementById('admin-country-select').value);
            const qual = document.getElementById('admin-quality-select').value;
            const price = parseFloat(document.getElementById('admin-price-input').value);
            const qty = parseInt(document.getElementById('admin-qty-input').value);

            try {
                await fetchAPI('/admin/stock', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ country_id: cid, quality: qual, price: price, quantity: qty })
                });
                alert('✅ Stock added successfully!');
                loadAdminDashboard();
            } catch (e) { alert(e.message); }
        }

        async function switchLanguage() {
            const nextLang = currentUser.language === 'ru' ? 'en' : 'ru';
            try {
                await fetchAPI('/language', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ language: nextLang })
                });
                currentUser.language = nextLang;
                updateUIUser();
            } catch (e) { console.error(e); }
        }

        window.onload = initApp;
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    return HTMLResponse(content=HTML_CONTENT)

# --- APPLICATION ENTRYPOINT ---

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("mini_app:app", host="0.0.0.0", port=port, reload=False)
