from typing import Dict

BOT_TOKEN = "8863940881:AAFETiuaSBKtNDNq9NHcbnoSfGFFAVLOpwk"
ADMIN_IDS = [7952327997, 7953147643]

# MongoDB Configuration
MONGO_URI = "mongodb+srv://Gopaljichoubey:gopaljichoubey12@cluster0.qlsuf4o.mongodb.net/?appName=Cluster0"
DATABASE_NAME = "marketplace_db"

DEVELOPER_SUPPORT_LINK = "https://t.me/support"
BACKUP_CHANNEL_ID = -1004412044372

PAYMENT_METHODS: Dict[str, Dict[str, str]] = {
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

TEXTS = {
    "ru": {
        "first_time_prompt": "👋 <b>Добро пожаловать!</b>\n\nПожалуйста, выберите язык обслуживания:",
        "welcome": "✨ <b>ЦИФРОВОЙ МАРКЕТПЛЕЙС</b> ✨\n\n👤 <b>Пользователь:</b> {name}\n🆔 <b>ID:</b> <code>{user_id}</code>\n🌐 <b>Язык:</b> 🇷🇺 Русский\n💰 <b>Баланс:</b> <code>${balance:.2f}</code>\n\n<blockquote>🛒 Выберите нужный раздел в меню ниже:</blockquote>",
        "btn_buy_account": "📱 АККАУНТЫ",
        "btn_topup": "💳 ПОПОЛНИТЬ БАЛАНС",
        "btn_orders": "📦 МОИ ЗАКАЗЫ",
        "btn_profile": "👤 МОЙ ПРОФИЛЬ",
        "btn_help": "❓ ПОМОЩЬ",
        "btn_admin": "👨‍💻 АДМИН ПАНЕЛЬ",
        "btn_home": "🏠 ГЛАВНОЕ МЕНЮ",
        "btn_back": "⬅️ НАЗАД",
        "btn_support": "💬 SUPPORT",
        "select_country": "🌐 <b>ВЫБЕРИТЕ РЕГИОН / СТРАНУ</b>\nСтраница <b>{page}</b> из <b>{total_pages}</b>:\n\nВыберите страну для просмотра доступных аккаунтов:",
        "select_quality": "🌐 <b>РЕГИОН:</b> {flag} <b>{country}</b>\n\nВыберите категорию аккаунта:",
        "fresh_acc_label": "🟢 Spam-Free Аккаунт",
        "broken_acc_label": "🔴 Spam Аккаунт",
        "catalog_title": "🛍️ <b>КАТАЛОГ АККАУНТОВ</b>\n═══════════════════════\n\n",
        "out_of_stock": "❌ <b>НЕТ В НАЛИЧИИ</b>\n\nВ этой категории нет доступных аккаунтов.",
        "purchase_success": "🎉 <b>ПОКУПКА УСПЕШНА!</b>\n═══════════════════════\n\n🧾 <b>Номер заказа:</b> <code>{order_id}</code>\n🔑 <b>Ключ / Данные Аккаунта:</b> <code>{prod_id}</code>\n💵 <b>Оплачено:</b> <code>${price:.2f}</code>\n💰 <b>Новый баланс:</b> <code>${balance:.2f}</code>",
        "insufficient_funds": "❌ Недостаточно средств! Требуется: ${price:.2f}",
        "dep_title": "💳 <b>ПОПОЛНЕНИЕ БАЛАНСА КРИПТОВАЛЮТОЙ</b>\n\n💰 <b>Текущий баланс:</b> <code>${balance:.2f}</code>\n\n<blockquote>⚡ Автоматическое зачисление через блокчейн.\nМинимальное пополнение: $4.50 USD.\nВыберите платёжную сеть ниже:</blockquote>",
        "dep_select_amt": "📥 <b>Пополнение через {method}</b>\n\n💵 Выберите или введите сумму пополнения в USD:\n\n<blockquote>⚠️ Минимальный депозит: $4.50 USD</blockquote>",
        "upload_proof": "📸 <b>ОТПРАВЬТЕ ЧЕК / СКРИНШОТ</b>\n\nПожалуйста, отправьте скриншот подтверждения оплаты.",
        "proof_submitted": "✅ <b>ЧЕК ОТПРАВЛЕН</b>\n\nВаш скриншот отправлен администрации.",
        "profile_title": "👤 <b>ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ</b>\n═══════════════════════\n\n🆔 <b>Ваш ID:</b> <code>{user_id}</code>\n👤 <b>Имя:</b> {name}\n🏷️ <b>Юзернейм:</b> {username}\n🌐 <b>Язык:</b> 🇷🇺 Русский\n💰 <b>Баланс:</b> <code>${balance:.2f}</code>\n🛒 <b>Всего заказов:</b> <code>{orders}</code>\n💵 <b>Потрачено:</b> <code>${spent:.2f}</code>",
        "orders_title": "📦 <b>ВАШИ ПОСЛЕДНИЕ ЗАКАЗЫ</b>\n═══════════════════════\n\n",
        "orders_empty": "📦 <b>ИСТОРИЯ ЗАКАЗОВ</b>\n═══════════════════════\n\n<i>Заказы не найдены.</i>",
        "order_item_order": "Заказ",
        "order_item_product": "Товар",
        "order_item_key": "Данные",
        "order_item_price": "Цена",
        "help_text": "❓ <b>СПРАВОЧНЫЙ ЦЕНТР</b>\n═══════════════════════\n\n📊 <b>Всего аккаунтов в наличии:</b> <code>{total_stock}</code> шт.\n\n<blockquote>• <b>Аккаунты:</b> Выдаются моментально после оплаты прямо в чат.\n• <b>Оплата:</b> Автоматический приём популярных криптовалют.\n• <b>Поддержка:</b> По всем вопросам обращайтесь в техподдержку.</blockquote>"
    },
    "en": {
        "first_time_prompt": "👋 <b>Welcome!</b>\n\nPlease select your preferred language:",
        "welcome": "✨ <b>PREMIUM DIGITAL MARKETPLACE</b> ✨\n\n👤 <b>User:</b> {name}\n🆔 <b>ID:</b> <code>{user_id}</code>\n🌐 <b>Language:</b> 🇬🇧 English\n💰 <b>Balance:</b> <code>${balance:.2f}</code>\n\n<blockquote>🛒 Select a category from the portal below:</blockquote>",
        "btn_buy_account": "📱 ACCOUNTS",
        "btn_topup": "💳 TOP-UP WALLET",
        "btn_orders": "📦 MY ORDERS",
        "btn_profile": "👤 MY PROFILE",
        "btn_help": "❓ HELP CENTER",
        "btn_admin": "👨‍💻 ADMIN PANEL",
        "btn_home": "🏠 MAIN MENU",
        "btn_back": "⬅️ BACK",
        "btn_support": "💬 SUPPORT",
        "select_country": "🌐 <b>SELECT REGION / ORIGIN</b>\nPage <b>{page}</b> of <b>{total_pages}</b>:\n\nChoose target region to view available stock:",
        "select_quality": "🌐 <b>ORIGIN:</b> {flag} <b>{country}</b>\n\nChoose item tier:",
        "fresh_acc_label": "🟢 Spam-Free Account",
        "broken_acc_label": "🔴 Spam Account",
        "catalog_title": "🛍️ <b>ACCOUNT CATALOG</b>\n═══════════════════════\n\n",
        "out_of_stock": "❌ <b>OUT OF STOCK</b>\n\nThere are currently no accounts available in this category.",
        "purchase_success": "🎉 <b>PURCHASE SUCCESSFUL!</b>\n═══════════════════════\n\n🧾 <b>Order ID:</b> <code>{order_id}</code>\n🔑 <b>Account Details / Key:</b> <code>{prod_id}</code>\n💵 <b>Amount Paid:</b> <code>${price:.2f}</code>\n💰 <b>New Balance:</b> <code>${balance:.2f}</code>",
        "insufficient_funds": "❌ Insufficient balance! Required: ${price:.2f}",
        "dep_title": "💳 <b>CRYPTO RECHARGE PORTAL</b>\n\n💰 <b>Current Balance:</b> <code>${balance:.2f}</code>\n\n<blockquote>⚡ Automatic blockchain auto-crediting.\nMinimum deposit: $4.50 USD.\nSelect a payment network below:</blockquote>",
        "dep_select_amt": "📥 <b>Deposit via {method}</b>\n\n💵 Select or enter deposit amount in USD:\n\n<blockquote>⚠️ Minimum Deposit: $4.50 USD</blockquote>",
        "upload_proof": "📸 <b>UPLOAD PAYMENT RECEIPT</b>\n\nPlease send a clear screenshot of your transaction confirmation.",
        "proof_submitted": "✅ <b>RECEIPT SUBMITTED</b>\n\nYour transaction proof has been sent for admin verification.",
        "profile_title": "👤 <b>ACCOUNT OVERVIEW</b>\n═══════════════════════\n\n🆔 <b>Account ID:</b> <code>{user_id}</code>\n👤 <b>Name:</b> {name}\n🏷️ <b>Username:</b> {username}\n🌐 <b>Language:</b> 🇬🇧 English\n💰 <b>Wallet Balance:</b> <code>${balance:.2f}</code>\n🛒 <b>Total Orders:</b> <code>{orders}</code>\n💵 <b>Total Spent:</b> <code>${spent:.2f}</code>",
        "orders_title": "📦 <b>YOUR RECENT ORDERS</b>\n═══════════════════════\n\n",
        "orders_empty": "📦 <b>ORDER HISTORY</b>\n═══════════════════════\n\n<i>No orders found.</i>",
        "order_item_order": "Order",
        "order_item_product": "Item",
        "order_item_key": "Details",
        "order_item_price": "Price",
        "help_text": "❓ <b>SUPPORT CENTER</b>\n═══════════════════════\n\n📊 <b>Total Accounts Available:</b> <code>{total_stock}</code> units\n\n<blockquote>• <b>Accounts:</b> Delivered directly after successful purchase.\n• <b>Payments:</b> Automated crypto wallet top-ups.\n• <b>Support:</b> For assistance, tap Support button below.</blockquote>"
    }
}
