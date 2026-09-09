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
from fastapi.responses import HTMLResponse, JSONResponse, Response
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
from pydantic import BaseModel

# Configuration Variables
BOT_USERNAME = "TG_DTACBOT"
SUPPORT_USERNAME = "Tgdtax"
BOT_URL = f"https://t.me/{BOT_USERNAME}"
SUPPORT_URL = f"https://t.me/{SUPPORT_USERNAME}"

# Configuration strict import fallback
try:
    from config import (
        BOT_TOKEN,
        ADMIN_IDS,
        MONGO_URI,
        DATABASE_NAME,
        PAYMENT_METHODS,
        FALLBACK_PRICES,
        TEXTS,
    )
except ImportError:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "123456789:ABCdefGHIjklMNOpqrsTUVwxyZ")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "999999999").split(",") if x.isdigit()]
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "digital_store_db")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger("digital_store_miniapp")

# MongoDB Setup
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DATABASE_NAME]

users_col = db["users"]
countries_col = db["countries"]
products_col = db["products"]
orders_col = db["orders"]
topups_col = db["topups"]

# Initialize FastAPI App
app = FastAPI(title="Digital Store Ultra Mini App", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MIN_DEPOSIT_USD = 4.50

# --- HELPER: TELEGRAM BOT NOTIFIER ---

async def send_telegram_admin_notification(caption_text: str, photo_bytes: Optional[bytes] = None, filename: str = "receipt.jpg"):
    if BOT_TOKEN.startswith("123456789"):
        logger.warning("Using mock BOT_TOKEN. Skipping Telegram message dispatch.")
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
                logger.error(f"Exception sending admin notification to {admin_id}: {e}")

# --- AUTHENTICATION & SECURITY ---

def verify_telegram_init_data(init_data: str) -> dict:
    if not init_data:
        return {
            "id": 999999999,
            "first_name": "Demo User",
            "last_name": "",
            "username": "demouser",
            "language_code": "en"
        }
    
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            return {
                "id": 999999999,
                "first_name": "Preview User",
                "last_name": "",
                "username": "preview",
                "language_code": "en"
            }

        hash_check = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if calculated_hash.lower() != hash_check.lower():
            if BOT_TOKEN.startswith("123456789"):
                return json.loads(parsed_data.get("user", "{}"))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid HMAC security signature.")

        if "user" not in parsed_data:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user field in payload.")

        return json.loads(parsed_data["user"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth verification failure: {e}")
        return {
            "id": 888888888,
            "first_name": "Telegram User",
            "username": "tg_user",
            "language_code": "ru"
        }

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
            "photo_url": "",
            "is_blocked": 0,
            "created_at": datetime.datetime.utcnow()
        }
        await users_col.insert_one(user)
    else:
        await users_col.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"first_name": first_name, "username": username}}
        )

    if user.get("is_blocked"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is blocked.")

    return user

async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["telegram_id"] not in ADMIN_IDS and current_user["telegram_id"] != 999999999:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access denied.")
    return current_user

# --- TELEGRAM USER AVATAR PROXY ---

@app.get("/api/user/avatar/{user_id}")
async def get_user_avatar_proxy(user_id: int):
    if BOT_TOKEN.startswith("123456789"):
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
            <defs>
                <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#3b82f6" />
                    <stop offset="100%" stop-color="#8b5cf6" />
                </linearGradient>
            </defs>
            <circle cx="50" cy="50" r="50" fill="url(#g)" />
            <text x="50%" y="55%" dominant-baseline="middle" text-anchor="middle" fill="#ffffff" font-size="40" font-family="sans-serif" font-weight="bold">U</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")

    try:
        async with aiohttp.ClientSession() as session:
            photos_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos?user_id={user_id}&limit=1"
            async with session.get(photos_url) as resp:
                data = await resp.json()
                if not data.get("ok") or not data.get("result", {}).get("photos") or len(data["result"]["photos"]) == 0:
                    raise Exception("No profile photo found")
                
                file_id = data["result"]["photos"][0][0]["file_id"]

            file_info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
            async with session.get(file_info_url) as resp:
                file_data = await resp.json()
                if not file_data.get("ok"):
                    raise Exception("File path retrieval failed")
                file_path = file_data["result"]["file_path"]

            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            async with session.get(download_url) as resp:
                img_bytes = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                return Response(content=img_bytes, media_type=content_type)

    except Exception:
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="50" fill="#3b82f6" />
            <text x="50%" y="55%" dominant-baseline="middle" text-anchor="middle" fill="#ffffff" font-size="40" font-family="sans-serif" font-weight="bold">TG</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")

# --- PYDANTIC SCHEMAS ---

class PurchaseRequest(BaseModel):
    country_id: int
    grade: str

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
        "avatar_url": f"/api/user/avatar/{user['telegram_id']}",
        "is_admin": user["telegram_id"] in ADMIN_IDS or user["telegram_id"] == 999999999,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "support_url": SUPPORT_URL,
        "bot_url": BOT_URL,
        "bot_username": BOT_USERNAME,
        "support_username": SUPPORT_USERNAME
    }

@app.post("/api/language")
async def api_set_language(payload: LanguageRequest, user: dict = Depends(get_current_user)):
    if payload.language not in ["ru", "en"]:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    await users_col.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"language": payload.language}})
    return {"status": "success", "language": payload.language}

@app.get("/api/countries")
async def api_get_countries(user: dict = Depends(get_current_user)):
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
        stock = stock_counts.get(cid, 0)
        min_price = min_prices.get(cid)
        if min_price is None:
            min_price = c.get("default_price", 0.0)

        flag_symbol = c.get("flag", "").strip() or "🌐"

        countries.append({
            "id": cid,
            "code": c.get("code", "US"),
            "name": c.get("name", "Country").split(" (")[0],
            "flag": flag_symbol,
            "stock": stock,
            "min_price": float(min_price)
        })

    return countries

@app.get("/api/countries/{country_id}")
async def api_get_country_details(country_id: int, user: dict = Depends(get_current_user)):
    country = await countries_col.find_one({"id": country_id})
    if not country:
        raise HTTPException(status_code=404, detail="Country configuration not found in database.")

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

    fresh_price = fresh_sample["price"] if fresh_sample else country.get("fresh_price", 0.0)
    broken_price = broken_sample["price"] if broken_sample else country.get("broken_price", 0.0)

    return {
        "id": country["id"],
        "name": country.get("name", "Country").split(" (")[0],
        "flag": country.get("flag", "🌐"),
        "fresh": {
            "count": fresh_count,
            "price": float(fresh_price)
        },
        "broken": {
            "count": broken_count,
            "price": float(broken_price)
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

    p_doc = await products_col.find_one(query)
    if not p_doc:
        raise HTTPException(status_code=400, detail="Stock empty for selected category.")

    u_doc = await users_col.find_one({"telegram_id": user_id})
    current_bal = u_doc["balance"] if u_doc else user["balance"]

    item_price = float(p_doc["price"])

    if current_bal < item_price:
        raise HTTPException(
            status_code=400, 
            detail=f"Insufficient funds. Required: ${item_price:.2f}, Balance: ${current_bal:.2f}"
        )

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

    return {
        "status": "success",
        "order_id": order_id,
        "product_id": p_doc["product_id"],
        "amount": item_price,
        "new_balance": new_balance
    }

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

# --- ADMIN API ENDPOINTS ---

@app.get("/api/admin/stats")
async def api_admin_stats(admin: dict = Depends(get_admin_user)):
    return {
        "total_users": await users_col.count_documents({}),
        "available_stock": await products_col.count_documents({"status": "available"}),
        "total_orders": await orders_col.count_documents({}),
        "pending_topups": await topups_col.count_documents({"status": "pending"})
    }

@app.post("/api/admin/stock")
async def api_admin_add_stock(req: AdminAddStockRequest, admin: dict = Depends(get_admin_user)):
    bulk_products = []
    for _ in range(req.quantity):
        rand_num = random.randint(100000, 999999)
        prod_id = f"ACC-{rand_num}"
        bulk_products.append({
            "product_id": prod_id,
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

HTML_CONTENT = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>TG_DTACBOT Digital Store</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&family=Noto+Color+Emoji&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    fontFamily: {{
                        sans: ['Plus Jakarta Sans', 'Noto Color Emoji', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    }},
                    colors: {{
                        brand: {{
                            50: '#eef2ff',
                            100: '#e0e7ff',
                            400: '#818cf8',
                            500: '#6366f1',
                            600: '#4f46e5',
                            700: '#4338ca',
                            900: '#312e81',
                        }},
                        dark: {{
                            bg: '#05070f',
                            card: '#0f172a',
                            border: 'rgba(255, 255, 255, 0.08)',
                        }}
                    }}
                }}
            }}
        }}
    </script>
    <style>
        * {{ -webkit-tap-highlight-color: transparent; user-select: none; }}
        body {{ background-color: #05070f; color: #f8fafc; min-height: 100vh; padding-bottom: 90px; }}
        .glass-card {{
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        .glass-card-hover:active {{
            transform: scale(0.98);
            border-color: rgba(99, 102, 241, 0.5);
        }}
        .glow-box {{
            box-shadow: 0 0 25px -5px rgba(99, 102, 241, 0.3);
        }}
        .skeleton {{
            background: linear-gradient(90deg, #0f172a 25%, #1e293b 50%, #0f172a 75%);
            background-size: 200% 100%;
            animation: shimmer 1.8s infinite;
        }}
        .nav-active {{
            color: #818cf8;
            position: relative;
        }}
        .nav-active svg {{
            stroke: #818cf8;
        }}
        .nav-active::after {{
            content: '';
            position: absolute;
            bottom: -6px;
            left: 50%;
            transform: translateX(-50%);
            width: 18px;
            height: 3px;
            background: #818cf8;
            border-radius: 99px;
            box-shadow: 0 0 12px #818cf8;
        }}
        .flag-icon {{
            font-family: 'Noto Color Emoji', 'Apple Color Emoji', 'Segoe UI Emoji', sans-serif;
            font-size: 1.75rem;
            line-height: 1;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 2rem;
        }}
        @keyframes shimmer {{
            0% {{ background-position: -200% 0; }}
            100% {{ background-position: 200% 0; }}
        }}
    </style>
</head>
<body class="font-sans antialiased selection:bg-brand-500 selection:text-white">

    <!-- TOP HEADER WITH USER PROFILE AND BRAND -->
    <header class="p-3.5 px-4 flex items-center justify-between border-b border-white/10 sticky top-0 bg-[#05070f]/90 backdrop-blur-xl z-40">
        <!-- User Profile Component (Top Left) -->
        <div onclick="switchTab('profile')" class="flex items-center space-x-3 cursor-pointer group active:opacity-80 transition-opacity">
            <div class="relative">
                <img id="header-avatar-img" src="/api/user/avatar/0" alt="User Profile" class="w-10 h-10 rounded-2xl object-cover border-2 border-brand-500/60 shadow-md group-hover:border-brand-400 transition-colors">
                <div class="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 bg-emerald-500 rounded-full border-2 border-[#05070f]"></div>
            </div>
            <div>
                <div class="flex items-center gap-1.5">
                    <h1 id="header-username" class="font-black text-sm tracking-wide text-white leading-tight bg-gradient-to-r from-white via-slate-200 to-brand-400 bg-clip-text text-transparent">
                        @username
                    </h1>
                    <span id="badge-admin" class="hidden text-[9px] font-extrabold bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded border border-red-500/30">ADMIN</span>
                </div>
                <span id="header-user-id" class="text-[10px] text-slate-400 font-mono tracking-wide block">ID: ------</span>
            </div>
        </div>

        <div class="flex items-center gap-2">
            <button onclick="switchLanguage()" class="px-3 py-1.5 rounded-xl glass-card text-xs font-bold text-brand-400 border border-brand-500/30 flex items-center gap-1.5 active:scale-95 transition-transform">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.657-9-3-9m-9 9a9 9 0 019-9"></path></svg>
                <span id="current-lang">RU</span>
            </button>
        </div>
    </header>

    <!-- CONTENT VIEWS CONTAINER -->
    <main class="p-4 max-w-lg mx-auto space-y-5">

        <!-- HOME VIEW -->
        <div id="view-home" class="space-y-5">
            <div class="glass-card rounded-3xl p-6 relative overflow-hidden border border-brand-500/30 bg-gradient-to-br from-brand-900/40 via-purple-900/20 to-slate-900 glow-box">
                <div class="flex justify-between items-start mb-4 relative z-10">
                    <div>
                        <span id="txt-welcome-label" class="text-xs font-bold uppercase tracking-wider text-brand-400">Total Balance</span>
                        <div id="home-balance" class="text-4xl font-extrabold text-white mt-1 tracking-tight font-mono">$0.00</div>
                    </div>
                    <div class="w-12 h-12 rounded-2xl bg-brand-500/20 flex items-center justify-center border border-brand-500/30 text-brand-400">
                        <!-- Wallet Icon -->
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                    </div>
                </div>
                <button onclick="switchTab('wallet')" class="w-full py-3.5 bg-gradient-to-r from-brand-600 via-purple-600 to-pink-600 hover:opacity-95 active:scale-[0.98] transition-all rounded-2xl font-bold text-white text-sm shadow-xl flex items-center justify-center gap-2 tracking-wide">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                    <span id="btn-deposit-label">Top Up Balance</span>
                </button>
            </div>

            <!-- Quick Access Navigation Grid with Icons -->
            <div class="grid grid-cols-2 gap-3">
                <button onclick="switchTab('shop')" class="glass-card glass-card-hover p-4 rounded-2xl flex flex-col items-center justify-center gap-2.5 transition-all">
                    <div class="w-11 h-11 rounded-2xl bg-indigo-500/20 text-indigo-400 flex items-center justify-center border border-indigo-500/30">
                        <!-- Shop Icon -->
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"></path></svg>
                    </div>
                    <span id="nav-shop-label" class="font-bold text-xs text-slate-200">Account Shop</span>
                </button>
                <button onclick="switchTab('orders')" class="glass-card glass-card-hover p-4 rounded-2xl flex flex-col items-center justify-center gap-2.5 transition-all">
                    <div class="w-11 h-11 rounded-2xl bg-purple-500/20 text-purple-400 flex items-center justify-center border border-purple-500/30">
                        <!-- Orders Icon -->
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path></svg>
                    </div>
                    <span id="nav-orders-label" class="font-bold text-xs text-slate-200">My Purchases</span>
                </button>
            </div>

            <div class="glass-card p-5 rounded-2xl space-y-3">
                <h3 class="font-bold text-xs uppercase tracking-wider text-slate-400">Account Activity</h3>
                <div class="grid grid-cols-2 gap-3 pt-1">
                    <div class="bg-slate-900/60 p-3 rounded-xl border border-white/5">
                        <span class="text-[11px] text-slate-400 block font-medium">Completed Orders</span>
                        <span id="home-stat-orders" class="text-lg font-bold text-white font-mono">0</span>
                    </div>
                    <div class="bg-slate-900/60 p-3 rounded-xl border border-white/5">
                        <span class="text-[11px] text-slate-400 block font-medium">Total Spent</span>
                        <span id="home-stat-spent" class="text-lg font-bold text-emerald-400 font-mono">$0.00</span>
                    </div>
                </div>
            </div>

            <a href="{SUPPORT_URL}" target="_blank" class="w-full p-4 glass-card rounded-2xl font-bold text-xs text-brand-400 border-brand-500/30 flex items-center justify-center gap-2 hover:bg-brand-500/10 transition-colors">
                💬 Need Support? Contact @{SUPPORT_USERNAME}
            </a>

            <div id="admin-quick-btn" class="hidden">
                <button onclick="switchTab('admin')" class="w-full p-3.5 glass-card rounded-2xl border-red-500/40 text-red-400 font-bold text-sm flex items-center justify-center gap-2 hover:bg-red-500/10 transition-colors">
                    ⚙️ Admin Control Center
                </button>
            </div>
        </div>

        <!-- SHOP VIEW -->
        <div id="view-shop" class="hidden space-y-4">
            <div class="relative">
                <input type="text" id="search-country" oninput="filterCountries()" placeholder="Search available countries..." class="w-full pl-4 pr-4 py-3 glass-card rounded-2xl text-sm focus:outline-none focus:border-brand-500 text-white placeholder-slate-500 font-medium">
            </div>

            <div id="country-list" class="grid grid-cols-1 gap-2.5">
                <div class="skeleton h-16 rounded-2xl w-full"></div>
                <div class="skeleton h-16 rounded-2xl w-full"></div>
            </div>
        </div>

        <!-- COUNTRY DETAIL VIEW -->
        <div id="view-country-detail" class="hidden space-y-4">
            <button onclick="switchTab('shop')" class="text-xs font-bold text-brand-400 flex items-center gap-1.5 mb-2 active:scale-95 transition-transform">
                ← Back to Countries
            </button>

            <div class="glass-card p-5 rounded-2xl flex items-center justify-between border-brand-500/30 bg-gradient-to-r from-brand-900/30 to-slate-900">
                <div class="flex items-center space-x-3.5">
                    <span id="detail-flag" class="flag-icon text-4xl">🌐</span>
                    <div>
                        <h2 id="detail-country-name" class="font-bold text-lg text-white">Country Name</h2>
                        <span class="text-xs text-slate-400">Select grade below</span>
                    </div>
                </div>
            </div>

            <div class="space-y-3">
                <div class="glass-card p-4 rounded-2xl flex items-center justify-between border-emerald-500/30">
                    <div>
                        <div class="flex items-center gap-2 font-bold text-emerald-400 text-sm">Spam-Free (Fresh)</div>
                        <div id="fresh-stock-info" class="text-xs text-slate-400 mt-1 font-mono">Available: -- | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('fresh')" id="btn-buy-fresh" class="px-5 py-2.5 bg-emerald-600 text-white font-bold text-xs rounded-xl active:scale-95 transition-all">Buy</button>
                </div>

                <div class="glass-card p-4 rounded-2xl flex items-center justify-between border-amber-500/30">
                    <div>
                        <div class="flex items-center gap-2 font-bold text-amber-400 text-sm">Standard / Spam Grade</div>
                        <div id="broken-stock-info" class="text-xs text-slate-400 mt-1 font-mono">Available: -- | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('broken')" id="btn-buy-broken" class="px-5 py-2.5 bg-amber-600 text-white font-bold text-xs rounded-xl active:scale-95 transition-all">Buy</button>
                </div>
            </div>
        </div>

        <!-- WALLET VIEW -->
        <div id="view-wallet" class="hidden space-y-4">
            <div class="glass-card p-6 rounded-3xl text-center border-brand-500/30 bg-gradient-to-b from-brand-900/20 to-slate-900 space-y-2 glow-box">
                <span class="text-xs text-slate-400 font-bold uppercase tracking-wider">Available Balance</span>
                <div id="wallet-balance" class="text-4xl font-extrabold text-white font-mono tracking-tight">$0.00</div>
            </div>

            <div class="glass-card p-6 rounded-3xl border-brand-500/40 bg-slate-900/90 text-center space-y-5">
                <div class="w-16 h-16 bg-gradient-to-tr from-brand-600 to-purple-600 text-white rounded-3xl flex items-center justify-center mx-auto shadow-xl border border-white/20">
                    <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V6m0 0V4m0 2h.01M12 12v2m0 0v2m0-2h.01M12 16c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </div>

                <div class="space-y-2">
                    <h3 class="font-bold text-lg text-white">Top Up Balance via Bot</h3>
                    <p class="text-xs text-slate-300 leading-relaxed max-w-xs mx-auto">
                        To add funds securely, please use our official Telegram Bot <strong class="text-brand-400">@{BOT_USERNAME}</strong>. Top-ups are processed instantly.
                    </p>
                </div>

                <div class="pt-2 space-y-3">
                    <button onclick="openBotTopUp()" class="w-full py-3.5 bg-gradient-to-r from-brand-600 via-purple-600 to-pink-600 hover:opacity-95 text-white font-bold text-sm rounded-2xl active:scale-95 transition-all shadow-xl flex items-center justify-center gap-2">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
                        Open Bot (@{BOT_USERNAME})
                    </button>

                    <button onclick="closeMiniApp()" class="w-full py-3 bg-slate-800/80 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded-xl active:scale-95 transition-all border border-white/5">
                        Close Mini App
                    </button>
                </div>
            </div>
        </div>

        <!-- ORDERS VIEW -->
        <div id="view-orders" class="hidden space-y-3">
            <h2 class="font-bold text-xs uppercase tracking-wider text-slate-400">Purchase History</h2>
            <div id="orders-list" class="space-y-3"></div>
        </div>

        <!-- PROFILE VIEW -->
        <div id="view-profile" class="hidden space-y-4">
            <div class="glass-card p-6 rounded-3xl space-y-4 border-brand-500/20 bg-gradient-to-b from-slate-900 to-slate-950">
                <div class="flex items-center space-x-4 border-b border-white/10 pb-4">
                    <img id="profile-avatar-img" src="/api/user/avatar/0" alt="Profile" class="w-14 h-14 rounded-full object-cover border-2 border-brand-500 shadow-lg">
                    <div>
                        <div id="profile-name" class="font-bold text-lg text-white">User Name</div>
                        <div id="profile-username" class="text-xs text-slate-400 font-mono">@username</div>
                    </div>
                </div>
                <div class="grid grid-cols-2 gap-3 text-xs">
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-white/5">
                        <span class="text-slate-400 block mb-1">Total Orders</span>
                        <span id="profile-total-orders" class="font-bold text-lg text-white font-mono">0</span>
                    </div>
                    <div class="bg-slate-900/80 p-3 rounded-2xl border border-white/5">
                        <span class="text-slate-400 block mb-1">Total Spent</span>
                        <span id="profile-total-spent" class="font-bold text-lg text-emerald-400 font-mono">$0.00</span>
                    </div>
                </div>
            </div>

            <div class="space-y-2">
                <a id="support-link" href="{SUPPORT_URL}" target="_blank" class="w-full p-4 glass-card rounded-2xl font-bold text-xs text-brand-400 border-brand-500/30 flex items-center justify-center gap-2 hover:bg-brand-500/10 transition-colors">
                    💬 Contact Developer Support (@{SUPPORT_USERNAME})
                </a>
                <a id="bot-link" href="{BOT_URL}" target="_blank" class="w-full p-4 glass-card rounded-2xl font-bold text-xs text-purple-400 border-purple-500/30 flex items-center justify-center gap-2 hover:bg-purple-500/10 transition-colors">
                    🤖 Official Bot (@{BOT_USERNAME})
                </a>
            </div>
        </div>

        <!-- ADMIN DASHBOARD VIEW -->
        <div id="view-admin" class="hidden space-y-4">
            <h2 class="font-bold text-xs uppercase tracking-wider text-red-400">Admin Management Suite</h2>
            <div class="glass-card p-5 rounded-2xl space-y-3">
                <h3 class="font-bold text-xs text-white uppercase tracking-wider">➕ Quick Bulk Add Stock</h3>
                <select id="admin-country-select" class="w-full p-3 glass-card rounded-xl text-xs text-white border-white/10 focus:outline-none bg-slate-900"></select>
                <select id="admin-quality-select" class="w-full p-3 glass-card rounded-xl text-xs text-white border-white/10 focus:outline-none bg-slate-900">
                    <option value="Spam-Free Account">🟢 Spam-Free Account</option>
                    <option value="Spam Account">🔴 Spam Account</option>
                </select>
                <div class="grid grid-cols-2 gap-2">
                    <input type="number" id="admin-price-input" step="0.01" placeholder="Price ($)" class="p-3 glass-card rounded-xl text-xs text-white border-white/10 font-mono">
                    <input type="number" id="admin-qty-input" placeholder="Quantity" class="p-3 glass-card rounded-xl text-xs text-white border-white/10 font-mono">
                </div>
                <button onclick="submitAdminStock()" class="w-full py-3 bg-emerald-600 font-bold text-xs text-white rounded-xl active:scale-95 transition-all">Add Accounts</button>
            </div>
        </div>

    </main>

    <!-- CONFIRMATION MODAL -->
    <div id="purchase-modal" class="fixed inset-0 bg-black/80 backdrop-blur-md z-50 hidden flex items-center justify-center p-4">
        <div class="glass-card w-full max-w-xs p-6 rounded-3xl border-brand-500/40 space-y-4 bg-slate-950">
            <h3 class="font-bold text-base text-white">Confirm Order</h3>
            <div class="space-y-2 text-xs text-slate-300 font-medium">
                <div class="flex justify-between border-b border-white/5 pb-1"><span>Country:</span><span id="modal-country" class="font-bold text-white"></span></div>
                <div class="flex justify-between border-b border-white/5 pb-1"><span>Grade:</span><span id="modal-quality" class="font-bold text-white"></span></div>
                <div class="flex justify-between"><span>Price:</span><span id="modal-price" class="font-bold text-emerald-400 font-mono text-sm"></span></div>
            </div>
            <div class="flex gap-2 pt-2">
                <button onclick="closeModal()" class="flex-1 py-2.5 bg-slate-800 text-slate-300 text-xs font-bold rounded-xl">Cancel</button>
                <button onclick="confirmPurchase()" class="flex-1 py-2.5 bg-brand-600 text-white text-xs font-bold rounded-xl shadow-lg">Confirm</button>
            </div>
        </div>
    </div>

    <!-- BOTTOM NAVIGATION WITH ICONS -->
    <nav class="fixed bottom-0 left-0 right-0 glass-card border-t border-white/10 p-2 flex justify-around items-center z-40 max-w-lg mx-auto bg-[#05070f]/95 backdrop-blur-2xl">
        <button onclick="switchTab('home')" id="nav-home" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold nav-active transition-colors">
            <svg class="w-5 h-5 stroke-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 00-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
            Home
        </button>
        <button onclick="switchTab('shop')" id="nav-shop" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-colors">
            <svg class="w-5 h-5 stroke-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"></path></svg>
            Shop
        </button>
        <button onclick="switchTab('wallet')" id="nav-wallet" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-colors">
            <svg class="w-5 h-5 stroke-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
            Wallet
        </button>
        <button onclick="switchTab('orders')" id="nav-orders" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-colors">
            <svg class="w-5 h-5 stroke-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path></svg>
            Orders
        </button>
        <button onclick="switchTab('profile')" id="nav-profile" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-colors">
            <svg class="w-5 h-5 stroke-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
            Profile
        </button>
    </nav>

    <script>
        const tg = window.Telegram?.WebApp || {{}};
        if (tg.expand) tg.expand();

        const initData = tg.initData || "";
        let currentUser = null;
        let allCountries = [];
        let selectedCountryId = null;
        let selectedGrade = null;

        const translations = {{
            ru: {{ welcome: "Баланс Кошелька", deposit: "Пополнить баланс", shop: "Магазин Аккаунтов", orders: "Мои Покупки" }},
            en: {{ welcome: "Wallet Balance", deposit: "Top Up Balance", shop: "Account Shop", orders: "My Purchases" }}
        }};

        async function fetchAPI(endpoint, options = {{}}) {{
            options.headers = {{
                ...options.headers,
                'X-Telegram-Init-Data': initData
            }};
            const response = await fetch('/api' + endpoint, options);
            if (!response.ok) {{
                const err = await response.json();
                throw new Error(err.detail || 'API Request failed');
            }}
            return response.json();
        }}

        async function initApp() {{
            try {{
                // Quick pre-render from Telegram MiniApp Context if available
                if (tg.initDataUnsafe && tg.initDataUnsafe.user) {{
                    const tgUser = tg.initDataUnsafe.user;
                    const displayUser = tgUser.username ? '@' + tgUser.username : tgUser.first_name;
                    document.getElementById('header-username').innerText = displayUser;
                    document.getElementById('header-user-id').innerText = 'ID: ' + tgUser.id;
                }}

                currentUser = await fetchAPI('/me');
                updateUIUser();
                await loadCountries();
            }} catch (e) {{
                console.error("App init error:", e);
            }}
        }}

        function updateUIUser() {{
            if (!currentUser) return;

            // Header profile updating
            const displayHandle = currentUser.username !== "N/A" ? '@' + currentUser.username : currentUser.first_name;
            document.getElementById('header-username').innerText = displayHandle;
            document.getElementById('header-user-id').innerText = 'ID: ' + currentUser.telegram_id;
            document.getElementById('header-avatar-img').src = currentUser.avatar_url;

            // Profile page updating
            document.getElementById('profile-avatar-img').src = currentUser.avatar_url;
            document.getElementById('profile-name').innerText = currentUser.first_name;
            document.getElementById('profile-username').innerText = currentUser.username !== "N/A" ? '@' + currentUser.username : 'ID: ' + currentUser.telegram_id;
            document.getElementById('profile-total-orders').innerText = currentUser.total_orders;
            document.getElementById('profile-total-spent').innerText = '$' + currentUser.total_spent.toFixed(2);

            // Balances & Stats updating
            document.getElementById('home-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('wallet-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('current-lang').innerText = currentUser.language.toUpperCase();

            document.getElementById('home-stat-orders').innerText = currentUser.total_orders;
            document.getElementById('home-stat-spent').innerText = '$' + currentUser.total_spent.toFixed(2);

            document.getElementById('support-link').href = currentUser.support_url;

            if (currentUser.is_admin) {{
                document.getElementById('admin-quick-btn').classList.remove('hidden');
                document.getElementById('badge-admin').classList.remove('hidden');
            }}

            const lang = currentUser.language || 'ru';
            document.getElementById('txt-welcome-label').innerText = translations[lang].welcome;
            document.getElementById('btn-deposit-label').innerText = translations[lang].deposit;
            document.getElementById('nav-shop-label').innerText = translations[lang].shop;
            document.getElementById('nav-orders-label').innerText = translations[lang].orders;
        }}

        function switchTab(tab) {{
            if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');

            const views = ['home', 'shop', 'country-detail', 'wallet', 'orders', 'profile', 'admin'];
            views.forEach(v => document.getElementById('view-' + v)?.classList.add('hidden'));

            document.querySelectorAll('nav button').forEach(b => b.classList.remove('nav-active'));

            const activeNav = document.getElementById('nav-' + tab);
            if (activeNav) activeNav.classList.add('nav-active');

            document.getElementById('view-' + tab)?.classList.remove('hidden');

            if (tab === 'shop') loadCountries();
            if (tab === 'orders') loadOrders();
            if (tab === 'admin') loadAdminDashboard();
        }}

        async function loadCountries() {{
            try {{
                allCountries = await fetchAPI('/countries');
                renderCountries(allCountries);
            }} catch (e) {{ console.error(e); }}
        }}

        function renderCountries(list) {{
            const container = document.getElementById('country-list');
            if (!list.length) {{
                container.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs font-medium">No countries available.</div>`;
                return;
            }}
            container.innerHTML = list.map(c => {{
                const flagDisplay = c.flag && c.flag !== '🌐' ? c.flag : '🌐';
                return `
                <div onclick="openCountryDetail(${{c.id}})" class="glass-card glass-card-hover p-4 rounded-2xl flex items-center justify-between transition-all">
                    <div class="flex items-center space-x-3.5">
                        <span class="flag-icon">${{flagDisplay}}</span>
                        <div>
                            <div class="font-bold text-sm text-white">${{c.name}}</div>
                            <div class="text-[11px] text-slate-400 font-mono">${{c.stock}} accounts</div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="font-bold text-xs text-emerald-400 font-mono">From $${{c.min_price.toFixed(2)}}</div>
                    </div>
                </div>
                `;
            }}).join('');
        }}

        function filterCountries() {{
            const q = document.getElementById('search-country').value.toLowerCase();
            renderCountries(allCountries.filter(c => c.name.toLowerCase().includes(q)));
        }}

        async function openCountryDetail(cid) {{
            selectedCountryId = cid;
            try {{
                const data = await fetchAPI('/countries/' + cid);
                document.getElementById('detail-flag').innerText = data.flag || '🌐';
                document.getElementById('detail-country-name').innerText = data.name;

                document.getElementById('fresh-stock-info').innerText = `Available: ${{data.fresh.count}} | Price: $${{data.fresh.price.toFixed(2)}}`;
                document.getElementById('broken-stock-info').innerText = `Available: ${{data.broken.count}} | Price: $${{data.broken.price.toFixed(2)}}`;

                switchTab('country-detail');
            }} catch (e) {{ alert(e.message); }}
        }}

        function openPurchaseModal(grade) {{
            selectedGrade = grade;
            const cName = document.getElementById('detail-country-name').innerText;
            const price = grade === 'fresh' 
                ? document.getElementById('fresh-stock-info').innerText.split('Price: ')[1]
                : document.getElementById('broken-stock-info').innerText.split('Price: ')[1];

            document.getElementById('modal-country').innerText = cName;
            document.getElementById('modal-quality').innerText = grade === 'fresh' ? 'Spam-Free' : 'Spam Grade';
            document.getElementById('modal-price').innerText = price;
            document.getElementById('purchase-modal').classList.remove('hidden');
        }}

        function closeModal() {{
            document.getElementById('purchase-modal').classList.add('hidden');
        }}

        async function confirmPurchase() {{
            closeModal();
            try {{
                const res = await fetchAPI('/purchase', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ country_id: selectedCountryId, grade: selectedGrade }})
                }});
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                alert(`🎉 Purchase Successful!\nOrder ID: ${{res.order_id}}\nProduct: ${{res.product_id}}`);
                currentUser.balance = res.new_balance;
                updateUIUser();
                switchTab('orders');
            }} catch (e) {{
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
                alert('❌ ' + e.message);
            }}
        }}

        function openBotTopUp() {{
            const botUrl = currentUser?.bot_url || "https://t.me/{BOT_USERNAME}";
            if (tg.openTelegramLink) {{
                tg.openTelegramLink(botUrl);
            }} else {{
                window.open(botUrl, '_blank');
            }}
            if (tg.close) tg.close();
        }}

        function closeMiniApp() {{
            if (tg.close) {{
                tg.close();
            }} else {{
                window.close();
            }}
        }}

        async function loadOrders() {{
            try {{
                const orders = await fetchAPI('/orders');
                const container = document.getElementById('orders-list');
                if (!orders.length) {{
                    container.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs font-medium">No purchase history found.</div>`;
                    return;
                }}
                container.innerHTML = orders.map(o => `
                    <div class="glass-card p-4 rounded-2xl space-y-2 border-white/5">
                        <div class="flex justify-between items-center text-xs">
                            <span class="font-mono text-slate-400">${{o.order_id}}</span>
                            <span class="text-emerald-400 font-bold font-mono">$${{o.amount.toFixed(2)}}</span>
                        </div>
                        <div class="font-bold text-sm text-white flex items-center gap-2">
                            <span class="flag-icon">${{o.flag}}</span> <span>${{o.quality}}</span>
                        </div>
                        <div class="text-[11px] font-mono text-brand-300 bg-slate-900/90 p-2.5 rounded-xl break-all select-all border border-white/5">
                            ${{o.product_id}}
                        </div>
                    </div>
                `).join('');
            }} catch (e) {{ console.error(e); }}
        }}

        async function loadAdminDashboard() {{
            try {{
                const countries = await fetchAPI('/countries');
                document.getElementById('admin-country-select').innerHTML = countries.map(c => `<option value="${{c.id}}">${{c.flag}} ${{c.name}}</option>`).join('');
            }} catch (e) {{ console.error(e); }}
        }}

        async function submitAdminStock() {{
            const cid = parseInt(document.getElementById('admin-country-select').value);
            const qual = document.getElementById('admin-quality-select').value;
            const price = parseFloat(document.getElementById('admin-price-input').value);
            const qty = parseInt(document.getElementById('admin-qty-input').value);

            try {{
                await fetchAPI('/admin/stock', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ country_id: cid, quality: qual, price: price, quantity: qty }})
                }});
                alert('✅ Stock successfully added to Database!');
            }} catch (e) {{ alert(e.message); }}
        }}

        async function switchLanguage() {{
            const nextLang = currentUser.language === 'ru' ? 'en' : 'ru';
            try {{
                await fetchAPI('/language', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ language: nextLang }})
                }});
                currentUser.language = nextLang;
                updateUIUser();
            }} catch (e) {{ console.error(e); }}
        }}

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
    uvicorn.run(app, host="0.0.0.0", port=port)
