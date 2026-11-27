import os
import telebot
from telebot import types
from pymongo import MongoClient

# ================= কনফিগারেশন =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9296413073:AAESYLilx-qnqvX8TJjn0XUZzXfnaIneARI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6080994435"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://freefirenewid8282_db_user:8wrQe9mh3xVdKux2@telegram.w4wlbz1.mongodb.net")
REFERRAL_COINS = 5

# বাধ্যতামূলক চ্যানেল লিস্ট (এখানে আপনার চ্যানেলের @username বা -100... Chat ID দিন)
# উদাহরণ: ["@mychannel1", -1001234567890]
REQUIRED_CHANNELS = [
    # "@your_channel_username",
]
# ================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
client = MongoClient(MONGO_URI)
db = client["telegram_verify_shop_db"]

users_col = db["users"]
products_col = db["products"]
channels_col = db["channels"]

# অ্যাডমিন স্টেট ট্র্যাক করার জন্য (প্রোডাক্ট যোগ করার ধাপ)
admin_states = {}


def get_channels():
    """ডাটাবেজ এবং কনফিগ থেকে সব বাধ্যতামূলক চ্যানেলের লিস্ট রিটার্ন করে"""
    ch_list = list(REQUIRED_CHANNELS)
    for doc in channels_col.find({}):
        ch = doc.get("chat_id")
        if ch and ch not in ch_list:
            ch_list.append(ch)
    return ch_list


def format_channel_link(ch):
    ch_str = str(ch).strip()
    if ch_str.startswith("@"):
        return f"https://t.me/{ch_str[1:]}"
    return ch_str


def is_user_joined_all(user_id):
    """ইউজার সব চ্যানেলে জয়েন করেছে কি না তা চেক করে"""
    channels = get_channels()
    if not channels:
        return True, []

    not_joined = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)

    return len(not_joined) == 0, not_joined


def ensure_user(user, referrer_id=None):
    """ডাটাবেজে ইউজার রেকর্ড তৈরি বা আপডেট করে এবং নতুন ইউজার কি না জানায়"""
    existing = users_col.find_one({"user_id": user.id})
    if existing:
        return existing, False

    valid_ref = None
    if referrer_id and referrer_id != user.id:
        ref_user = users_col.find_one({"user_id": referrer_id})
        if ref_user:
            valid_ref = referrer_id

    doc = {
        "user_id": user.id,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "coins": 0,
        "referred_by": valid_ref,
        "referral_rewarded": False,
        "verified": False,
    }
    users_col.insert_one(doc)
    return doc, True


def reward_referrer_if_eligible(user_id):
    """ভেরিফাই হলে রেফারকারীকে ৫ কয়েন দেয় (শুধু একবার)"""
    user_doc = users_col.find_one({"user_id": user_id})
    if not user_doc:
        return

    ref_id = user_doc.get("referred_by")
    already_rewarded = user_doc.get("referral_rewarded", False)

    if ref_id and not already_rewarded:
        users_col.update_one(
            {"user_id": ref_id},
            {"$inc": {"coins": REFERRAL_COINS}}
        )
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"referral_rewarded": True}}
        )
        try:
            bot.send_message(
                ref_id,
                f"🎉 <b>নতুন রেফারেল সফল!</b>\nআপনি <b>+{REFERRAL_COINS} কয়েন</b> পেয়েছেন।"
            )
        except Exception:
            pass


def send_force_join_message(chat_id, user_id):
    channels = get_channels()
    markup = types.InlineKeyboardMarkup(row_width=1)

    for idx, ch in enumerate(channels, start=1):
        ch_str = str(ch).strip()
        if ch_str.startswith("@"):
            url = f"https://t.me/{ch_str[1:]}"
            markup.add(types.InlineKeyboardButton(f"📢 Join Channel {idx} ({ch_str})", url=url))
        else:
            markup.add(types.InlineKeyboardButton(f"📢 Channel {idx}: {ch_str}", callback_data="noop"))

    markup.add(types.InlineKeyboardButton("✅ Verify", callback_data="verify_join"))

    text = (
        "🔒 <b>বট ব্যবহার করতে হলে আগে চ্যানেলগুলোতে জয়েন করুন</b>\n\n"
        "নিচের চ্যানেলগুলোতে জয়েন করার পর <b>Verify</b> বাটনে চাপ দিন।\n"
        "জয়েন না করলে ভেরিফাই হবে না।"
    )
    bot.send_message(chat_id, text, reply_markup=markup)


def send_main_menu(chat_id, user_id):
    user_doc = users_col.find_one({"user_id": user_id}) or {}
    coins = user_doc.get("coins", 0)
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🛍️ Products", "🪙 My Coins & Referral")
    if user_id == ADMIN_ID:
        markup.row("➕ Add Product", "📢 Add Channel")
        markup.row("📋 List Products", "📊 Stats")

    text = (
        f"✅ <b>ভেরিফিকেশন সফল!</b>\n"
        f"🪙 আপনার বর্তমান ব্যালেন্স: <b>{coins} কয়েন</b>\n\n"
        f"🔗 আপনার রেফারেল লিংক:\n<code>{ref_link}</code>\n"
        f"প্রতি সফল রেফারে পাবেন <b>{REFERRAL_COINS} কয়েন</b>।"
    )
    bot.send_message(chat_id, text, reply_markup=markup)


def send_products_list(chat_id, user_id):
    products = list(products_col.find({}))
    if not products:
        bot.send_message(chat_id, "📦 বর্তমানে কোনো প্রোডাক্ট যুক্ত করা হয়নি।")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for p in products:
        cost = p.get("cost", 0)
        cost_label = "Free" if cost <= 0 else f"{cost} Coins"
        btn_text = f"📦 {p['title']} ({cost_label})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"get_prod_{str(p['_id'])}"))

    bot.send_message(chat_id, "🛍️ <b>প্রোডাক্ট লিস্ট</b> — যেকোনো প্রোডাক্টে চাপ দিন:", reply_markup=markup)


@bot.message_handler(commands=["start"])
def handle_start(message):
    parts = message.text.split()
    ref_id = None
    if len(parts) > 1 and parts[1].isdigit():
        ref_id = int(parts[1])

    ensure_user(message.from_user, referrer_id=ref_id)

    joined, _ = is_user_joined_all(message.from_user.id)
    if not joined:
        send_force_join_message(message.chat.id, message.from_user.id)
        return

    users_col.update_one({"user_id": message.from_user.id}, {"$set": {"verified": True}})
    reward_referrer_if_eligible(message.from_user.id)
    send_main_menu(message.chat.id, message.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data == "verify_join")
def handle_verify_join(call):
    user_id = call.from_user.id
    ensure_user(call.from_user)

    joined, missing = is_user_joined_all(user_id)
    if not joined:
        bot.answer_callback_query(call.id, "❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)
        send_force_join_message(call.message.chat.id, user_id)
        return

    users_col.update_one({"user_id": user_id}, {"$set": {"verified": True}})
    reward_referrer_if_eligible(user_id)
    bot.answer_callback_query(call.id, "✅ ভেরিফাই সম্পন্ন হয়েছে!")
    send_main_menu(call.message.chat.id, user_id)


@bot.callback_query_handler(func=lambda call: call.data == "noop")
def handle_noop(call):
    bot.answer_callback_query(call.id, "চ্যানেল ID কপি করে টেলিগ্রামে সার্চ করুন বা জয়েন করুন।")


@bot.message_handler(func=lambda m: m.text == "🛍️ Products")
def menu_products(message):
    joined, _ = is_user_joined_all(message.from_user.id)
    if not joined:
        send_force_join_message(message.chat.id, message.from_user.id)
        return
    send_products_list(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "🪙 My Coins & Referral")
def menu_coins_ref(message):
    joined, _ = is_user_joined_all(message.from_user.id)
    if not joined:
        send_force_join_message(message.chat.id, message.from_user.id)
        return

    user_doc, _ = ensure_user(message.from_user)
    coins = user_doc.get("coins", 0)
    ref_count = users_col.count_documents({"referred_by": message.from_user.id, "referral_rewarded": True})
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={message.from_user.id}"

    text = (
        f"🪙 <b>আপনার ব্যালেন্স:</b> {coins} কয়েন\n"
        f"👥 <b>সফল রেফারেল:</b> {ref_count} জন\n"
        f"🎁 <b>প্রতি রেফারে:</b> {REFERRAL_COINS} কয়েন\n\n"
        f"🔗 <b>আপনার রেফারেল লিংক:</b>\n<code>{ref_link}</code>"
    )
    bot.send_message(message.chat.id, text)


@bot.callback_query_handler(func=lambda call: call.data.startswith("get_prod_"))
def handle_get_product(call):
    from bson import ObjectId

    user_id = call.from_user.id
    joined, _ = is_user_joined_all(user_id)
    if not joined:
        bot.answer_callback_query(call.id, "❌ আগে চ্যানেলগুলোতে জয়েন করুন!", show_alert=True)
        send_force_join_message(call.message.chat.id, user_id)
        return

    prod_id_str = call.data.replace("get_prod_", "")
    try:
        prod = products_col.find_one({"_id": ObjectId(prod_id_str)})
    except Exception:
        prod = None

    if not prod:
        bot.answer_callback_query(call.id, "প্রোডাক্টটি পাওয়া যায়নি।", show_alert=True)
        return

    cost = int(prod.get("cost", 0))
    user_doc, _ = ensure_user(call.from_user)
    current_coins = int(user_doc.get("coins", 0))

    if cost > 0 and current_coins < cost:
        bot.answer_callback_query(
            call.id,
            f"❌ এই প্রোডাক্টের জন্য {cost} কয়েন দরকার। আপনার আছে {current_coins} কয়েন।",
            show_alert=True
        )
        return

    if cost > 0:
        users_col.update_one({"user_id": user_id}, {"$inc": {"coins": -cost}})

    bot.answer_callback_query(call.id, "✅ প্রোডাক্ট পাঠানো হচ্ছে...")

    caption = f"📦 <b>{prod['title']}</b>\n\n{prod.get('description', '')}"
    p_type = prod.get("type", "text")
    payload = prod.get("payload", "")

    if p_type == "document" and payload:
        bot.send_document(call.message.chat.id, payload, caption=caption)
    elif p_type == "photo" and payload:
        bot.send_photo(call.message.chat.id, payload, caption=caption)
    else:
        bot.send_message(call.message.chat.id, f"{caption}\n\n{payload}".strip())


# ================= অ্যাডমিন কমান্ড ও বাটন =================
@bot.message_handler(func=lambda m: m.text == "📢 Add Channel" and m.from_user.id == ADMIN_ID)
def admin_add_channel_prompt(message):
    admin_states[message.from_user.id] = {"step": "waiting_channel"}
    bot.send_message(
        message.chat.id,
        "📢 চ্যানেলের <b>@username</b> (যেমন <code>@mychannel</code>) অথবা <b>Chat ID</b> (যেমন <code>-1001234567890</code>) পাঠান:\n"
        "(বাতিল করতে /cancel লিখুন)"
    )


@bot.message_handler(func=lambda m: m.text == "➕ Add Product" and m.from_user.id == ADMIN_ID)
def admin_add_product_start(message):
    admin_states[message.from_user.id] = {"step": "prod_title", "data": {}}
    bot.send_message(message.chat.id, "📦 নতুন প্রোডাক্টের <b>নাম</b> লিখুন:")


@bot.message_handler(func=lambda m: m.text == "📋 List Products" and m.from_user.id == ADMIN_ID)
def admin_list_products(message):
    products = list(products_col.find({}))
    if not products:
        bot.send_message(message.chat.id, "কোনো প্রোডাক্ট নেই।")
        return
    lines = ["📋 <b>সব প্রোডাক্ট:</b>"]
    for idx, p in enumerate(products, start=1):
        lines.append(f"{idx}. <b>{p['title']}</b> — Cost: {p.get('cost', 0)} coins (Type: {p.get('type', 'text')})")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda m: m.text == "📊 Stats" and m.from_user.id == ADMIN_ID)
def admin_stats(message):
    total_users = users_col.count_documents({})
    verified_users = users_col.count_documents({"verified": True})
    total_products = products_col.count_documents({})
    channels = get_channels()
    bot.send_message(
        message.chat.id,
        f"📊 <b>বট পরিসংখ্যান</b>\n\n"
        f"👥 মোট ইউজার: <b>{total_users}</b>\n"
        f"✅ ভেরিফাইড ইউজার: <b>{verified_users}</b>\n"
        f"📦 মোট প্রোডাক্ট: <b>{total_products}</b>\n"
        f"📢 বাধ্যতামূলক চ্যানেল: <b>{len(channels)}</b>"
    )


@bot.message_handler(commands=["cancel"])
def cancel_state(message):
    admin_states.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "❌ অপারেশন বাতিল করা হয়েছে।")


@bot.message_handler(content_types=["text", "document", "photo"], func=lambda m: m.from_user.id == ADMIN_ID and m.from_user.id in admin_states)
def admin_state_flow(message):
    state = admin_states[message.from_user.id]
    step = state.get("step")

    if step == "waiting_channel" and message.text:
        ch_val = message.text.strip()
        if not ch_val.startswith("@"):
            try:
                ch_val = int(ch_val)
            except ValueError:
                pass
        channels_col.update_one({"chat_id": ch_val}, {"$set": {"chat_id": ch_val}}, upsert=True)
        admin_states.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, f"✅ চ্যানেল যুক্ত হয়েছে: <code>{ch_val}</code>\nমনে রাখবেন, চ্যানেলে বটকে Admin করতে হবে।")
        return

    data = state.get("data", {})

    if step == "prod_title" and message.text:
        data["title"] = message.text.strip()
        state["step"] = "prod_desc"
        bot.send_message(message.chat.id, "📝 প্রোডাক্টের <b>বিবরণ</b> লিখুন (না থাকলে <code>-</code> লিখুন):")

    elif step == "prod_desc" and message.text:
        desc = "" if message.text.strip() == "-" else message.text.strip()
        data["description"] = desc
        state["step"] = "prod_cost"
        bot.send_message(message.chat.id, "🪙 প্রোডাক্ট নিতে কত <b>কয়েন</b> লাগবে? (ফ্রি হলে <code>0</code> লিখুন):")

    elif step == "prod_cost" and message.text:
        try:
            cost = max(0, int(message.text.strip()))
        except ValueError:
            bot.send_message(message.chat.id, "❌ দয়া করে সঠিক সংখ্যা লিখুন (যেমন <code>0</code> বা <code>5</code>):")
            return
        data["cost"] = cost
        state["step"] = "prod_payload"
        bot.send_message(
            message.chat.id,
            "📎 এবার প্রোডাক্টের <b>ফাইল (Document/Photo)</b> পাঠান অথবা <b>টেক্সট/লিংক</b> লিখে পাঠান:"
        )

    elif step == "prod_payload":
        if message.content_type == "document":
            data["type"] = "document"
            data["payload"] = message.document.file_id
        elif message.content_type == "photo":
            data["type"] = "photo"
            data["payload"] = message.photo[-1].file_id
        elif message.text:
            data["type"] = "text"
            data["payload"] = message.text.strip()
        else:
            bot.send_message(message.chat.id, "❌ অনুগ্রহ করে একটি ফাইল, ছবি বা টেক্সট/লিংক পাঠান।")
            return

        products_col.insert_one(data)
        admin_states.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, f"✅ প্রোডাক্ট <b>{data['title']}</b> সফলভাবে যুক্ত হয়েছে!")


if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True)
