from typing import Dict

BOT_TOKEN = "8863940881:AAFETiuaSBKtNDNq9NHcbnoSfGFFAVLOpwk"
ADMIN_IDS = [7952327997]
DATABASE_NAME = "marketplace.db"
DEFAULT_BIN_CHANNEL_ID = -1004412044372
DEVELOPER_SUPPORT_LINK = "https://t.me/your_developer_username"

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
        "btn_buy_session": "⚡ СЕССИИ",
        "btn_topup": "💳 ПОПОЛНИТЬ БАЛАНС",
        "btn_orders": "📦 МОИ ЗАКАЗЫ",
        "btn_profile": "👤 МОЙ ПРОФИЛЬ",
        "btn_help": "❓ ПОМОЩЬ",
        "btn_admin": "👨‍💻 АДМИН ПАНЕЛЬ",
        "btn_home": "🏠 ГЛАВНОЕ МЕНЮ",
        "btn_back": "⬅️ НАЗАД",
        "btn_support": "💬 СВЯЗАТЬСЯ С РАЗРАБОТЧИКОМ",
        "select_country": "🌐 <b>ВЫБЕРИТЕ РЕГИОН / СТРАНУ</b>\nСтраница <b>{page}</b> из <b>{total_pages}</b>:\n\nВыберите страну для просмотра товаров:",
        "select_quality": "🌐 <b>РЕГИОН:</b> {flag} <b>{country}</b>\n\nВыберите категорию товара:",
        "fresh_acc_label": "🟢 Spam-Free Аккаунт",
        "broken_acc_label": "🔴 Spam Аккаунт",
        "fresh_sess_label": "⚡ Spam-Free Сессия",
        "broken_sess_label": "🔥 Spam Сессия",
        "catalog_title": "🛍️ <b>КАТАЛОГ ТОВАРОВ</b>\n═══════════════════════\n\n",
        "out_of_stock": "❌ <b>НЕТ В НАЛИЧИИ</b>\n\nВ этой категории нет доступных товаров.",
        "purchase_success": "🎉 <b>ПОКУПКА УСПЕШНА!</b>\n═══════════════════════\n\n🧾 <b>Номер заказа:</b> <code>{order_id}</code>\n🔑 <b>Ключ / ID Аккаунта:</b> <code>{prod_id}</code>\n💵 <b>Оплачено:</b> <code>${price:.2f}</code>\n💰 <b>Новый баланс:</b> <code>${balance:.2f}</code>",
        "purchase_success_broken": "🎉 <b>ПОКУПКА УСПЕШНА!</b>\n═══════════════════════\n\n🧾 <b>Номер заказа:</b> <code>{order_id}</code>\n✨ <b>Категория:</b> {quality}\n📂 <b>Файл сессии отправлен прямо в чат!</b>\n\n💵 <b>Оплачено:</b> <code>${price:.2f}</code>\n💰 <b>Новый баланс:</b> <code>${balance:.2f}</code>",
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
        "order_item_key": "Ключ",
        "order_item_price": "Цена",
        "order_item_link": "Ссылка",
        "help_text": "❓ <b>СПРАВОЧНЫЙ ЦЕНТР</b>\n═══════════════════════\n\n<blockquote>• <b>Аккаунты:</b> Выдаются уникальными логинами/ID.\n• <b>Сессии:</b> Выдаются файлами из канала.\n• <b>Оплата:</b> Автоматический приём криптовалют.</blockquote>\n\nПо любым вопросам или проблемам обращайтесь в поддержку:"
    },
    "en": {
        "first_time_prompt": "👋 <b>Welcome!</b>\n\nPlease select your preferred language:",
        "welcome": "✨ <b>PREMIUM DIGITAL MARKETPLACE</b> ✨\n\n👤 <b>User:</b> {name}\n🆔 <b>ID:</b> <code>{user_id}</code>\n🌐 <b>Language:</b> 🇬🇧 English\n💰 <b>Balance:</b> <code>${balance:.2f}</code>\n\n<blockquote>🛒 Select a catalog category from the portal below:</blockquote>",
        "btn_buy_account": "📱 ACCOUNTS",
        "btn_buy_session": "⚡ SESSIONS",
        "btn_topup": "💳 TOP-UP WALLET",
        "btn_orders": "📦 MY ORDERS",
        "btn_profile": "👤 MY PROFILE",
        "btn_help": "❓ HELP CENTER",
        "btn_admin": "👨‍💻 ADMIN PANEL",
        "btn_home": "🏠 MAIN MENU",
        "btn_back": "⬅️ BACK",
        "btn_support": "💬 CONTACT DEVELOPER",
        "select_country": "🌐 <b>SELECT REGION / ORIGIN</b>\nPage <b>{page}</b> of <b>{total_pages}</b>:\n\nChoose target region to view available stock:",
        "select_quality": "🌐 <b>ORIGIN:</b> {flag} <b>{country}</b>\n\nChoose item tier:",
        "fresh_acc_label": "🟢 Spam-Free Account",
        "broken_acc_label": "🔴 Spam Account",
        "fresh_sess_label": "⚡ Spam-Free Session",
        "broken_sess_label": "🔥 Spam Session",
        "catalog_title": "🛍️ <b>PRODUCT CATALOG</b>\n═══════════════════════\n\n",
        "out_of_stock": "❌ <b>OUT OF STOCK</b>\n\nThere are currently no items available in this category.",
        "purchase_success": "🎉 <b>PURCHASE SUCCESSFUL!</b>\n═══════════════════════\n\n🧾 <b>Order ID:</b> <code>{order_id}</code>\n🔑 <b>Account Key / ID:</b> <code>{prod_id}</code>\n💵 <b>Amount Paid:</b> <code>${price:.2f}</code>\n💰 <b>New Balance:</b> <code>${balance:.2f}</code>",
        "purchase_success_broken": "🎉 <b>PURCHASE SUCCESSFUL!</b>\n═══════════════════════\n\n🧾 <b>Order ID:</b> <code>{order_id}</code>\n✨ <b>Category:</b> {quality}\n📂 <b>Session file dispatched directly to chat!</b>\n\n💵 <b>Amount Paid:</b> <code>${price:.2f}</code>\n💰 <b>New Balance:</b> <code>${balance:.2f}</code>",
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
        "order_item_key": "Key",
        "order_item_price": "Price",
        "order_item_link": "Link",
        "help_text": "❓ <b>SUPPORT CENTER</b>\n═══════════════════════\n\n<blockquote>• <b>Accounts:</b> Delivered directly as individual logins/IDs.\n• <b>Sessions:</b> Delivered as direct posts/files from channel.\n• <b>Payments:</b> Automated crypto top-ups.</blockquote>\n\nFor any questions or support, contact the developer:"
    }
}
