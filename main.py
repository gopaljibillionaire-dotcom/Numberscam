import asyncio
import html
import logging
import os
import random
from typing import Optional, List

import aiohttp
import aiosqlite
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
    FSInputFile,
    BufferedInputFile,
)

from config import (
    BOT_TOKEN,
    ADMIN_IDS,
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

async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language TEXT DEFAULT NULL,
                balance REAL DEFAULT 0.0,
                is_blocked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                flag TEXT NOT NULL,
                is_enabled INTEGER DEFAULT 1
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                seller_id INTEGER DEFAULT 0,
                type TEXT NOT NULL DEFAULT 'account',
                country_id INTEGER NOT NULL,
                price REAL NOT NULL,
                quality TEXT NOT NULL,
                bin_link TEXT DEFAULT '',
                status TEXT DEFAULT 'available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (country_id) REFERENCES countries (id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (telegram_id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topups (
                topup_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                method TEXT NOT NULL,
                crypto_amount TEXT DEFAULT '0',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (telegram_id)
            )
        """)

        for code, name, flag in sorted(ALL_COUNTRIES_DATA, key=lambda x: x[1]):
            await db.execute(
                "INSERT INTO countries (code, name, flag, is_enabled) VALUES (?, ?, ?, 1) ON CONFLICT(code) DO UPDATE SET name=excluded.name, flag=excluded.flag",
                (code, name, flag)
            )
        
        await db.commit()

def get_db():
    return aiosqlite.connect(DATABASE_NAME)

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
            InlineKeyboardButton(text=t["btn_buy_account"], callback_data="buy_cat:account:1")
        ],
        [
            InlineKeyboardButton(text=t["btn_topup"], callback_data="wallet_topup")
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
        buttons.append([InlineKeyboardButton(text=t["btn_admin"], callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_home_buttons(lang: str = "ru") -> List[List[InlineKeyboardButton]]:
    t = TEXTS.get(lang, TEXTS["ru"])
    return [
        [InlineKeyboardButton(text=t["btn_support"], url=DEVELOPER_SUPPORT_LINK)],
        [InlineKeyboardButton(text=t["btn_home"], callback_data="main_menu")]
    ]

router = Router()

async def get_or_create_user(telegram_id: int, username: Optional[str], first_name: Optional[str]) -> dict:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            user = await cursor.fetchone()
            if not user:
                await db.execute(
                    "INSERT INTO users (telegram_id, username, first_name, language) VALUES (?, ?, ?, NULL)",
                    (telegram_id, username or "N/A", first_name or "User")
                )
                await db.commit()
                async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as c2:
                    user = await c2.fetchone()
            return dict(user)

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if user['is_blocked']:
        await message.answer("❌ <i>Ваш аккаунт заблокирован.</i>", parse_mode="HTML")
        return

    if user.get('language') is None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="first_lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="first_lang:en")
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

@router.message(Command("export_db"))
async def cmd_export_db(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if os.path.exists(DATABASE_NAME):
        db_file = FSInputFile(DATABASE_NAME)
        await message.answer_document(db_file, caption="📂 <b>Database Backup Exported</b>", parse_mode="HTML")
    else:
        await message.answer("❌ Database file not found.")

@router.message(F.document, F.from_user.id.in_(ADMIN_IDS))
async def process_admin_document_import(message: Message, state: FSMContext):
    file_name = message.document.file_name.lower()
    
    # Handle Database File Import (.db)
    if file_name.endswith(".db"):
        file_id = message.document.file_id
        file_info = await message.bot.get_file(file_id)
        await message.bot.download_file(file_info.file_path, DATABASE_NAME)
        await message.answer("✅ <b>Database file imported successfully!</b>", parse_mode="HTML")
        return

    # Handle Stock Text File Import (.txt)
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

        async with get_db() as db:
            for item in lines:
                prod_id = item.upper()
                try:
                    await db.execute("""
                        INSERT INTO products (product_id, seller_id, type, country_id, price, quality, bin_link, status)
                        VALUES (?, ?, 'account', ?, ?, ?, '', 'available')
                        ON CONFLICT(product_id) DO UPDATE SET
                            seller_id=excluded.seller_id,
                            price=excluded.price,
                            quality=excluded.quality,
                            status='available'
                    """, (prod_id, admin_id, data['country_id'], data['price'], data['quality']))
                    added_count += 1
                except Exception as e:
                    logger.error(f"Failed to add item '{item}': {e}")

            await db.commit()

        current_total = data.get('uploaded_total', 0) + added_count
        await state.update_data(uploaded_total=current_total)

        exit_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Finish / Exit Upload Mode", callback_data="exit_upload")]
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

    async with get_db() as db:
        await db.execute("UPDATE users SET language = ? WHERE telegram_id = ?", (lang, user_id))
        await db.commit()

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
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang:ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang:en")
        ],
        [InlineKeyboardButton(text="⬅️ Back / Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("🌐 Select Language / Выберите Язык:", reply_markup=kb)

@router.callback_query(F.data.startswith("set_lang:"))
async def cb_set_language(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id

    async with get_db() as db:
        await db.execute("UPDATE users SET language = ? WHERE telegram_id = ?", (lang, user_id))
        await db.commit()

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

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM countries WHERE is_enabled = 1") as total_cur:
            total_countries = (await total_cur.fetchone())[0]

        total_pages = max(1, (total_countries + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        async with db.execute(
            "SELECT * FROM countries WHERE is_enabled = 1 ORDER BY name ASC LIMIT ? OFFSET ?",
            (per_page, offset)
        ) as cursor:
            countries = await cursor.fetchall()

        buttons = []
        for i in range(0, len(countries), 2):
            row_btns = []
            c1 = countries[i]
            async with db.execute(
                "SELECT COUNT(*) FROM products WHERE country_id = ? AND status = 'available'",
                (c1['id'],)
            ) as count_cur:
                st1 = (await count_cur.fetchone())[0]
            row_btns.append(InlineKeyboardButton(
                text=f"{c1['flag']} {c1['name'].split(' (')[0]} [{st1}]",
                callback_data=f"buy_country:{p_type}:{c1['id']}:{page}"
            ))

            if i + 1 < len(countries):
                c2 = countries[i + 1]
                async with db.execute(
                    "SELECT COUNT(*) FROM products WHERE country_id = ? AND status = 'available'",
                    (c2['id'],)
                ) as count_cur2:
                    st2 = (await count_cur2.fetchone())[0]
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

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM countries WHERE id = ?", (country_id,)) as c_cur:
            country = await c_cur.fetchone()

        fresh_label = t["fresh_acc_label"]
        broken_label = t["broken_acc_label"]

        async with db.execute(
            "SELECT COUNT(*) FROM products WHERE country_id = ? AND quality LIKE '%Spam-Free%' AND status = 'available'",
            (country_id,)
        ) as f_cur:
            fresh_count = (await f_cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM products WHERE country_id = ? AND quality NOT LIKE '%Spam-Free%' AND status = 'available'",
            (country_id,)
        ) as b_cur:
            broken_count = (await b_cur.fetchone())[0]

    buttons = [
        [InlineKeyboardButton(text=f"{fresh_label} [{fresh_count}]", callback_data=f"list_prods:{p_type}:{country_id}:fresh:1:{back_page}")],
        [InlineKeyboardButton(text=f"{broken_label} [{broken_count}]", callback_data=f"list_prods:{p_type}:{country_id}:broken:1:{back_page}")],
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

    quality_like = "%Spam-Free%" if grade == "fresh" else "%Spam%"

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) FROM products WHERE country_id = ? AND quality LIKE ? AND status = 'available'",
            (country_id, quality_like)
        ) as count_cur:
            total_items = (await count_cur.fetchone())[0]

        if total_items == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t["btn_back"], callback_data=f"buy_country:{p_type}:{country_id}:{back_page}")]])
            await callback.message.edit_text(t["out_of_stock"], reply_markup=kb, parse_mode="HTML")
            return

        per_page = 5
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        offset = (prod_page - 1) * per_page

        async with db.execute(
            "SELECT * FROM products WHERE country_id = ? AND quality LIKE ? AND status = 'available' LIMIT ? OFFSET ?",
            (country_id, quality_like, per_page, offset)
        ) as cursor:
            products = await cursor.fetchall()

    text = t["catalog_title"]
    buttons = []

    text += f"📄 <b>Page {prod_page}/{total_pages}</b> (Showing {len(products)} of {total_items} items):\n\n"
    for p in products:
        text += f"🔹 <b>ID:</b> <code>{html.escape(p['product_id'])}</code> — Price: <b>${p['price']:.2f}</b>\n"
        buttons.append([InlineKeyboardButton(
            text=f"🛒 Buy {p['product_id']} (${p['price']:.2f})",
            callback_data=f"exec_buy:{p['product_id']}"
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

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("BEGIN IMMEDIATE")
            
            async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (user_id,)) as u_cur:
                u_row = await u_cur.fetchone()
            
            async with db.execute("SELECT * FROM products WHERE product_id = ? AND status = 'available'", (prod_id,)) as p_cur:
                p = await p_cur.fetchone()

            if not p:
                await db.execute("ROLLBACK")
                await callback.answer("❌ Account already sold!", show_alert=True)
                return

            if u_row['balance'] < p['price']:
                await db.execute("ROLLBACK")
                await callback.answer(t["insufficient_funds"].format(price=p['price']), show_alert=True)
                return

            new_balance = u_row['balance'] - p['price']
            await db.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (new_balance, user_id))
            await db.execute("UPDATE products SET status = 'sold' WHERE product_id = ?", (prod_id,))

            order_id = f"ORD-{random.randint(100000, 999999)}"
            await db.execute(
                "INSERT INTO orders (order_id, user_id, product_id, amount, status) VALUES (?, ?, ?, ?, ?)",
                (order_id, user_id, prod_id, p['price'], "completed")
            )
            await db.commit()

            text = t["purchase_success"].format(
                order_id=order_id,
                prod_id=html.escape(prod_id),
                price=p['price'],
                balance=new_balance
            )
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML")

        except Exception as e:
            await db.execute("ROLLBACK")
            logger.error(f"Purchase Error: {e}")
            await callback.answer("❌ Purchase failed.", show_alert=True)

@router.callback_query(F.data == "wallet_topup")
async def cb_wallet_topup_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    lang = user.get('language') or 'ru'
    t = TEXTS[lang]
    
    await state.set_state(RechargeFSM.select_method)
    
    buttons = [
        [
            InlineKeyboardButton(text="USDT (BEP-20)", callback_data="dep_method:usdt_bep20"),
            InlineKeyboardButton(text="USDT (ERC-20)", callback_data="dep_method:usdt_erc20")
        ],
        [
            InlineKeyboardButton(text="USDT (Polygon)", callback_data="dep_method:usdt_poly"),
            InlineKeyboardButton(text="USDT (TON)", callback_data="dep_method:usdt_ton")
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
        [InlineKeyboardButton(text="✏️ Custom Amount / Своя сумма USD", callback_data="dep_amt:custom")],
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
        [InlineKeyboardButton(text="✅ I Have Paid / Я оплатил", callback_data=f"topup_paid:{invoice_code}")],
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

    async with get_db() as db:
        await db.execute(
            "INSERT INTO topups (topup_id, user_id, amount, method, crypto_amount, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (invoice_code, message.from_user.id, amount, method_name, crypto_amount)
        )
        await db.commit()

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_appr_topup:{invoice_code}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_topup:{invoice_code}")
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

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM topups WHERE topup_id = ? AND status = 'pending'", (topup_id,)) as c:
            topup = await c.fetchone()

        if topup:
            await db.execute("UPDATE topups SET status = 'approved' WHERE topup_id = ?", (topup_id,))
            await db.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (topup['amount'], topup['user_id']))
            await db.commit()
            try:
                await callback.bot.send_message(topup['user_id'], f"🎉 <b>Deposit Approved! / Депозит одобрен!</b>\n\n<code>${topup['amount']:.2f} USD</code> credited to your wallet.", parse_mode="HTML")
            except Exception:
                pass

    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n✅ <b>APPROVED BY ADMIN</b>", parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_rej_topup:"))
async def cb_admin_reject_topup(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    topup_id = callback.data.split(":")[1]

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM topups WHERE topup_id = ? AND status = 'pending'", (topup_id,)) as c:
            topup = await c.fetchone()

        if topup:
            await db.execute("UPDATE topups SET status = 'rejected' WHERE topup_id = ?", (topup_id,))
            await db.commit()
            try:
                await callback.bot.send_message(topup['user_id'], f"❌ Top-up request for <b>${topup['amount']:.2f} USD</b> rejected.", parse_mode="HTML")
            except Exception:
                pass

    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n❌ <b>REJECTED BY ADMIN</b>", parse_mode="HTML")

@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Bulk Add Account Stock", callback_data="admin_add_prod")],
        [InlineKeyboardButton(text="📤 Export Full Stock (.txt)", callback_data="admin_export_txt")],
        [InlineKeyboardButton(text="📥 Export Database (/export_db)", callback_data="admin_export_db")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="main_menu")]
    ])
    await callback.message.edit_text("👨‍💻 <b>ADMIN CONTROL PANEL</b>\n\nSelect operation mode:\n\n<i>Send a `.db` file to import DB or send a `.txt` file during upload mode to import stock.</i>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "admin_export_txt")
async def cb_admin_export_txt(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.name as country_name, c.flag, p.product_id, p.price, p.quality, p.status 
            FROM products p
            JOIN countries c ON p.country_id = c.id
            ORDER BY c.name ASC, p.quality ASC
        """) as cursor:
            products = await cursor.fetchall()

    if not products:
        await callback.answer("❌ No stock/products available to export.", show_alert=True)
        return

    output_lines = ["==========================================", "       FULL STOCK DATABASE EXPORT         ", "==========================================\n"]
    current_country = ""

    for p in products:
        if p['country_name'] != current_country:
            current_country = p['country_name']
            output_lines.append(f"\n--- {p['flag']} {current_country.upper()} ---")
        
        output_lines.append(f"ID: {p['product_id']} | Quality: {p['quality']} | Price: ${p['price']:.2f} | Status: {p['status']}")

    file_bytes = "\n".join(output_lines).encode('utf-8')
    txt_file = BufferedInputFile(file_bytes, filename="full_stock_export.txt")
    
    await callback.message.answer_document(
        document=txt_file,
        caption="📄 <b>Full Stock Export (.txt) Generated Successfully!</b>",
        parse_mode="HTML"
    )
    await callback.answer("Exported!")

@router.callback_query(F.data == "admin_export_db")
async def cb_admin_export_db(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    if os.path.exists(DATABASE_NAME):
        db_file = FSInputFile(DATABASE_NAME)
        await callback.message.answer_document(db_file, caption="📂 <b>Database Backup Exported</b>", parse_mode="HTML")
        await callback.answer("Database sent!")
    else:
        await callback.answer("❌ Database file not found.", show_alert=True)

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
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM countries WHERE is_enabled = 1") as total_cur:
            total_countries = (await total_cur.fetchone())[0]

        total_pages = max(1, (total_countries + per_page - 1) // per_page)
        offset = (page - 1) * per_page

        async with db.execute("SELECT * FROM countries WHERE is_enabled = 1 ORDER BY name ASC LIMIT ? OFFSET ?", (per_page, offset)) as cursor:
            countries = await cursor.fetchall()

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
        [InlineKeyboardButton(text="🟢 Spam-Free Account", callback_data="qual:Spam-Free Account")],
        [InlineKeyboardButton(text="🔴 Spam Account", callback_data="qual:Spam Account")]
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
        [InlineKeyboardButton(text="🛑 Finish / Exit Upload Mode", callback_data="exit_upload")]
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

    async with get_db() as db:
        for item in lines:
            prod_id = item.upper()
            try:
                await db.execute("""
                    INSERT INTO products (product_id, seller_id, type, country_id, price, quality, bin_link, status)
                    VALUES (?, ?, 'account', ?, ?, ?, '', 'available')
                    ON CONFLICT(product_id) DO UPDATE SET
                        seller_id=excluded.seller_id,
                        price=excluded.price,
                        quality=excluded.quality,
                        status='available'
                """, (prod_id, admin_id, data['country_id'], data['price'], data['quality']))
                
                added_count += 1
            except Exception as e:
                logger.error(f"Failed to add account '{item}': {e}")
                continue

        await db.commit()

    current_total = data.get('uploaded_total', 0) + added_count
    await state.update_data(uploaded_total=current_total)

    exit_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Finish / Exit Upload Mode", callback_data="exit_upload")]
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

    async with get_db() as db:
        async with db.execute("SELECT COUNT(*), SUM(amount) FROM orders WHERE user_id = ?", (user['telegram_id'],)) as c:
            row = await c.fetchone()
            total_orders = row[0] if row and row[0] is not None else 0
            total_spent = row[1] if row and row[1] is not None else 0.0

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

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.order_id, o.amount, o.created_at, 
                   COALESCE(p.quality, 'Standard Account') as quality, 
                   o.product_id
            FROM orders o 
            LEFT JOIN products p ON o.product_id = p.product_id 
            WHERE o.user_id = ? 
            ORDER BY o.created_at DESC LIMIT 5
        """, (user_id,)) as cursor:
            orders = await cursor.fetchall()

    if not orders:
        text = t["orders_empty"]
    else:
        text = t["orders_title"]
        for o in orders:
            text += (
                f"📱 <b>{t['order_item_order']}:</b> <code>{o['order_id']}</code>\n"
                f"✨ <b>{t['order_item_product']}:</b> {html.escape(o['quality'])}\n"
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

    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM products WHERE status = 'available'") as count_cur:
            total_stock = (await count_cur.fetchone())[0]

    text = t["help_text"].format(total_stock=total_stock)
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=back_home_buttons(lang)), parse_mode="HTML")

async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Bot started successfully.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution stopped.")
