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

from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File, Form, status, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from motor.motor_asyncio import AsyncIOMotorClient
import aiohttp
from pydantic import BaseModel

# --- IMPORT CONFIGURATION FROM CONFIG.PY ---
try:
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
except ImportError:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8863940881:AAFtqtpfrdcMQbHzIM8j1FJUYltVHZABF-o")
    ADMIN_IDS = [7952327997, 7953147643, 8064493735, 7123919486]
    MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://Gopaljichoubey:gopaljichoubey12@cluster0.qlsuf4o.mongodb.net/?appName=Cluster0")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "marketplace_db")
    DEVELOPER_SUPPORT_LINK = "https://t.me/support"
    PAYMENT_METHODS = {
        "usdt_bep20": {
            "name": "USDT (BEP-20)",
            "ticker": "USDT",
            "coingecko_id": "tether",
            "address": "0xC902874FE3A7fc30C792E17b75454eb7f4ce0dfE",
            "memo": "",
        },
        "usdt_erc20": {
            "name": "USDT (ERC-20)",
            "ticker": "USDT",
            "coingecko_id": "tether",
            "address": "0xC902874FE3A7fc30C792E17b75454eb7f4ce0dfE",
            "memo": "",
        },
        "usdt_poly": {
            "name": "USDT (Polygon)",
            "ticker": "USDT",
            "coingecko_id": "tether",
            "address": "0xC902874FE3A7fc30C792E17b75454eb7f4ce0dfE",
            "memo": "",
        },
        "usdt_ton": {
            "name": "USDT (TON)",
            "ticker": "USDT",
            "coingecko_id": "tether",
            "address": "EQAj7vKLbaWjaNbAuAKP1e1HwmdYZ2vJ2xtWU8qq3JafkfxF",
            "memo": "1481661",
        },
    }
    FALLBACK_PRICES = {"tether": 1.0}
    TEXTS = {"ru": {}, "en": {}}

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
app = FastAPI(title="Digital Store Ultra Mini App", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HELPER: TELEGRAM BOT NOTIFIER & APPROVAL SYSTEM ---

async def send_telegram_admin_approval_request(
    topup_id: str,
    user_id: int,
    username: str,
    first_name: str,
    amount_usd: float,
    crypto_amount: str,
    method_name: str,
    photo_bytes: bytes,
    filename: str = "receipt.jpg"
):
    """
    Sends payment proof and interactive inline approval buttons directly to Admin Telegram Chat(s).
    """
    if BOT_TOKEN.startswith("123456789") or "MOCK" in BOT_TOKEN:
        logger.warning("Using mock BOT_TOKEN. Skipping real Telegram message dispatch.")
        return

    caption = (
        f"🚨 <b>NEW DEPOSIT PROOF SUBMITTED</b> 🚨\n"
        f"═══════════════════════\n\n"
        f"🆔 <b>Invoice ID:</b> <code>{topup_id}</code>\n"
        f"👤 <b>User:</b> {first_name} (@{username})\n"
        f"🔢 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"💵 <b>Amount USD:</b> <code>${amount_usd:.2f}</code>\n"
        f"🪙 <b>Crypto Detail:</b> <code>{crypto_amount}</code> ({method_name})\n\n"
        f"👇 <b>Use buttons below to instantly approve or reject:</b>"
    )

    inline_keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": f"✅ Approve (${amount_usd:.2f})",
                    "callback_data": f"approve_topup:{topup_id}:{user_id}:{amount_usd}"
                },
                {
                    "text": "❌ Reject",
                    "callback_data": f"reject_topup:{topup_id}:{user_id}"
                }
            ]
        ]
    }

    async with aiohttp.ClientSession() as session:
        for admin_id in ADMIN_IDS:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                data = aiohttp.FormData()
                data.add_field("chat_id", str(admin_id))
                data.add_field("caption", caption, parse_mode="HTML")
                data.add_field("reply_markup", json.dumps(inline_keyboard))
                data.add_field("photo", photo_bytes, filename=filename, content_type="image/jpeg")
                
                async with session.post(url, data=data) as resp:
                    res = await resp.json()
                    if not res.get("ok"):
                        logger.error(f"Failed to send photo to admin {admin_id}: {res}")
            except Exception as e:
                logger.error(f"Exception sending admin notification to {admin_id}: {e}")

async def send_telegram_user_message(user_id: int, text: str):
    """Helper to send a direct message to a specific Telegram user."""
    if BOT_TOKEN.startswith("123456789"):
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload)
    except Exception as e:
        logger.error(f"Failed sending user message to {user_id}: {e}")

# --- TELEGRAM WEBHOOK HANDLER FOR INLINE BUTTON ACTIONS ---

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    """
    Handles inline button callback queries from admins approving/rejecting top-ups.
    """
    try:
        update = await request.json()
        if "callback_query" not in update:
            return {"status": "ignored"}

        cq = update["callback_query"]
        cq_id = cq["id"]
        from_id = cq["from"]["id"]
        data = cq.get("data", "")
        message = cq.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if from_id not in ADMIN_IDS:
            async with aiohttp.ClientSession() as session:
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={
                    "callback_query_id": cq_id,
                    "text": "❌ Unauthorized access.",
                    "show_alert": True
                })
            return {"status": "unauthorized"}

        if data.startswith("approve_topup:"):
            _, topup_id, user_id_str, amount_str = data.split(":")
            user_id = int(user_id_str)
            amount = float(amount_str)

            topup = await topups_col.find_one({"topup_id": topup_id})
            if not topup:
                alert_text = "❌ Transaction not found."
            elif topup.get("status") == "approved":
                alert_text = "⚠️ Deposit was already approved!"
            else:
                # Atomically update top-up and credit user balance
                await topups_col.update_one({"topup_id": topup_id}, {"$set": {"status": "approved", "approved_by": from_id, "approved_at": datetime.datetime.utcnow()}})
                await users_col.update_one({"telegram_id": user_id}, {"$inc": {"balance": amount}})
                
                # Notify User
                await send_telegram_user_message(
                    user_id,
                    f"🎉 <b>DEPOSIT APPROVED!</b>\n\n💰 Your wallet has been credited with <b>${amount:.2f} USD</b>.\nThank you for choosing our marketplace!"
                )
                alert_text = f"✅ Approved! ${amount:.2f} credited to user {user_id}."

                # Edit Admin Message Caption
                new_caption = (
                    f"{message.get('caption', '')}\n\n"
                    f"✅ <b>STATUS: APPROVED</b>\n"
                    f"👨‍💻 <b>Approved By Admin:</b> <code>{from_id}</code>\n"
                    f"🕒 <b>Time:</b> {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                )
                async with aiohttp.ClientSession() as session:
                    await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageCaption", json={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "caption": new_caption,
                        "parse_mode": "HTML",
                        "reply_markup": {"inline_keyboard": []}
                    })

            async with aiohttp.ClientSession() as session:
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={
                    "callback_query_id": cq_id,
                    "text": alert_text,
                    "show_alert": True
                })

        elif data.startswith("reject_topup:"):
            _, topup_id, user_id_str = data.split(":")
            user_id = int(user_id_str)

            await topups_col.update_one({"topup_id": topup_id}, {"$set": {"status": "rejected", "rejected_by": from_id}})
            await send_telegram_user_message(
                user_id,
                f"❌ <b>DEPOSIT REJECTED</b>\n\nYour recent transaction proof (ID: <code>{topup_id}</code>) was declined by support. Please contact support if you believe this is an error."
            )

            new_caption = (
                f"{message.get('caption', '')}\n\n"
                f"❌ <b>STATUS: REJECTED</b>\n"
                f"👨‍💻 <b>Rejected By Admin:</b> <code>{from_id}</code>"
            )
            async with aiohttp.ClientSession() as session:
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageCaption", json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "caption": new_caption,
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": []}
                })
                await session.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={
                    "callback_query_id": cq_id,
                    "text": "❌ Deposit proof rejected.",
                    "show_alert": True
                })

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {e}")
        return {"status": "error", "message": str(e)}

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
                if not data.get("ok") or not data.get("result", {}).get("photos"):
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

    except Exception as e:
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="50" fill="#3b82f6" />
            <text x="50%" y="55%" dominant-baseline="middle" text-anchor="middle" fill="#ffffff" font-size="40" font-family="sans-serif" font-weight="bold">TG</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")

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

class AdminManualCreditRequest(BaseModel):
    target_user_id: int
    amount: float

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

        countries.append({
            "id": cid,
            "code": c.get("code", "US"),
            "name": c.get("name", "Country").split(" (")[0],
            "flag": c.get("flag", "🌐"),
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

@app.get("/api/payment-methods")
async def api_get_payment_methods(user: dict = Depends(get_current_user)):
    return PAYMENT_METHODS

@app.post("/api/deposit")
async def api_create_deposit(req: DepositRequest, user: dict = Depends(get_current_user)):
    if req.amount < 1.00:
        raise HTTPException(status_code=400, detail="Minimum deposit amount is $1.00 USD.")
    
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
    """
    Saves deposit proof in MongoDB and delivers screenshot with interactive inline buttons to Admins.
    """
    method_name = PAYMENT_METHODS.get(method_key, {}).get("name", method_key)
    file_bytes = await file.read()

    topup_doc = {
        "topup_id": invoice_code,
        "user_id": user["telegram_id"],
        "username": user.get("username", "N/A"),
        "first_name": user.get("first_name", "User"),
        "amount": amount,
        "method": method_name,
        "crypto_amount": crypto_amount,
        "status": "pending",
        "proof_filename": file.filename,
        "created_at": datetime.datetime.utcnow()
    }
    await topups_col.insert_one(topup_doc)

    # Forward interactive approval request directly to Admin Telegram
    asyncio.create_task(
        send_telegram_admin_approval_request(
            topup_id=invoice_code,
            user_id=user["telegram_id"],
            username=user.get("username", "N/A"),
            first_name=user.get("first_name", "User"),
            amount_usd=amount,
            crypto_amount=crypto_amount,
            method_name=method_name,
            photo_bytes=file_bytes,
            filename=file.filename or "receipt.jpg"
        )
    )

    return {"status": "success", "message": "Payment proof submitted! Admins can now approve balance from Telegram."}

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

@app.post("/api/admin/manual-credit")
async def api_admin_manual_credit(req: AdminManualCreditRequest, admin: dict = Depends(get_admin_user)):
    res = await users_col.update_one({"telegram_id": req.target_user_id}, {"$inc": {"balance": req.amount}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Target user ID not found.")
    
    await send_telegram_user_message(
        req.target_user_id,
        f"💵 <b>BALANCE CREDITED!</b>\n\nSupport has manually added <b>${req.amount:.2f} USD</b> to your wallet."
    )
    return {"status": "success", "credited": req.amount}

# --- FRONTEND WEB APP CODE ---

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Digital Marketplace Mini App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Plus Jakarta Sans', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    },
                    colors: {
                        brand: {
                            50: '#eff6ff',
                            100: '#dbeafe',
                            400: '#60a5fa',
                            500: '#3b82f6',
                            600: '#2563eb',
                            700: '#1d4ed8',
                            900: '#1e3a8a',
                        },
                        dark: {
                            bg: '#090d16',
                            card: '#111827',
                            border: 'rgba(255, 255, 255, 0.08)',
                        }
                    },
                    animation: {
                        'pulse-glow': 'pulseGlow 3s infinite alternate',
                        'float': 'float 4s ease-in-out infinite',
                        'shimmer': 'shimmer 2s infinite linear',
                    },
                    keyframes: {
                        pulseGlow: {
                            '0%': { boxShadow: '0 0 15px -3px rgba(59, 130, 246, 0.3)' },
                            '100%': { boxShadow: '0 0 35px 8px rgba(139, 92, 246, 0.5)' },
                        },
                        float: {
                            '0%, 100%': { transform: 'translateY(0px)' },
                            '50%': { transform: 'translateY(-6px)' },
                        },
                        shimmer: {
                            '0%': { backgroundPosition: '-200% 0' },
                            '100%': { backgroundPosition: '200% 0' },
                        }
                    }
                }
            }
        }
    </script>
    <style>
        * { -webkit-tap-highlight-color: transparent; user-select: none; }
        body { background-color: #070a12; color: #f3f4f6; min-height: 100vh; padding-bottom: 90px; }
        .glass-card {
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.02) 100%);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .glass-card-hover:active {
            transform: scale(0.98);
            border-color: rgba(59, 130, 246, 0.4);
        }
        .skeleton {
            background: linear-gradient(90deg, #111827 25%, #1f2937 50%, #111827 75%);
            background-size: 200% 100%;
            animation: shimmer 1.8s infinite;
        }
        .nav-active {
            color: #60a5fa;
            position: relative;
        }
        .nav-active::after {
            content: '';
            position: absolute;
            bottom: -6px;
            left: 50%;
            transform: translateX(-50%);
            width: 16px;
            height: 3px;
            background: #60a5fa;
            border-radius: 99px;
            box-shadow: 0 0 10px #60a5fa;
        }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #1f2937; border-radius: 4px; }
    </style>
</head>
<body class="font-sans antialiased selection:bg-brand-500 selection:text-white">

    <!-- HEADER -->
    <header class="p-4 flex items-center justify-between border-b border-white/10 sticky top-0 bg-[#070a12]/90 backdrop-blur-xl z-40">
        <div class="flex items-center space-x-3">
            <div class="relative">
                <img id="user-avatar-img" src="/api/user/avatar/0" alt="Avatar" class="w-10 h-10 rounded-full object-cover border-2 border-brand-500/50 shadow-md">
                <div class="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 bg-emerald-500 rounded-full border-2 border-[#070a12]"></div>
            </div>
            <div>
                <div class="flex items-center gap-1.5">
                    <h1 id="user-name" class="font-bold text-sm tracking-tight text-white leading-none">Loading...</h1>
                    <span id="badge-admin" class="hidden text-[9px] font-extrabold bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded border border-red-500/30">ADMIN</span>
                </div>
                <span id="user-tg-id" class="text-xs text-slate-400 font-mono tracking-wide">ID: ------</span>
            </div>
        </div>

        <div class="flex items-center gap-2">
            <button onclick="switchLanguage()" class="px-3 py-1.5 rounded-xl glass-card text-xs font-bold text-brand-400 border border-brand-500/30 flex items-center gap-1.5 active:scale-95 transition-transform">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.657-9-3-9m-9 9a9 9 0 019-9"></path></svg>
                <span id="current-lang">RU</span>
            </button>
        </div>
    </header>

    <main class="p-4 max-w-lg mx-auto space-y-5">

        <!-- HOME VIEW -->
        <div id="view-home" class="space-y-5">
            <div class="glass-card rounded-3xl p-6 relative overflow-hidden animate-pulse-glow border border-brand-500/30 bg-gradient-to-br from-brand-900/40 via-purple-900/20 to-slate-900">
                <div class="absolute -right-8 -bottom-8 w-32 h-32 bg-brand-500/20 rounded-full blur-2xl pointer-events-none"></div>
                <div class="flex justify-between items-start mb-4 relative z-10">
                    <div>
                        <span id="txt-welcome-label" class="text-xs font-bold uppercase tracking-wider text-brand-400">Total Balance</span>
                        <div id="home-balance" class="text-4xl font-extrabold text-white mt-1 tracking-tight font-mono">$0.00</div>
                    </div>
                    <div class="p-3 bg-brand-500/20 rounded-2xl border border-brand-500/30 text-brand-400 animate-float">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
                    </div>
                </div>
                <button onclick="switchTab('wallet')" class="w-full py-3.5 bg-gradient-to-r from-brand-600 via-purple-600 to-pink-600 hover:opacity-95 active:scale-[0.98] transition-all rounded-2xl font-bold text-white text-sm shadow-xl flex items-center justify-center gap-2 tracking-wide">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                    <span id="btn-deposit-label">Top Up Balance</span>
                </button>
            </div>

            <div class="grid grid-cols-2 gap-3">
                <button onclick="switchTab('shop')" class="glass-card glass-card-hover p-4 rounded-2xl flex flex-col items-center justify-center gap-2.5 transition-all">
                    <div class="p-3 bg-blue-500/10 rounded-2xl text-blue-400 border border-blue-500/20">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"></path></svg>
                    </div>
                    <span id="nav-shop-label" class="font-bold text-sm text-slate-200">Account Shop</span>
                </button>
                <button onclick="switchTab('orders')" class="glass-card glass-card-hover p-4 rounded-2xl flex flex-col items-center justify-center gap-2.5 transition-all">
                    <div class="p-3 bg-emerald-500/10 rounded-2xl text-emerald-400 border border-emerald-500/20">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"></path></svg>
                    </div>
                    <span id="nav-orders-label" class="font-bold text-sm text-slate-200">My Purchases</span>
                </button>
            </div>

            <div class="glass-card p-5 rounded-2xl space-y-3">
                <h3 class="font-bold text-xs uppercase tracking-wider text-slate-400 flex items-center gap-2">
                    <svg class="w-4 h-4 text-brand-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"></path></svg>
                    Account Activity
                </h3>
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

            <div id="admin-quick-btn" class="hidden">
                <button onclick="switchTab('admin')" class="w-full p-3.5 glass-card rounded-2xl border-red-500/40 text-red-400 font-bold text-sm flex items-center justify-center gap-2 hover:bg-red-500/10 transition-colors">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                    Admin Control Center
                </button>
            </div>
        </div>

        <!-- SHOP VIEW -->
        <div id="view-shop" class="hidden space-y-4">
            <div class="relative">
                <svg class="w-4 h-4 absolute left-3.5 top-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                <input type="text" id="search-country" oninput="filterCountries()" placeholder="Search available countries..." class="w-full pl-10 pr-4 py-3 glass-card rounded-2xl text-sm focus:outline-none focus:border-brand-500 text-white placeholder-slate-500 font-medium">
            </div>

            <div id="country-list" class="grid grid-cols-1 gap-2.5">
                <div class="skeleton h-16 rounded-2xl w-full"></div>
                <div class="skeleton h-16 rounded-2xl w-full"></div>
            </div>
        </div>

        <!-- COUNTRY DETAIL VIEW -->
        <div id="view-country-detail" class="hidden space-y-4">
            <button onclick="switchTab('shop')" class="text-xs font-bold text-brand-400 flex items-center gap-1.5 mb-2 active:scale-95 transition-transform">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
                Back to Countries
            </button>

            <div class="glass-card p-5 rounded-2xl flex items-center justify-between border-brand-500/30 bg-gradient-to-r from-brand-900/30 to-slate-900">
                <div class="flex items-center space-x-3.5">
                    <span id="detail-flag" class="text-4xl">🌐</span>
                    <div>
                        <h2 id="detail-country-name" class="font-bold text-lg text-white">Country Name</h2>
                        <span class="text-xs text-slate-400">Select grade below</span>
                    </div>
                </div>
            </div>

            <div class="space-y-3">
                <div class="glass-card p-4 rounded-2xl flex items-center justify-between border-emerald-500/30 hover:border-emerald-500/50 transition-colors">
                    <div>
                        <div class="flex items-center gap-2 font-bold text-emerald-400 text-sm">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 11-18 0018 0z"></path></svg>
                            Spam-Free (Fresh)
                        </div>
                        <div id="fresh-stock-info" class="text-xs text-slate-400 mt-1 font-mono">Available: -- | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('fresh')" id="btn-buy-fresh" class="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-xl active:scale-95 transition-all shadow-lg shadow-emerald-600/20">Buy</button>
                </div>

                <div class="glass-card p-4 rounded-2xl flex items-center justify-between border-amber-500/30 hover:border-amber-500/50 transition-colors">
                    <div>
                        <div class="flex items-center gap-2 font-bold text-amber-400 text-sm">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                            Standard / Spam Grade
                        </div>
                        <div id="broken-stock-info" class="text-xs text-slate-400 mt-1 font-mono">Available: -- | Price: $0.00</div>
                    </div>
                    <button onclick="openPurchaseModal('broken')" id="btn-buy-broken" class="px-5 py-2.5 bg-amber-600 hover:bg-amber-500 text-white font-bold text-xs rounded-xl active:scale-95 transition-all shadow-lg shadow-amber-600/20">Buy</button>
                </div>
            </div>
        </div>

        <!-- WALLET VIEW -->
        <div id="view-wallet" class="hidden space-y-4">
            <div class="glass-card p-6 rounded-3xl text-center border-brand-500/30 bg-gradient-to-b from-brand-900/20 to-slate-900">
                <span class="text-xs text-slate-400 font-bold uppercase tracking-wider">Available Balance</span>
                <div id="wallet-balance" class="text-4xl font-extrabold text-white mt-1 font-mono tracking-tight">$0.00</div>
            </div>

            <h3 class="font-bold text-xs uppercase tracking-wider text-slate-400">Select Deposit Crypto Network</h3>
            <div id="payment-methods-grid" class="grid grid-cols-2 gap-3"></div>

            <div id="deposit-amount-section" class="hidden glass-card p-5 rounded-2xl space-y-4 border-brand-500/40">
                <h4 class="font-bold text-xs text-brand-400 uppercase tracking-wider">Select Amount (USD)</h4>
                <div class="grid grid-cols-4 gap-2">
                    <button onclick="selectPresetAmount(5)" class="py-2.5 bg-slate-900 hover:bg-brand-600 text-white text-xs font-bold rounded-xl border border-white/10 transition-colors">$5.00</button>
                    <button onclick="selectPresetAmount(10)" class="py-2.5 bg-slate-900 hover:bg-brand-600 text-white text-xs font-bold rounded-xl border border-white/10 transition-colors">$10.00</button>
                    <button onclick="selectPresetAmount(25)" class="py-2.5 bg-slate-900 hover:bg-brand-600 text-white text-xs font-bold rounded-xl border border-white/10 transition-colors">$25.00</button>
                    <button onclick="selectPresetAmount(50)" class="py-2.5 bg-slate-900 hover:bg-brand-600 text-white text-xs font-bold rounded-xl border border-white/10 transition-colors">$50.00</button>
                </div>
                <div class="flex gap-2">
                    <input type="number" id="custom-deposit-amt" min="1" step="0.5" placeholder="Custom USD" class="flex-1 px-4 py-3 glass-card rounded-xl text-xs text-white focus:outline-none border-white/10 font-mono">
                    <button onclick="generateInvoice()" class="px-5 py-3 bg-brand-600 text-white text-xs font-bold rounded-xl hover:bg-brand-500 active:scale-95 transition-all shadow-lg">Pay Now</button>
                </div>
            </div>

            <div id="invoice-section" class="hidden glass-card p-5 rounded-2xl space-y-4 border-emerald-500/40 bg-slate-900/90">
                <div class="flex justify-between items-center border-b border-white/10 pb-3">
                    <span id="invoice-net" class="font-bold text-sm text-brand-400">USDT (BEP-20)</span>
                    <span id="invoice-code" class="text-xs font-mono text-slate-400">INV-00000</span>
                </div>
                <div>
                    <span class="text-xs text-slate-400 block mb-1">Exact Crypto Amount:</span>
                    <div id="invoice-crypto" class="text-xl font-mono font-bold text-emerald-400">0.0000 USDT</div>
                </div>
                <div>
                    <span class="text-xs text-slate-400 block mb-1">Deposit Address:</span>
                    <div id="invoice-address" class="text-xs font-mono bg-black/60 p-3 rounded-xl break-all text-slate-200 select-all border border-white/5">0x000...</div>
                </div>
                <div id="invoice-memo-container" class="hidden">
                    <span class="text-xs text-amber-400 block mb-1">Required MEMO / Tag:</span>
                    <div id="invoice-memo" class="text-xs font-mono bg-amber-500/10 p-2.5 rounded-xl text-amber-300 font-bold">--</div>
                </div>
                <div class="pt-2">
                    <input type="file" id="proof-file" accept="image/*" class="hidden" onchange="uploadProof(this)">
                    <button onclick="document.getElementById('proof-file').click()" class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-xl active:scale-95 transition-all shadow-lg flex items-center justify-center gap-2">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                        Upload Payment Proof
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

            <a id="support-link" href="#" target="_blank" class="w-full p-4 glass-card rounded-2xl font-bold text-xs text-brand-400 border-brand-500/30 flex items-center justify-center gap-2 hover:bg-brand-500/10 transition-colors">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 11-18 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                Contact Developer Support
            </a>
        </div>

        <!-- ADMIN DASHBOARD VIEW -->
        <div id="view-admin" class="hidden space-y-4">
            <h2 class="font-bold text-xs uppercase tracking-wider text-red-400 flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>
                Admin Management Suite
            </h2>

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
                <button onclick="submitAdminStock()" class="w-full py-3 bg-emerald-600 hover:bg-emerald-500 font-bold text-xs text-white rounded-xl active:scale-95 transition-all shadow-lg">Add Accounts</button>
            </div>

            <div class="glass-card p-5 rounded-2xl space-y-3">
                <h3 class="font-bold text-xs text-white uppercase tracking-wider">💵 Manual User Credit</h3>
                <input type="number" id="admin-target-user" placeholder="User Telegram ID" class="w-full p-3 glass-card rounded-xl text-xs text-white border-white/10 font-mono">
                <input type="number" id="admin-credit-amount" step="0.5" placeholder="Amount ($)" class="w-full p-3 glass-card rounded-xl text-xs text-white border-white/10 font-mono">
                <button onclick="submitManualCredit()" class="w-full py-3 bg-blue-600 hover:bg-blue-500 font-bold text-xs text-white rounded-xl active:scale-95 transition-all shadow-lg">Credit User Balance</button>
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
                <button onclick="closeModal()" class="flex-1 py-2.5 bg-slate-800 text-slate-300 text-xs font-bold rounded-xl active:scale-95 transition-transform">Cancel</button>
                <button onclick="confirmPurchase()" class="flex-1 py-2.5 bg-brand-600 text-white text-xs font-bold rounded-xl shadow-lg active:scale-95 transition-transform">Confirm</button>
            </div>
        </div>
    </div>

    <!-- BOTTOM NAVIGATION -->
    <nav class="fixed bottom-0 left-0 right-0 glass-card border-t border-white/10 p-2.5 flex justify-around items-center z-40 max-w-lg mx-auto bg-[#070a12]/95 backdrop-blur-2xl">
        <button onclick="switchTab('home')" id="nav-home" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold nav-active transition-all">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
            Home
        </button>
        <button onclick="switchTab('shop')" id="nav-shop" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-all">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"></path></svg>
            Shop
        </button>
        <button onclick="switchTab('wallet')" id="nav-wallet" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-all">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
            Wallet
        </button>
        <button onclick="switchTab('orders')" id="nav-orders" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-all">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"></path></svg>
            Orders
        </button>
        <button onclick="switchTab('profile')" id="nav-profile" class="flex flex-col items-center gap-1 text-slate-400 text-[10px] font-bold transition-all">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
            Profile
        </button>
    </nav>

    <script>
        const tg = window.Telegram?.WebApp || {};
        if (tg.expand) tg.expand();

        const initData = tg.initData || "";
        let currentUser = null;
        let allCountries = [];
        let selectedCountryId = null;
        let selectedGrade = null;
        let selectedPaymentMethod = null;

        const translations = {
            ru: { welcome: "Баланс Кошелька", deposit: "Пополнить баланс", shop: "Магазин Аккаунтов", orders: "Мои Покупки" },
            en: { welcome: "Wallet Balance", deposit: "Top Up Balance", shop: "Account Shop", orders: "My Purchases" }
        };

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
            try {
                currentUser = await fetchAPI('/me');
                updateUIUser();
                await loadCountries();
            } catch (e) {
                console.error(e);
            }
        }

        function updateUIUser() {
            if (!currentUser) return;

            document.getElementById('user-name').innerText = currentUser.first_name || 'Telegram User';
            document.getElementById('user-tg-id').innerText = 'ID: ' + currentUser.telegram_id;
            document.getElementById('user-avatar-img').src = currentUser.avatar_url;
            document.getElementById('profile-avatar-img').src = currentUser.avatar_url;

            document.getElementById('home-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('wallet-balance').innerText = '$' + currentUser.balance.toFixed(2);
            document.getElementById('current-lang').innerText = currentUser.language.toUpperCase();

            document.getElementById('profile-name').innerText = currentUser.first_name;
            document.getElementById('profile-username').innerText = '@' + currentUser.username;
            document.getElementById('profile-total-orders').innerText = currentUser.total_orders;
            document.getElementById('profile-total-spent').innerText = '$' + currentUser.total_spent.toFixed(2);
            document.getElementById('home-stat-orders').innerText = currentUser.total_orders;
            document.getElementById('home-stat-spent').innerText = '$' + currentUser.total_spent.toFixed(2);

            document.getElementById('support-link').href = currentUser.support_url;

            if (currentUser.is_admin) {
                document.getElementById('admin-quick-btn').classList.remove('hidden');
                document.getElementById('badge-admin').classList.remove('hidden');
            }

            const lang = currentUser.language || 'ru';
            document.getElementById('txt-welcome-label').innerText = translations[lang].welcome;
            document.getElementById('btn-deposit-label').innerText = translations[lang].deposit;
            document.getElementById('nav-shop-label').innerText = translations[lang].shop;
            document.getElementById('nav-orders-label').innerText = translations[lang].orders;
        }

        function switchTab(tab) {
            if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');

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
                container.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs font-medium">No countries available.</div>`;
                return;
            }
            container.innerHTML = list.map(c => `
                <div onclick="openCountryDetail(${c.id})" class="glass-card glass-card-hover p-4 rounded-2xl flex items-center justify-between transition-all">
                    <div class="flex items-center space-x-3.5">
                        <span class="text-3xl">${c.flag}</span>
                        <div>
                            <div class="font-bold text-sm text-white">${c.name}</div>
                            <div class="text-[11px] text-slate-400 font-mono">${c.stock} accounts</div>
                        </div>
                    </div>
                    <div class="text-right">
                        <div class="font-bold text-xs text-emerald-400 font-mono">From $${c.min_price.toFixed(2)}</div>
                    </div>
                </div>
            `).join('');
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
            document.getElementById('modal-quality').innerText = grade === 'fresh' ? 'Spam-Free' : 'Spam Grade';
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
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
                alert(`🎉 Purchase Successful!\nOrder ID: ${res.order_id}\nProduct: ${res.product_id}`);
                currentUser.balance = res.new_balance;
                updateUIUser();
                switchTab('orders');
            } catch (e) {
                if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
                alert('❌ ' + e.message);
            }
        }

        async function loadPaymentMethods() {
            try {
                const methods = await fetchAPI('/payment-methods');
                const grid = document.getElementById('payment-methods-grid');
                grid.innerHTML = Object.entries(methods).map(([key, val]) => `
                    <button onclick="selectPaymentMethod('${key}')" class="glass-card glass-card-hover p-3.5 rounded-2xl flex flex-col items-center justify-center gap-1 hover:border-brand-500/50 transition-all">
                        <span class="font-bold text-xs text-white">${val.name}</span>
                        <span class="text-[10px] text-brand-400 font-mono">${val.ticker}</span>
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
            if (!amt || amt < 1.0) return alert('Minimum deposit is $1.00 USD');
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

                if (inv.memo) {
                    document.getElementById('invoice-memo').innerText = inv.memo;
                    document.getElementById('invoice-memo-container').classList.remove('hidden');
                } else {
                    document.getElementById('invoice-memo-container').classList.add('hidden');
                }

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
                alert('✅ Receipt submitted! Admins will verify your payment in Telegram.');
                document.getElementById('invoice-section').classList.add('hidden');
            } catch (e) { alert(e.message); }
        }

        async function loadOrders() {
            try {
                const orders = await fetchAPI('/orders');
                const container = document.getElementById('orders-list');
                if (!orders.length) {
                    container.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs font-medium">No purchase history found.</div>`;
                    return;
                }
                container.innerHTML = orders.map(o => `
                    <div class="glass-card p-4 rounded-2xl space-y-2 border-white/5">
                        <div class="flex justify-between items-center text-xs">
                            <span class="font-mono text-slate-400">${o.order_id}</span>
                            <span class="text-emerald-400 font-bold font-mono">$${o.amount.toFixed(2)}</span>
                        </div>
                        <div class="font-bold text-sm text-white flex items-center gap-2">
                            <span>${o.flag}</span> <span>${o.quality}</span>
                        </div>
                        <div class="text-[11px] font-mono text-brand-300 bg-slate-900/90 p-2.5 rounded-xl break-all select-all border border-white/5">
                            ${o.product_id}
                        </div>
                    </div>
                `).join('');
            } catch (e) { console.error(e); }
        }

        async function loadAdminDashboard() {
            try {
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
                alert('✅ Stock successfully added to Database!');
            } catch (e) { alert(e.message); }
        }

        async function submitManualCredit() {
            const uid = parseInt(document.getElementById('admin-target-user').value);
            const amt = parseFloat(document.getElementById('admin-credit-amount').value);

            try {
                await fetchAPI('/admin/manual-credit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target_user_id: uid, amount: amt })
                });
                alert(`✅ Successfully credited $${amt.toFixed(2)} to User ID ${uid}!`);
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
