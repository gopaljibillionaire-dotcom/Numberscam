from typing import Dict

BOT_TOKEN = "8863940881:AAFtqtpfrdcMQbHzIM8j1FJUYltVHZABF-o"
ADMIN_IDS = [7952327997, 7953147643, 8064493735, 7123919486]

# MongoDB Configuration
MONGO_URI = "mongodb+srv://Gopaljichoubey:gopaljichoubey12@cluster0.qlsuf4o.mongodb.net/?appName=Cluster0"
DATABASE_NAME = "marketplace_db"

DEVELOPER_SUPPORT_LINK = "https://t.me/Tgdtax"
BACKUP_CHANNEL_ID = -1004412044372

PAYMENT_METHODS: Dict[str, Dict[str, str]] = {
    "usdt_bep20": {
        "name": "USDT (BEP-20)",
        "ticker": "USDT",
        "coingecko_id": "tether",
        "address": "0x4671baa1F70594B06A0A34125E7e014874887a9E",
        "memo": "",
    },
    "usdt_erc20": {
        "name": "USDT (ERC-20)",
        "ticker": "USDT",
        "coingecko_id": "tether",
        "address": "0x4671baa1F70594B06A0A34125E7e014874887a9E",
        "memo": "",
    },
    "usdt_poly": {
        "name": "USDT (Polygon)",
        "ticker": "USDT",
        "coingecko_id": "tether",
        "address": "0x4671baa1F70594B06A0A34125E7e014874887a9E",
        "memo": "",
    },
    "usdt_trc20": {
        "name": "USDT (TRC-20)",
        "ticker": "USDT",
        "coingecko_id": "tether",
        "address": "TGPgYX3xAKDUFsS51GFY7dcw76fgTX1V24",
        "memo": "",
    },
    "usdt_sol": {
        "name": "USDT (Solana)",
        "ticker": "USDT",
        "coingecko_id": "tether",
        "address": "HFm9352iJYx75JJsrp9TZg5WRoqWhwwriAdoQedtxxqi",
        "memo": "",
    },
    "usdt_ton": {
        "name": "USDT (TON)",
        "ticker": "USDT",
        "coingecko_id": "tether",
        "address": "EQAj7vKLbaWjaNbAuAKP1e1HwmdYZ2vJ2xtWU8qq3JafkfxF",
        "memo": "1482623",
    },
}

FALLBACK_PRICES = {"tether": 1.0}

TEXTS = {
    "ru": {
        "first_time_prompt": "👋 <b>Добро пожаловать в Премиум Маркетплейс!</b>\n\n<blockquote>Пожалуйста, выберите язык обслуживания:</blockquote>",
        "welcome": (
            "💎 ═══════════════════════ 💎\n"
            "   ✨ <b>ПРЕМИУМ ЦИФРОВОЙ МАРКЕТПЛЕЙС</b> ✨\n"
            "💎 ═══════════════════════ 💎\n\n"
            "👤 <b>Пользователь:</b> {name}\n"
            "🆔 <b>ID:</b> <code>{user_id}</code>\n"
            "🌐 <b>Язык:</b> 🇷🇺 Русский\n"
            "💰 <b>Баланс:</b> <code>${balance:.2f} USD</code>\n\n"
            "<blockquote>🛒 Выберите нужный раздел в меню ниже для совершения покупок:</blockquote>"
        ),
        "btn_buy_account": "🛍️ КАТАЛОГ АККАУНТОВ",
        "btn_topup": "💳 ПОПОЛНИТЬ БАЛАНС",
        "btn_orders": "📦 МОИ ЗАКАЗЫ",
        "btn_profile": "👤 МОЙ ПРОФИЛЬ",
        "btn_help": "❓ ПОМОЩЬ & ИНФО",
        "btn_admin": "⚡ АДМИН ПАНЕЛЬ",
        "btn_home": "🏠 ГЛАВНОЕ МЕНЮ",
        "btn_back": "⬅️ НАЗАД",
        "btn_support": "💬 ТЕХПОДДЕРЖКА (@Tgdtax)",
        "select_country": (
            "🌐 <b>ВЫБОР СТРАНЫ ИЛИ РЕГИОНА</b>\n"
            "📄 Страница <b>{page}</b> из <b>{total_pages}</b>\n"
            "═══════════════════════\n\n"
            "<blockquote>Выберите интересующую вас страну для просмотра наличия:</blockquote>"
        ),
        "select_quality": (
            "🌐 <b>РЕГИОН:</b> {flag} <b>{country}</b>\n"
            "═══════════════════════\n\n"
            "<blockquote>Выберите желаемый тип и качество аккаунта:</blockquote>"
        ),
        "fresh_acc_label": "🟢 Spam-Free (Чистый)",
        "broken_acc_label": "🔴 Spam (С ограничениями)",
        "catalog_title": "🛍️ <b>КАТАЛОГ АККАУНТОВ</b>\n═══════════════════════\n\n",
        "out_of_stock": "❌ <b>НЕТ В НАЛИЧИИ</b>\n\nК сожалению, в данной категории сейчас нет доступных товаров.",
        "purchase_success": (
            "🎉 <b>ПОКУПКА УСПЕШНО СОВЕРШЕНА!</b>\n"
            "═══════════════════════\n\n"
            "🧾 <b>Номер заказа:</b> <code>{order_id}</code>\n"
            "🔑 <b>Данные аккаунта:</b> <code>{prod_id}</code>\n"
            "💵 <b>Списано:</b> <code>${price:.2f} USD</code>\n"
            "💰 <b>Остаток на балансе:</b> <code>${balance:.2f} USD</code>\n\n"
            "<blockquote>Спасибо за покупку! По любым вопросам пишите в поддержку.</blockquote>"
        ),
        "insufficient_funds": "❌ Недостаточно средств на балансе! Требуется: ${price:.2f} USD",
        "dep_title": (
            "💳 <b>КРИПТО ПОПОЛНЕНИЕ БАЛАНСА</b>\n"
            "═══════════════════════\n\n"
            "💰 <b>Ваш текущий баланс:</b> <code>${balance:.2f} USD</code>\n\n"
            "<blockquote>⚡ Автоматическая обработка платежей через блокчейн.\n"
            "⚠️ Минимальное пополнение: <b>$4.50 USD</b>.\n\n"
            "Выберите удобную платёжную сеть ниже:</blockquote>"
        ),
        "dep_select_amt": (
            "📥 <b>Пополнение через {method}</b>\n"
            "═══════════════════════\n\n"
            "💵 Выберите готовую сумму или введите свою:\n\n"
            "<blockquote>⚠️ Минимальный депозит: $4.50 USD</blockquote>"
        ),
        "upload_proof": (
            "📸 <b>ОТПРАВКА ЧЕКА ОБ ОПЛАТЕ</b>\n"
            "═══════════════════════\n\n"
            "Пожалуйста, отправьте скриншот или фото подтверждения перевода в этот чат."
        ),
        "proof_submitted": (
            "✅ <b>ЧЕК УСПЕШНО ОТПРАВЛЕН!</b>\n"
            "═══════════════════════\n\n"
            "Ваш запрос передан администраторам. Баланс будет зачислен сразу после проверки."
        ),
        "profile_title": (
            "👤 <b>ЛИЧНЫЙ КАБИНЕТ ПОЛЬЗОВАТЕЛЯ</b>\n"
            "═══════════════════════\n\n"
            "🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
            "👤 <b>Имя:</b> {name}\n"
            "🏷️ <b>Юзернейм:</b> {username}\n"
            "🌐 <b>Язык сервиса:</b> 🇷🇺 Русский\n"
            "💰 <b>Баланс:</b> <code>${balance:.2f} USD</code>\n"
            "🛒 <b>Куплено товаров:</b> <code>{orders} шт.</code>\n"
            "💵 <b>Всего потрачено:</b> <code>${spent:.2f} USD</code>"
        ),
        "orders_title": "📦 <b>ИСТОРИЯ ПОСЛЕДНИХ ЗАКАЗОВ</b>\n═══════════════════════\n\n",
        "orders_empty": (
            "📦 <b>ИСТОРИЯ ЗАКАЗОВ</b>\n"
            "═══════════════════════\n\n"
            "<i>У вас пока нет совершённых покупок.</i>"
        ),
        "order_item_order": "Заказ",
        "order_item_product": "Категория",
        "order_item_key": "Данные",
        "order_item_price": "Стоимость",
        "help_text": (
            "❓ <b>СПРАВОЧНЫЙ ЦЕНТР И ПОДДЕРЖКА</b>\n"
            "═══════════════════════\n\n"
            "📊 <b>Доступно товаров в боте:</b> <code>{total_stock}</code> шт.\n\n"
            "<blockquote>• <b>Выдача товара:</b> Моментально после оплаты в этот чат.\n"
            "• <b>Пополнение:</b> Автоматическая обработка криптодепозитов.\n"
            "• <b>Поддержка:</b> По всем вопросам обращайтесь к @Tgdtax.</blockquote>"
        )
    },
    "en": {
        "first_time_prompt": "👋 <b>Welcome to Premium Digital Marketplace!</b>\n\n<blockquote>Please select your preferred language:</blockquote>",
        "welcome": (
            "💎 ═══════════════════════ 💎\n"
            "   ✨ <b>PREMIUM DIGITAL MARKETPLACE</b> ✨\n"
            "💎 ═══════════════════════ 💎\n\n"
            "👤 <b>User:</b> {name}\n"
            "🆔 <b>ID:</b> <code>{user_id}</code>\n"
            "🌐 <b>Language:</b> 🇬🇧 English\n"
            "💰 <b>Balance:</b> <code>${balance:.2f} USD</code>\n\n"
            "<blockquote>🛒 Select a category from the options below to start shopping:</blockquote>"
        ),
        "btn_buy_account": "🛍️ ACCOUNT CATALOG",
        "btn_topup": "💳 TOP-UP BALANCE",
        "btn_orders": "📦 MY ORDERS",
        "btn_profile": "👤 MY PROFILE",
        "btn_help": "❓ HELP & INFO",
        "btn_admin": "⚡ ADMIN PANEL",
        "btn_home": "🏠 MAIN MENU",
        "btn_back": "⬅️ BACK",
        "btn_support": "💬 SUPPORT (@Tgdtax)",
        "select_country": (
            "🌐 <b>SELECT REGION OR ORIGIN</b>\n"
            "📄 Page <b>{page}</b> of <b>{total_pages}</b>\n"
            "═══════════════════════\n\n"
            "<blockquote>Choose a target region to view available stock:</blockquote>"
        ),
        "select_quality": (
            "🌐 <b>REGION:</b> {flag} <b>{country}</b>\n"
            "═══════════════════════\n\n"
            "<blockquote>Choose preferred item quality tier:</blockquote>"
        ),
        "fresh_acc_label": "🟢 Spam-Free Account",
        "broken_acc_label": "🔴 Spam Account",
        "catalog_title": "🛍️ <b>ACCOUNT CATALOG</b>\n═══════════════════════\n\n",
        "out_of_stock": "❌ <b>OUT OF STOCK</b>\n\nThere are currently no accounts available in this category.",
        "purchase_success": (
            "🎉 <b>PURCHASE SUCCESSFUL!</b>\n"
            "═══════════════════════\n\n"
            "🧾 <b>Order ID:</b> <code>{order_id}</code>\n"
            "🔑 <b>Account Data / Key:</b> <code>{prod_id}</code>\n"
            "💵 <b>Amount Paid:</b> <code>${price:.2f} USD</code>\n"
            "💰 <b>New Balance:</b> <code>${balance:.2f} USD</code>\n\n"
            "<blockquote>Thank you for your order! Contact support if you need help.</blockquote>"
        ),
        "insufficient_funds": "❌ Insufficient balance! Required: ${price:.2f} USD",
        "dep_title": (
            "💳 <b>CRYPTO RECHARGE PORTAL</b>\n"
            "═══════════════════════\n\n"
            "💰 <b>Current Balance:</b> <code>${balance:.2f} USD</code>\n\n"
            "<blockquote>⚡ Automated blockchain invoice processing.\n"
            "⚠️ Minimum deposit amount: <b>$4.50 USD</b>.\n\n"
            "Select a payment network below:</blockquote>"
        ),
        "dep_select_amt": (
            "📥 <b>Deposit via {method}</b>\n"
            "═══════════════════════\n\n"
            "💵 Select preset amount or enter a custom value:\n\n"
            "<blockquote>⚠️ Minimum Deposit: $4.50 USD</blockquote>"
        ),
        "upload_proof": (
            "📸 <b>UPLOAD PAYMENT RECEIPT</b>\n"
            "═══════════════════════\n\n"
            "Please send a clear screenshot of your transaction confirmation."
        ),
        "proof_submitted": (
            "✅ <b>RECEIPT SUBMITTED!</b>\n"
            "═══════════════════════\n\n"
            "Your payment proof has been submitted for admin verification."
        ),
        "profile_title": (
            "👤 <b>ACCOUNT OVERVIEW</b>\n"
            "═══════════════════════\n\n"
            "🆔 <b>Account ID:</b> <code>{user_id}</code>\n"
            "👤 <b>Name:</b> {name}\n"
            "🏷️ <b>Username:</b> {username}\n"
            "🌐 <b>Language:</b> 🇬🇧 English\n"
            "💰 <b>Wallet Balance:</b> <code>${balance:.2f} USD</code>\n"
            "🛒 <b>Total Purchased:</b> <code>{orders} items</code>\n"
            "💵 <b>Total Spent:</b> <code>${spent:.2f} USD</code>"
        ),
        "orders_title": "📦 <b>YOUR RECENT ORDERS</b>\n═══════════════════════\n\n",
        "orders_empty": (
            "📦 <b>ORDER HISTORY</b>\n"
            "═══════════════════════\n\n"
            "<i>No order history found.</i>"
        ),
        "order_item_order": "Order",
        "order_item_product": "Category",
        "order_item_key": "Data",
        "order_item_price": "Price",
        "help_text": (
            "❓ <b>SUPPORT CENTER & INFO</b>\n"
            "═══════════════════════\n\n"
            "📊 <b>Total Accounts Available:</b> <code>{total_stock}</code> units\n\n"
            "<blockquote>• <b>Delivery:</b> Instant delivery directly in chat upon purchase.\n"
            "• <b>Payments:</b> Automated crypto wallet deposits.\n"
            "• <b>Support:</b> Contact @Tgdtax for instant customer assistance.</blockquote>"
        )
    }
}
