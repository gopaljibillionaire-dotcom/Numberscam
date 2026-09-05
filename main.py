import asyncio
import datetime
import html
import logging
import random
from typing import Optional, List

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)

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
from countries import ALL_COUNTRIES_DATA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger("digital_store_bot")

# --- MONGODB CONNECTION ---
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DATABASE_NAME]

users_col = db["users"]
countries_col = db["countries"]
products_col = db["products"]
orders_col = db["orders"]
topups_col = db["topups"]

async def init_db():
    await users_col.create_index("telegram_id", unique=True)
    await countries_col.create_index("code", unique=True)
    await countries_col.create_index("id", unique=True)
    await products_col.create_index("product_id", unique=True)
    await orders_col.create_index("order_id", unique=True)
    await topups_col.create_index("topup_id", unique=True)

    # Sync countries list to MongoDB
    idx = 1
    for code, name, flag in sorted(ALL_COUNTRIES_DATA, key=lambda x: x[1]):
        await countries_col.update_one(
            {"code": code},
            {"$setOnInsert": {"id": idx}, "$set": {"name": name, "flag": flag, "is_enabled": 1}},
            upsert=True
        )
        idx += 1

# --- HELPER FUNCTIONS ---

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

class AddProductFSM(StatesGroup):
    select_country = State()
    select_quality = State()
    enter_price = State()
    enter_content = State()

class RechargeFSM(StatesGroup):
    select_method = State()
    select_amount = State()
    custom_amount = State()
    upload_proof = State()

def get_main_keyboard(user_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    t = TEXTS.get(lang, TEXTS["ru"])
    buttons = [
        [
            InlineKeyboardButton(text=t["btn_buy_account"], callback_data="buy_cat:account:1", style="primary")
        ],
        [
            InlineKeyboardButton(text=t["btn_topup"], callback_data="wallet_topup", style="success")
        ],
        [
            InlineKeyboardButton(text=t["btn_orders"], callback_data="my_orders"),
            InlineKeyboardButton(text=t["btn_profile"], callback_data="my_profile")
        ],
        [
            InlineKeyboardButton(text=t["btn_help"], callback_data="help"),
            InlineKeyboardButton(text=t["btn_support"], url=DEVELOPER_SUPPORT_LINK)
        ],
        [
            InlineKeyboardButton(text="🌐 Язык / Language", callback_data="switch_lang")
        ]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text=t["btn_admin"], callback_data="admin_panel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_home_buttons(lang: str = "ru") -> List[List[InlineKeyboardButton]]:
    t = TEXTS.get(lang, TEXTS["ru"])
    return [
        [InlineKeyboardButton(text=t["btn_support"], url=DEVELOPER_SUPPORT_LINK)],
        [InlineKeyboardButton(text=t["btn_home"], callback_data="main_menu", style="primary")]
    ]

router = Router()

async def get_or_create_user(telegram_id: int, username: Optional[str], first_name: Optional[str]) -> dict:
    user = await users_col.find_one({"telegram_id": telegram_id})
    if not user:
        user_data = {
            "telegram_id": telegram_id,
            "username": username or "N/A",
            "first_name": first_name or "User",
            "language": None,
            "balance": 0.0,
            "is_blocked": 0,
            "created_at": datetime.datetime.utcnow()
        }
        await users_col.insert_one(user_data)
        user = user_data
    return user

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if user.get('is_blocked'):
        await message.answer("❌ <i>Ваш аккаунт заблокирован.</i>", parse_mode="HTML")
        return

    if user.get('language') is None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="first_lang:ru", style="primary"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="first_lang:en", style="primary")
            ]
        ])
        await message.answer(TEXTS["ru"]["first_time_prompt"], reply_markup=kb, parse_mode="HTML")
        return

    lang = user['language']
    t = TEXTS[lang]
    text = t["welcome"].format(
        name=html.escape(user['first_name']),
        user_id=user['telegram_id'],
        balance=user['balance']
    )
    await message.answer(text, reply_markup=get_main_keyboard(message.from_user.id, lang), parse_mode="HTML")

@router.message(F.document, F.from_user.id.in_(ADMIN_IDS))
async def process_admin_document_import(message: Message, state: FSMContext):
    file_name = message.document.file_name.lower()
    current_state = await state.get_state()
    
    if file_name.endswith(".txt") and current_state == AddProductFSM.enter_content.state:
        file_id = message.document.file_id
        file_info = await message.bot.get_file(file_id)
        downloaded = await message.bot.download_file(file_info.file_path)
        raw_content = downloaded.read().decode("utf-8", errors="ignore")
        
        lines = [line.strip() for line in raw_content.split("\n") if line.strip()]
        if not lines:
            await message.answer("❌ The uploaded .txt file is empty or contains invalid content.")
            return

        data = await state.get_data()
        admin_id = message.from_user.id
        added_count = 0

        for item in lines:
            prod_id = item.upper()
            try:
                await products_col.update_one(
                    {"product_id": prod_id},
                    {"$set": {
                        "product_id": prod_id,
                        "seller_id": admin_id,
                        "type": "account",
                        "country_id": data['country_id'],
                        "price": data['price'],
                        "quality": data['quality'],
                        "bin_link": "",
                        "status": "available",
                        "created_at": datetime.datetime.utcnow()
                    }},
                    upsert=True
                )
                added_count += 1
            except Exception as e:
                logger.error(f"Failed to add item '{item}': {e}")

        current_total = data.get('uploaded_total', 0) + added_count
        await state.update_data(uploaded_total=current_total)

        exit_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Finish / Exit Upload Mode", callback_data="exit_upload", style="danger")]
        ])

        await message.answer(
            f"✅ <b>TXT FILE IMPORTED! (+{added_count} Accounts)</b>\n"
            f"📊 <b>Total Uploaded in this Session:</b> <code>{current_total}</code>\n\n"
            f"📥 <i>Send more text files or raw lines to continue, or tap Finish below.</i>",
            reply_markup=exit_kb,
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("first_lang:"))
async def cb_first_lang_selection(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id

    await users_col.update_one({"telegram_id": user_id}, {"$set": {"language": lang}})
    user = await get_or_create_user(user_id, callback.from_user.username, callback.from_user.first_name)
    t = TEXTS[lang]
    text = t["welcome"].format(
        name=html.escape(user['first_name']),
        user_id=user['telegram_id'],
        balance=user['balance']
    )
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(user_id, lang), parse_mode="HTML")

@router.callback_query(F.data == "switch_lang")
async def cb_switch_language_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang:ru", style="primary"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang:en", style="primary")
        ],
        [InlineKeyboardButton(text="⬅️ Back / Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("🌐 Select Language / Выберите Язык:", reply_markup=kb)

@router.callback_query(F.data.startswith("set_lang:"))
async def cb_set_language(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id

    await users_col.update_one({"telegram_id": user_id}, {"$set": {"language": lang}})
    user = await get_or_create_user(user_id, callback.from_user.username, callback.from_user.first_name)
    t = TEXTS[lang]
    text = t["welcome"].format(
        name=html.escape(user['first_name']),
        user_id=user['telegram_id'],
        balance=user['balance']
    )
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(user_id, lang), parse_mode="HTML")

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]
    
    text = t["welcome"].format(
        name=html.escape(user['first_name']),
        user_id=user['telegram_id'],
        balance=user['balance']
    )
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(callback.from_user.id, lang), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_cat:"))
async def cb_select_category(callback: CallbackQuery):
    parts = callback.data.split(":")
    p_type = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 1
    per_page = 20

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    total_countries = await countries_col.count_documents({"is_enabled": 1})
    total_pages = max(1, (total_countries + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    cursor = countries_col.find({"is_enabled": 1}).sort("name", 1).skip(offset).limit(per_page)
    countries = await cursor.to_list(length=per_page)

    buttons = []
    for i in range(0, len(countries), 2):
        row_btns = []
        c1 = countries[i]
        st1 = await products_col.count_documents({"country_id": c1['id'], "status": "available"})
        row_btns.append(InlineKeyboardButton(
            text=f"{c1['flag']} {c1['name'].split(' (')[0]} [{st1}]",
            callback_data=f"buy_country:{p_type}:{c1['id']}:{page}"
        ))

        if i + 1 < len(countries):
            c2 = countries[i + 1]
            st2 = await products_col.count_documents({"country_id": c2['id'], "status": "available"})
            row_btns.append(InlineKeyboardButton(
                text=f"{c2['flag']} {c2['name'].split(' (')[0]} [{st2}]",
                callback_data=f"buy_country:{p_type}:{c2['id']}:{page}"
            ))
        buttons.append(row_btns)

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"buy_cat:{p_type}:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="ignore"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"buy_cat:{p_type}:{page + 1}"))

    buttons.append(nav_buttons)
    buttons.extend(back_home_buttons(lang))
    
    text = t["select_country"].format(page=page, total_pages=total_pages)
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_country:"))
async def cb_select_quality_grade(callback: CallbackQuery):
    parts = callback.data.split(":")
    p_type = parts[1]
    country_id = int(parts[2])
    back_page = parts[3] if len(parts) > 3 else "1"

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    country = await countries_col.find_one({"id": country_id})
    fresh_label = t["fresh_acc_label"]
    broken_label = t["broken_acc_label"]

    fresh_count = await products_col.count_documents({
        "country_id": country_id,
        "quality": {"$regex": "Spam-Free", "$options": "i"},
        "status": "available"
    })

    broken_count = await products_col.count_documents({
        "country_id": country_id,
        "quality": {"$not": {"$regex": "Spam-Free", "$options": "i"}},
        "status": "available"
    })

    buttons = [
        [InlineKeyboardButton(text=f"{fresh_label} [{fresh_count}]", callback_data=f"list_prods:{p_type}:{country_id}:fresh:1:{back_page}", style="success")],
        [InlineKeyboardButton(text=f"{broken_label} [{broken_count}]", callback_data=f"list_prods:{p_type}:{country_id}:broken:1:{back_page}", style="danger")],
        [InlineKeyboardButton(text=t["btn_back"], callback_data=f"buy_cat:{p_type}:{back_page}")]
    ]
    
    text = t["select_quality"].format(flag=country['flag'], country=country['name'].upper())
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("list_prods:"))
async def cb_list_products(callback: CallbackQuery):
    parts = callback.data.split(":")
    p_type = parts[1]
    country_id = int(parts[2])
    grade = parts[3]
    prod_page = int(parts[4]) if len(parts) > 4 else 1
    back_page = parts[5] if len(parts) > 5 else "1"

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    query = {"country_id": country_id, "status": "available"}
    if grade == "fresh":
        query["quality"] = {"$regex": "Spam-Free", "$options": "i"}
    else:
        query["quality"] = {"$not": {"$regex": "Spam-Free", "$options": "i"}}

    total_items = await products_col.count_documents(query)

    if total_items == 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t["btn_back"], callback_data=f"buy_country:{p_type}:{country_id}:{back_page}")]])
        await callback.message.edit_text(t["out_of_stock"], reply_markup=kb, parse_mode="HTML")
        return

    per_page = 5
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    offset = (prod_page - 1) * per_page

    cursor = products_col.find(query).skip(offset).limit(per_page)
    products = await cursor.to_list(length=per_page)

    text = t["catalog_title"]
    buttons = []

    text += f"📄 <b>Page {prod_page}/{total_pages}</b> (Showing {len(products)} of {total_items} items):\n\n"
    for p in products:
        text += f"🔹 <b>ID:</b> <code>{html.escape(p['product_id'])}</code> — Price: <b>${p['price']:.2f}</b>\n"
        buttons.append([InlineKeyboardButton(
            text=f"🛒 Buy {p['product_id']} (${p['price']:.2f})",
            callback_data=f"exec_buy:{p['product_id']}",
            style="success"
        )])

    nav_buttons = []
    if prod_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"list_prods:{p_type}:{country_id}:{grade}:{prod_page - 1}:{back_page}"))
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {prod_page}/{total_pages}", callback_data="ignore"))
    if prod_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"list_prods:{p_type}:{country_id}:{grade}:{prod_page + 1}:{back_page}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text=t["btn_back"], callback_data=f"buy_country:{p_type}:{country_id}:{back_page}")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML", disable_web_page_preview=True)

@router.callback_query(F.data.startswith("exec_buy:"))
async def cb_execute_buy_fresh(callback: CallbackQuery):
    prod_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    user = await get_or_create_user(user_id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    async with await mongo_client.start_session() as session:
        async with session.start_transaction():
            u_doc = await users_col.find_one({"telegram_id": user_id}, session=session)
            p_doc = await products_col.find_one({"product_id": prod_id, "status": "available"}, session=session)

            if not p_doc:
                await callback.answer("❌ Account already sold!", show_alert=True)
                return

            if u_doc['balance'] < p_doc['price']:
                await callback.answer(t["insufficient_funds"].format(price=p_doc['price']), show_alert=True)
                return

            new_balance = u_doc['balance'] - p_doc['price']
            await users_col.update_one({"telegram_id": user_id}, {"$set": {"balance": new_balance}}, session=session)
            await products_col.update_one({"product_id": prod_id}, {"$set": {"status": "sold"}}, session=session)

            order_id = f"ORD-{random.randint(100000, 999999)}"
            await orders_col.insert_one({
                "order_id": order_id,
                "user_id": user_id,
                "product_id": prod_id,
                "amount": p_doc['price'],
                "status": "completed",
                "created_at": datetime.datetime.utcnow()
            }, session=session)

            text = t["purchase_success"].format(
                order_id=order_id,
                prod_id=html.escape(prod_id),
                price=p_doc['price'],
                balance=new_balance
            )
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML")

@router.callback_query(F.data == "wallet_topup")
async def cb_wallet_topup_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]
    
    await state.set_state(RechargeFSM.select_method)
    
    buttons = [
        [
            InlineKeyboardButton(text="USDT (BEP-20)", callback_data="dep_method:usdt_bep20", style="primary"),
            InlineKeyboardButton(text="USDT (ERC-20)", callback_data="dep_method:usdt_erc20", style="primary")
        ],
        [
            InlineKeyboardButton(text="USDT (Polygon)", callback_data="dep_method:usdt_poly", style="primary"),
            InlineKeyboardButton(text="USDT (TON)", callback_data="dep_method:usdt_ton", style="primary")
        ],
        [InlineKeyboardButton(text=t["btn_support"], url=DEVELOPER_SUPPORT_LINK)],
        [InlineKeyboardButton(text=t["btn_home"], callback_data="main_menu")]
    ]
    
    text = t["dep_title"].format(balance=user['balance'])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("dep_method:"), StateFilter(RechargeFSM.select_method))
async def cb_topup_select_amount(callback: CallbackQuery, state: FSMContext):
    method_key = callback.data.split(":")[1]
    method_info = PAYMENT_METHODS.get(method_key)
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]
    
    if not method_info:
        await callback.answer("Invalid Payment Method Selected", show_alert=True)
        return

    await state.update_data(method_key=method_key)
    await state.set_state(RechargeFSM.select_amount)

    buttons = [
        [
            InlineKeyboardButton(text="$4.50", callback_data="dep_amt:4.5"),
            InlineKeyboardButton(text="$10.00", callback_data="dep_amt:10.0")
        ],
        [
            InlineKeyboardButton(text="$15.00", callback_data="dep_amt:15.0"),
            InlineKeyboardButton(text="$25.00", callback_data="dep_amt:25.0")
        ],
        [InlineKeyboardButton(text="✏️ Custom Amount / Своя сумма USD", callback_data="dep_amt:custom", style="primary")],
        [InlineKeyboardButton(text=t["btn_back"], callback_data="wallet_topup")]
    ]

    text = t["dep_select_amt"].format(method=method_info['name'])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("dep_amt:"), StateFilter(RechargeFSM.select_amount))
async def cb_topup_preset_amount(callback: CallbackQuery, state: FSMContext):
    amt_str = callback.data.split(":")[1]
    
    if amt_str == "custom":
        await state.set_state(RechargeFSM.custom_amount)
        await callback.message.edit_text(
            "✍️ <b>Enter amount in USD ($) / Введите сумму в USD ($):</b>\n\n<blockquote>Minimum deposit / Минимальный депозит: $4.50 USD.</blockquote>",
            parse_mode="HTML"
        )
        return
        
    amount = float(amt_str)
    await generate_invoice(callback, state, amount)

@router.message(StateFilter(RechargeFSM.custom_amount))
async def process_custom_topup_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount < 4.50:
            await message.answer("⚠️ <b>Minimum deposit is $4.50 USD / Минимальное пополнение: $4.50 USD.</b>", parse_mode="HTML")
            return
    except ValueError:
        await message.answer("❌ Invalid amount format. Please enter a valid number:")
        return

    await generate_invoice(message, state, amount)

async def generate_invoice(event: CallbackQuery | Message, state: FSMContext, amount: float):
    data = await state.get_data()
    method_key = data.get("method_key", "usdt_bep20")
    method_info = PAYMENT_METHODS[method_key]
    
    invoice_code = f"INV-{random.randint(10000, 99999)}"
    crypto_price = await get_crypto_price_usd(method_info["coingecko_id"])
    calculated = amount / crypto_price
    unique_offset = random.randint(1, 99) * 0.0001
    coin_amount = f"{calculated + unique_offset:.4f}"

    await state.update_data(
        invoice_code=invoice_code,
        amount=amount,
        crypto_amount=coin_amount,
        address=method_info['address']
    )

    memo_str = f"\n📌 <b>MEMO / Tag:</b> <code>{method_info['memo']}</code>" if method_info.get('memo') else ""

    text = (
        f"📥 <b>{method_info['name']} DEPOSIT / ПОПОЛНЕНИЕ</b>\n"
        f"═══════════════════════\n\n"
        f"💳 <b>Amount due / К оплате:</b> <code>{coin_amount} {method_info['ticker']}</code> (${amount:.2f})\n"
        f"🧾 <b>Invoice / Инвойс:</b> <code>{invoice_code}</code>\n\n"
        f"💲 <b>Wallet Address / Адрес кошелька:</b>\n"
        f"<code>{method_info['address']}</code>{memo_str}\n\n"
        f"<blockquote>⚠️ Send EXACTLY <b>{coin_amount} {method_info['ticker']}</b>.</blockquote>"
    )

    buttons = [
        [InlineKeyboardButton(text="📋 Copy Address / Скопировать адрес", callback_data=f"copy_addr:{method_key}")],
        [InlineKeyboardButton(text=f"📋 Copy Amount / Скопировать · {coin_amount}", callback_data=f"copy_amt:{coin_amount}")],
        [InlineKeyboardButton(text="✅ I Have Paid / Я оплатил", callback_data=f"topup_paid:{invoice_code}", style="success")],
        [InlineKeyboardButton(text="💬 Support", url=DEVELOPER_SUPPORT_LINK)],
        [InlineKeyboardButton(text="Back / Назад", callback_data="wallet_topup")]
    ]
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("copy_addr:"))
async def cb_copy_address(callback: CallbackQuery):
    method_key = callback.data.split(":")[1]
    addr = PAYMENT_METHODS[method_key]['address']
    await callback.answer(f"Address Copied: {addr}", show_alert=True)

@router.callback_query(F.data.startswith("copy_amt:"))
async def cb_copy_amount(callback: CallbackQuery):
    amt = callback.data.split(":")[1]
    await callback.answer(f"Amount Copied: {amt}", show_alert=True)

@router.callback_query(F.data.startswith("topup_paid:"))
async def cb_topup_i_have_paid(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    await state.set_state(RechargeFSM.upload_proof)
    await callback.message.answer(t["upload_proof"], parse_mode="HTML")

@router.message(StateFilter(RechargeFSM.upload_proof), F.photo)
async def process_proof_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    invoice_code = data.get('invoice_code', f"INV-{random.randint(10000, 99999)}")
    amount = data.get('amount', 0.0)
    crypto_amount = data.get('crypto_amount', 'N/A')
    method_key = data.get('method_key', 'usdt_bep20')
    method_name = PAYMENT_METHODS.get(method_key, {}).get('name', method_key)

    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    await topups_col.insert_one({
        "topup_id": invoice_code,
        "user_id": message.from_user.id,
        "amount": amount,
        "method": method_name,
        "crypto_amount": crypto_amount,
        "status": "pending",
        "created_at": datetime.datetime.utcnow()
    })

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_appr_topup:{invoice_code}", style="success"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_topup:{invoice_code}", style="danger")
        ]
    ])

    admin_text = (
        f"🚨 <b>NEW TOP-UP REQUEST</b>\n"
        f"═══════════════════════\n\n"
        f"🧾 <b>Invoice:</b> <code>{invoice_code}</code>\n"
        f"👤 <b>User ID:</b> <code>{message.from_user.id}</code>\n"
        f"🌐 <b>Network:</b> {method_name}\n"
        f"💎 <b>Crypto Amount:</b> <code>{crypto_amount}</code>\n"
        f"💵 <b>USD Value:</b> <code>${amount:.2f}</code>"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(chat_id=admin_id, photo=photo_id, caption=admin_text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    await state.clear()
    await message.answer(t["proof_submitted"], reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_appr_topup:"))
async def cb_admin_approve_topup(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    topup_id = callback.data.split(":")[1]

    topup = await topups_col.find_one({"topup_id": topup_id, "status": "pending"})
    if topup:
        await topups_col.update_one({"topup_id": topup_id}, {"$set": {"status": "approved"}})
        await users_col.update_one({"telegram_id": topup['user_id']}, {"$inc": {"balance": topup['amount']}})
        try:
            await callback.bot.send_message(topup['user_id'], f"🎉 <b>Deposit Approved! / Депозит одобрен!</b>\n\n<code>${topup['amount']:.2f} USD</code> credited to your wallet.", parse_mode="HTML")
        except Exception:
            pass

    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n✅ <b>APPROVED BY ADMIN</b>", parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_rej_topup:"))
async def cb_admin_reject_topup(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    topup_id = callback.data.split(":")[1]

    topup = await topups_col.find_one({"topup_id": topup_id, "status": "pending"})
    if topup:
        await topups_col.update_one({"topup_id": topup_id}, {"$set": {"status": "rejected"}})
        try:
            await callback.bot.send_message(topup['user_id'], f"❌ Top-up request for <b>${topup['amount']:.2f} USD</b> rejected.", parse_mode="HTML")
        except Exception:
            pass

    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n❌ <b>REJECTED BY ADMIN</b>", parse_mode="HTML")

# --- ADMIN PANEL AND STORAGE MANAGEMENT ---

@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Bulk Add Account Stock", callback_data="admin_add_prod", style="success")],
        [InlineKeyboardButton(text="📤 Export Full Stock (.txt)", callback_data="admin_export_txt")],
        [InlineKeyboardButton(text="📊 Check Storage Usage", callback_data="admin_check_storage", style="primary")],
        [InlineKeyboardButton(text="⚠️ Delete All Database", callback_data="admin_clear_db_confirm", style="danger")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
    ])
    await callback.message.edit_text("👨‍💻 <b>ADMIN CONTROL PANEL</b>\n\nSelect operation mode:\n\n<i>Send a `.txt` file during upload mode to import stock.</i>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "admin_check_storage")
async def cb_admin_check_storage(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return

    try:
        stats = await db.command("dbStats")
        data_size_mb = stats.get("dataSize", 0) / (1024 * 1024)
        storage_size_mb = stats.get("storageSize", 0) / (1024 * 1024)
        index_size_mb = stats.get("indexSize", 0) / (1024 * 1024)
        
        # Free MongoDB Tier usually cap at 512 MB
        max_storage_mb = 512.0
        available_mb = max(0.0, max_storage_mb - storage_size_mb)

        text = (
            f"📊 <b>MONGODB STORAGE STATISTICS</b>\n"
            f"═══════════════════════\n\n"
            f"💾 <b>Data Size:</b> <code>{data_size_mb:.2f} MB</code>\n"
            f"📦 <b>Storage Used:</b> <code>{storage_size_mb:.2f} MB</code>\n"
            f"🗂️ <b>Indexes Size:</b> <code>{index_size_mb:.2f} MB</code>\n"
            f"🟢 <b>Available Space:</b> <code>{available_mb:.2f} MB</code> / {max_storage_mb:.0f} MB\n"
            f"📑 <b>Total Collections:</b> <code>{stats.get('collections', 0)}</code>"
        )
    except Exception as e:
        text = f"❌ <b>Error fetching storage stats:</b>\n<code>{e}</code>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Admin Panel", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "admin_clear_db_confirm")
async def cb_admin_clear_db_confirm(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ YES, DELETE ENTIRE DB ⚠️", callback_data="admin_clear_db_execute", style="danger")],
        [InlineKeyboardButton(text="❌ CANCEL", callback_data="admin_panel", style="primary")]
    ])
    await callback.message.edit_text(
        "🚨 <b>WARNING: DELETE ALL DATABASE DATA</b> 🚨\n\n"
        "Are you sure you want to completely clear the entire MongoDB database?\n"
        "<i>This action will delete all user accounts, orders, deposits, and stock.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin_clear_db_execute")
async def cb_admin_clear_db_execute(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return

    await users_col.delete_many({})
    await products_col.delete_many({})
    await orders_col.delete_many({})
    await topups_col.delete_many({})
    await countries_col.delete_many({})

    # Re-initialize countries and indexes
    await init_db()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu", style="primary")]
    ])
    await callback.message.edit_text("💥 <b>DATABASE CLEARED SUCCESSFULLY!</b>\n\nAll MongoDB collections have been reset.", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.in_(["btn_green", "btn_red", "btn_blue"]))
async def cb_colored_buttons_demo(callback: CallbackQuery):
    btn = callback.data
    await callback.answer(f"You clicked on styled button: {btn}", show_alert=True)

@router.callback_query(F.data == "admin_export_txt")
async def cb_admin_export_txt(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return

    pipeline = [
        {
            "$lookup": {
                "from": "countries",
                "localField": "country_id",
                "foreignField": "id",
                "as": "country_info"
            }
        },
        {"$unwind": "$country_info"},
        {"$sort": {"country_info.name": 1, "quality": 1}}
    ]
    products = await products_col.aggregate(pipeline).to_list(length=None)

    if not products:
        await callback.answer("❌ No stock/products available to export.", show_alert=True)
        return

    output_lines = ["==========================================", "       FULL STOCK DATABASE EXPORT         ", "==========================================\n"]
    current_country = ""

    for p in products:
        c_name = p['country_info']['name']
        flag = p['country_info']['flag']
        if c_name != current_country:
            current_country = c_name
            output_lines.append(f"\n--- {flag} {current_country.upper()} ---")
        
        output_lines.append(f"ID: {p['product_id']} | Quality: {p['quality']} | Price: ${p['price']:.2f} | Status: {p['status']}")

    file_bytes = "\n".join(output_lines).encode('utf-8')
    txt_file = BufferedInputFile(file_bytes, filename="full_stock_export.txt")
    
    await callback.message.answer_document(
        document=txt_file,
        caption="📄 <b>Full Stock Export (.txt) Generated Successfully!</b>",
        parse_mode="HTML"
    )
    await callback.answer("Exported!")

@router.callback_query(F.data == "admin_add_prod")
async def cb_start_add_item(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    
    await state.update_data(p_type="account")
    await render_admin_country_selection(callback, state, page=1)

@router.callback_query(F.data.startswith("admin_country_page:"), StateFilter(AddProductFSM.select_country))
async def cb_admin_country_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await render_admin_country_selection(callback, state, page=page)

async def render_admin_country_selection(callback: CallbackQuery, state: FSMContext, page: int = 1):
    per_page = 20
    total_countries = await countries_col.count_documents({"is_enabled": 1})
    total_pages = max(1, (total_countries + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    cursor = countries_col.find({"is_enabled": 1}).sort("name", 1).skip(offset).limit(per_page)
    countries = await cursor.to_list(length=per_page)

    buttons = []
    for i in range(0, len(countries), 2):
        row_btns = [InlineKeyboardButton(text=f"{countries[i]['flag']} {countries[i]['name'].split(' (')[0]}", callback_data=f"prod_c:{countries[i]['id']}")]
        if i + 1 < len(countries):
            row_btns.append(InlineKeyboardButton(text=f"{countries[i+1]['flag']} {countries[i+1]['name'].split(' (')[0]}", callback_data=f"prod_c:{countries[i+1]['id']}"))
        buttons.append(row_btns)
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin_country_page:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="ignore"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_country_page:{page + 1}"))

    buttons.append(nav_buttons)
    await state.set_state(AddProductFSM.select_country)
    await callback.message.edit_text(f"Select Target Country for Stock (Page {page}/{total_pages}):", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("prod_c:"), StateFilter(AddProductFSM.select_country))
async def cb_item_country(callback: CallbackQuery, state: FSMContext):
    c_id = int(callback.data.split(":")[1])
    await state.update_data(country_id=c_id)

    qual_buttons = [
        [InlineKeyboardButton(text="🟢 Spam-Free Account", callback_data="qual:Spam-Free Account", style="success")],
        [InlineKeyboardButton(text="🔴 Spam Account", callback_data="qual:Spam Account", style="danger")]
    ]

    await state.set_state(AddProductFSM.select_quality)
    await callback.message.edit_text("Select Account Quality Tier:", reply_markup=InlineKeyboardMarkup(inline_keyboard=qual_buttons))

@router.callback_query(F.data.startswith("qual:"), StateFilter(AddProductFSM.select_quality))
async def cb_item_qual(callback: CallbackQuery, state: FSMContext):
    qual = callback.data.split(":")[1]
    await state.update_data(quality=qual, uploaded_total=0)
    await state.set_state(AddProductFSM.enter_price)
    await callback.message.edit_text("💵 Enter unit price in USD ($):\n\n<i>Example: 0.50 or 1.20</i>", parse_mode="HTML")

@router.message(StateFilter(AddProductFSM.enter_price))
async def process_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
        if price <= 0: raise ValueError()
    except ValueError:
        await message.answer("❌ Invalid price format. Please enter a valid number:")
        return

    await state.update_data(price=price)
    await state.set_state(AddProductFSM.enter_content)
    
    exit_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Finish / Exit Upload Mode", callback_data="exit_upload", style="danger")]
    ])

    await message.answer(
        "🆔 <b>ADD ACCOUNTS (Continuous Input Mode)</b>\n\n"
        "Send Account Serial Keys line-by-line OR upload a <code>.txt</code> file directly.\n"
        "Bot will remain open for more inputs until you click Finish below.",
        reply_markup=exit_kb,
        parse_mode="HTML"
    )

@router.message(StateFilter(AddProductFSM.enter_content))
async def process_item_content(message: Message, state: FSMContext):
    data = await state.get_data()
    raw_text = message.text or message.caption or ""
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

    if not lines:
        await message.answer("❌ No valid keys found. Please try sending text or a .txt file again.")
        return

    added_count = 0
    admin_id = message.from_user.id

    for item in lines:
        prod_id = item.upper()
        try:
            await products_col.update_one(
                {"product_id": prod_id},
                {"$set": {
                    "product_id": prod_id,
                    "seller_id": admin_id,
                    "type": "account",
                    "country_id": data['country_id'],
                    "price": data['price'],
                    "quality": data['quality'],
                    "bin_link": "",
                    "status": "available",
                    "created_at": datetime.datetime.utcnow()
                }},
                upsert=True
            )
            added_count += 1
        except Exception as e:
            logger.error(f"Failed to add account '{item}': {e}")
            continue

    current_total = data.get('uploaded_total', 0) + added_count
    await state.update_data(uploaded_total=current_total)

    exit_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Finish / Exit Upload Mode", callback_data="exit_upload", style="danger")]
    ])

    await message.answer(
        f"✅ <b>BATCH SAVED! (+{added_count} Accounts)</b>\n"
        f"📊 <b>Total Uploaded in this Session:</b> <code>{current_total}</code>\n\n"
        f"📥 <i>Send more lines or a .txt file to continue adding, or tap Finish when completed.</i>",
        reply_markup=exit_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data == "exit_upload", StateFilter(AddProductFSM.enter_content))
async def cb_exit_upload_mode(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uploaded_total = data.get('uploaded_total', 0)
    await state.clear()
    
    await callback.message.edit_text(
        f"🎉 <b>UPLOAD COMPLETED SUCCESSFULLY!</b>\n═══════════════════════\n\n"
        f"📦 <b>Total Accounts Added:</b> <code>{uploaded_total}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons("ru")),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "my_profile")
async def cb_my_profile(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    pipeline = [
        {"$match": {"user_id": user['telegram_id']}},
        {"$group": {"_id": None, "total_orders": {"$sum": 1}, "total_spent": {"$sum": "$amount"}}}
    ]
    res = await orders_col.aggregate(pipeline).to_list(length=1)
    
    total_orders = res[0]['total_orders'] if res else 0
    total_spent = res[0]['total_spent'] if res else 0.0

    username_str = f"@{html.escape(user['username'])}" if user['username'] and user['username'] != "N/A" else "None"
    
    text = t["profile_title"].format(
        user_id=user['telegram_id'],
        name=html.escape(user['first_name']),
        username=username_str,
        balance=user['balance'],
        orders=total_orders,
        spent=total_spent
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML")

@router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_or_create_user(user_id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    cursor = orders_col.find({"user_id": user_id}).sort("created_at", -1).limit(5)
    orders = await cursor.to_list(length=5)

    if not orders:
        text = t["orders_empty"]
    else:
        text = t["orders_title"]
        for o in orders:
            prod = await products_col.find_one({"product_id": o['product_id']})
            quality = prod['quality'] if prod and 'quality' in prod else 'Standard Account'
            text += (
                f"📱 <b>{t['order_item_order']}:</b> <code>{o['order_id']}</code>\n"
                f"✨ <b>{t['order_item_product']}:</b> {html.escape(quality)}\n"
                f"🔑 <b>{t['order_item_key']}:</b> <code>{html.escape(o['product_id'])}</code>\n"
                f"💵 <b>{t['order_item_price']}:</b> <code>${o['amount']:.2f}</code>\n"
                f"───────────────────────\n"
            )

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML", disable_web_page_preview=True)

@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]

    total_stock = await products_col.count_documents({"status": "available"})
    text = t["help_text"].format(total_stock=total_stock)
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML")

async def main():
    bot = Bot(token=BOT_TOKEN)
    
    # Initialize MongoDB Schema / Collections
    await init_db()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Bot started successfully with MongoDB.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution stopped.")
