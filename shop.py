"""Telegram do'kon boti: kanalga mahsulot joylash + buyurtma + to'lov + yetkazib berish (EMU Post)."""
import os, json, time, html, requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = os.environ.get("CHANNEL_ID") or "@Online_magazin12jam"
ADMIN = str(os.environ.get("ADMIN_CHAT_ID") or "")
DISCOUNT = float(os.environ.get("DISCOUNT_PERCENT") or 20)
DELIVERY_FEE = int(os.environ.get("DELIVERY_FEE") or 25000)
PAY_INFO = os.environ.get("PAY_INFO") or "Реквизиты для оплаты будут отправлены администратором."
UZUM_KEY = (os.environ.get("UZUM_API_KEY") or "").strip()
UZUM = "https://api-seller.uzum.uz/api/seller-openapi"
RUN_SECONDS = int(os.environ.get("RUN_SECONDS") or 55 * 60)
TG = f"https://api.telegram.org/bot{TOKEN}/"
STATE = "state.json"

def load():
    try:
        s = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        s = {}
    s.setdefault("offset", 0); s.setdefault("products", {}); s.setdefault("orders", {})
    s.setdefault("sessions", {}); s.setdefault("drafts", {}); s.setdefault("albums", {})
    s.setdefault("next_product", 1); s.setdefault("next_order", 1)
    return s

def save(s):
    json.dump(s, open(STATE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(STATE + ".tmp", STATE)

def tg(method, **data):
    try:
        r = requests.post(TG + method, json=data, timeout=40)
        j = r.json()
        if not j.get("ok"):
            print("TG", method, j)
        return j
    except Exception as e:
        print("TG ERROR", method, e)
        return {"ok": False}

def money(n):
    return f"{int(n):,}".replace(",", " ") + " сум"

def shop_price(uzum):
    return int(round(uzum * (1 - DISCOUNT / 100) / 1000.0)) * 1000

def esc(t):
    return html.escape(str(t))

def me(s):
    if "me" not in s:
        s["me"] = tg("getMe").get("result", {}).get("username", "")
    return s["me"]

def product_caption(p):
    t = f"<b>{esc(p['title'])}</b>\n"
    if p.get("desc"):
        t += f"\n{esc(p['desc'])}\n"
    t += f"\n💰 Цена: <b>{money(p['price'])}</b>\n🚚 Доставка EMU Post — платная"
    return t

# ---------- admin: новая карточка ----------
def parse_caption(cap):
    parts = [x.strip() for x in (cap or "").split("|")]
    if len(parts) < 2:
        return None
    digits = "".join(c for c in parts[1] if c.isdigit())
    if not digits:
        return None
    return {"title": parts[0], "uzum": int(digits), "desc": parts[2] if len(parts) > 2 else ""}

def admin_photo(s, msg):
    gid = msg.get("media_group_id")
    fid = msg["photo"][-1]["file_id"]
    cap = msg.get("caption")
    if gid:
        a = s["albums"].setdefault(gid, {"photos": [], "caption": None, "t": time.time()})
        a["photos"].append(fid)
        if cap:
            a["caption"] = cap
        return  # финализируем позже в flush_albums
    make_draft(s, [fid], cap)

def flush_albums(s):
    for gid, a in list(s["albums"].items()):
        if time.time() - a["t"] > 4:
            del s["albums"][gid]
            make_draft(s, a["photos"], a["caption"])

def make_draft(s, photos, cap):
    d = parse_caption(cap)
    if not d:
        tg("sendMessage", chat_id=ADMIN, text="Подпись должна быть такой:\n<code>Название | цена на Uzum | краткое описание</code>\nНапример: <code>Худи мужское | 250000 | Хлопок, размеры S–XL</code>", parse_mode="HTML")
        return
    d["price"] = shop_price(d["uzum"]); d["photos"] = photos
    did = str(int(time.time()))
    s["drafts"][did] = d
    tg("sendPhoto", chat_id=ADMIN, photo=photos[0], parse_mode="HTML",
       caption=product_caption(d) + f"\n\n(на Uzum: {money(d['uzum'])}, фото: {len(photos)})",
       reply_markup={"inline_keyboard": [[{"text": "✅ Опубликовать", "callback_data": f"pub:{did}"},
                                          {"text": "❌ Отмена", "callback_data": f"del:{did}"}]]})

def publish(s, did):
    d = s["drafts"].pop(did, None)
    if not d:
        return "Уже обработано"
    if d.get("uzum_id"):
        s.setdefault("uzum_done", []).append(d["uzum_id"])
    pid = str(s["next_product"]); s["next_product"] += 1
    s["products"][pid] = d
    kb = {"inline_keyboard": [[{"text": "🛒 Заказать", "url": f"https://t.me/{me(s)}?start=p{pid}"}]]}
    cap = product_caption(d)
    if len(d["photos"]) == 1:
        tg("sendPhoto", chat_id=CHANNEL, photo=d["photos"][0], caption=cap, parse_mode="HTML", reply_markup=kb)
    else:
        media = [{"type": "photo", "media": f} for f in d["photos"][:10]]
        media[0]["caption"] = cap; media[0]["parse_mode"] = "HTML"
        tg("sendMediaGroup", chat_id=CHANNEL, media=media)
        tg("sendMessage", chat_id=CHANNEL, text=f"👆 {esc(d['title'])}", parse_mode="HTML", reply_markup=kb)
    return "Опубликовано в канале"


# ---------- Uzum: загрузка своих карточек ----------
def uzum_get(path, **params):
    r = requests.get(UZUM + path, headers={"Authorization": UZUM_KEY}, params=params, timeout=40)
    r.raise_for_status()
    return r.json()

def uzum_img(x):
    if not x:
        return None
    return x if x.startswith("http") else f"https://images.uzum.uz/{x}/original.jpg"

def uzum_products():
    """Все товары всех магазинов продавца, в наличии."""
    out = []
    for sh in uzum_get("/v1/shops"):
        page = 0
        while page < 40:
            j = uzum_get(f"/v1/product/shop/{sh['id']}", searchQuery="", filter="ALL", sortBy="DEFAULT", order="ASC", size=20, page=page)
            lst = j.get("productList") or []
            for pr in lst:
                skus = [k for k in pr.get("skuList", []) if (k.get("quantityAvailable") or 0) > 0 and not k.get("archived") and not k.get("blocked")]
                if not skus:
                    continue
                price = min((k.get("price") or 0) for k in skus) or pr.get("price") or 0
                opts = []
                for k in skus:
                    c = (k.get("characteristics") or k.get("skuTitle") or "").strip()
                    if c and c not in opts:
                        opts.append(c)
                img = uzum_img(pr.get("previewImg") or pr.get("image") or (skus[0].get("previewImage")))
                if price and img:
                    out.append({"id": str(pr["productId"]), "title": pr.get("title") or skus[0].get("productTitle"), "uzum": int(price),
                                "photo": img, "opts": opts[:12]})
            if len(lst) < 20:
                break
            page += 1
    return out

def uzum_offer(s, chat):
    if not UZUM_KEY:
        tg("sendMessage", chat_id=chat, text="Ключ Uzum не подключён (секрет UZUM_API_KEY).")
        return
    try:
        items = uzum_products()
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", "")
        tg("sendMessage", chat_id=chat, text=f"Ошибка Uzum API: {type(e).__name__} {code}")
        print("UZUM ERR", repr(e)[:300])
        return
    done = set(s.setdefault("uzum_done", []))
    new = [i for i in items if i["id"] not in done]
    tg("sendMessage", chat_id=chat, text=f"Товаров в наличии на Uzum: {len(items)}, ещё не в канале: {len(new)}. Показываю до 10.")
    for i in new[:10]:
        d = {"title": i["title"], "uzum": i["uzum"], "price": shop_price(i["uzum"]), "photos": [i["photo"]],
             "desc": ("Варианты: " + "; ".join(i["opts"])) if i["opts"] else "", "uzum_id": i["id"]}
        did = f"u{i['id']}"
        s["drafts"][did] = d
        r = tg("sendPhoto", chat_id=chat, photo=i["photo"], parse_mode="HTML",
               caption=product_caption(d) + f"\n\n(на Uzum: {money(d['uzum'])})",
               reply_markup={"inline_keyboard": [[{"text": "✅ Опубликовать", "callback_data": f"pub:{did}"},
                                                  {"text": "⏭ Пропустить", "callback_data": f"del:{did}"}]]})
        if not r.get("ok"):
            tg("sendMessage", chat_id=chat, text=f"Не удалось показать фото для «{i['title']}»")

# ---------- покупатель: заказ ----------
def start_order(s, chat, user, pid):
    p = s["products"].get(pid)
    if not p:
        tg("sendMessage", chat_id=chat, text="Этот товар не найден.")
        return
    s["sessions"][str(chat)] = {"step": "name", "pid": pid, "user": user}
    tg("sendPhoto", chat_id=chat, photo=p["photos"][0], parse_mode="HTML", caption=product_caption(p))
    tg("sendMessage", chat_id=chat, text="Оформим заказ. Как вас зовут?")

def order_text(o, p):
    return (f"<b>Заказ №{o['id']}</b>: {esc(p['title'])}\n"
            f"👤 {esc(o['name'])}\n📞 {esc(o['phone'])}\n📍 {esc(o['address'])}\n"
            f"📝 {esc(o.get('comment') or '—')}\n\n"
            f"Товар: {money(p['price'])}\nДоставка EMU Post: {money(DELIVERY_FEE)}\n"
            f"<b>Итого: {money(p['price'] + DELIVERY_FEE)}</b>")

def customer_step(s, chat, msg):
    ses = s["sessions"].get(str(chat))
    if not ses:
        return False
    text = (msg.get("text") or "").strip()
    step = ses["step"]
    if step == "name" and text:
        ses["name"] = text; ses["step"] = "phone"
        tg("sendMessage", chat_id=chat, text="Ваш номер телефона (можно кнопкой ниже):",
           reply_markup={"keyboard": [[{"text": "📞 Отправить номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True})
    elif step == "phone" and (text or msg.get("contact")):
        ses["phone"] = msg["contact"]["phone_number"] if msg.get("contact") else text
        ses["step"] = "address"
        tg("sendMessage", chat_id=chat, text="Адрес доставки (область, город/район, улица, дом, индекс отделения EMU Post если знаете):", reply_markup={"remove_keyboard": True})
    elif step == "address" and text:
        ses["address"] = text; ses["step"] = "comment"
        tg("sendMessage", chat_id=chat, text="Размер, цвет, количество или другие пожелания (или напишите «-»):")
    elif step == "comment" and text:
        oid = str(s["next_order"]); s["next_order"] += 1
        o = {"id": oid, "chat": chat, "pid": ses["pid"], "name": ses["name"], "phone": ses["phone"],
             "address": ses["address"], "comment": "" if text == "-" else text, "status": "new", "user": ses.get("user")}
        s["orders"][oid] = o
        ses["step"] = "pay"; ses["oid"] = oid
        p = s["products"][o["pid"]]
        tg("sendMessage", chat_id=chat, parse_mode="HTML",
           text=order_text(o, p) + f"\n\n💳 Оплата:\n{esc(PAY_INFO)}\n\nПосле оплаты нажмите кнопку и пришлите скриншот чека.",
           reply_markup={"inline_keyboard": [[{"text": "✅ Я оплатил(а)", "callback_data": f"paid:{oid}"}]]})
    elif step == "receipt" and (msg.get("photo") or msg.get("document")):
        oid = ses["oid"]; o = s["orders"][oid]; o["status"] = "paid_wait"
        p = s["products"][o["pid"]]
        tg("forwardMessage", chat_id=ADMIN, from_chat_id=chat, message_id=msg["message_id"])
        tg("sendMessage", chat_id=ADMIN, parse_mode="HTML", text="💰 Проверьте оплату\n\n" + order_text(o, p),
           reply_markup={"inline_keyboard": [[{"text": "✅ Подтвердить", "callback_data": f"ok:{oid}"},
                                              {"text": "❌ Не пришла", "callback_data": f"no:{oid}"}]]})
        tg("sendMessage", chat_id=chat, text="Спасибо! Чек отправлен, ждём подтверждения оплаты.")
        del s["sessions"][str(chat)]
    else:
        return False
    return True

def callback(s, cq):
    data = cq.get("data", ""); who = str(cq["from"]["id"]); chat = cq["message"]["chat"]["id"]
    act, _, arg = data.partition(":")
    ans = ""
    if act in ("pub", "del") and who == ADMIN:
        if act == "pub":
            ans = publish(s, arg)
        else:
            dd = s["drafts"].pop(arg, None)
            if dd and dd.get("uzum_id"):
                s.setdefault("uzum_done", []).append(dd["uzum_id"])
            ans = "Пропущено"
        tg("editMessageReplyMarkup", chat_id=chat, message_id=cq["message"]["message_id"], reply_markup={"inline_keyboard": []})
    elif act == "paid":
        ses = s["sessions"].get(str(chat))
        if ses and ses.get("oid") == arg:
            ses["step"] = "receipt"
            tg("sendMessage", chat_id=chat, text="Пришлите скриншот или фото чека одним сообщением.")
    elif act in ("ok", "no") and who == ADMIN:
        o = s["orders"].get(arg)
        if o:
            if act == "ok":
                o["status"] = "paid"
                tg("sendMessage", chat_id=o["chat"], text=f"✅ Оплата заказа №{arg} подтверждена. Отправим через EMU Post и пришлём трек-номер.")
                ans = "Подтверждено. Трек: /track " + arg + " НОМЕР"
            else:
                o["status"] = "unpaid"
                tg("sendMessage", chat_id=o["chat"], text=f"Оплата заказа №{arg} не найдена. Если вы платили, напишите администратору.")
                ans = "Отклонено"
            tg("editMessageReplyMarkup", chat_id=chat, message_id=cq["message"]["message_id"], reply_markup={"inline_keyboard": []})
    tg("answerCallbackQuery", callback_query_id=cq["id"], text=ans)

def handle(s, u):
    if u.get("callback_query"):
        return callback(s, u["callback_query"])
    msg = u.get("message")
    if not msg or msg["chat"]["type"] != "private":
        return
    chat = msg["chat"]["id"]; uid = str(msg["from"]["id"]); text = (msg.get("text") or "").strip()
    if text.startswith("/id"):
        tg("sendMessage", chat_id=chat, text=f"Ваш ID: {uid}")
        return
    if text.startswith("/start"):
        arg = text.split(maxsplit=1)[1] if " " in text else ""
        if arg.startswith("p"):
            return start_order(s, chat, msg["from"].get("username"), arg[1:])
        tg("sendMessage", chat_id=chat, text="Здравствуйте! Выберите товар в нашем канале и нажмите «🛒 Заказать».\n" + (f"https://t.me/{CHANNEL.lstrip('@')}" if CHANNEL.startswith("@") else ""))
        return
    if uid == ADMIN:
        if text.startswith("/track"):
            parts = text.split(maxsplit=2)
            o = s["orders"].get(parts[1]) if len(parts) > 2 else None
            if o:
                tg("sendMessage", chat_id=o["chat"], text=f"📦 Заказ №{o['id']} отправлен EMU Post. Трек-номер: {parts[2]}")
                o["status"] = "shipped"; tg("sendMessage", chat_id=chat, text="Отправлено покупателю")
            else:
                tg("sendMessage", chat_id=chat, text="Формат: /track НОМЕР_ЗАКАЗА ТРЕК")
            return
        if text.startswith("/uzum"):
            return uzum_offer(s, chat)
        if msg.get("photo"):
            return admin_photo(s, msg)
        if text.startswith("/help") or text.startswith("/admin"):
            tg("sendMessage", chat_id=chat, text="Чтобы добавить товар, пришлите фото (можно несколько) с подписью:\nНазвание | цена на Uzum | описание\nЦена в канале будет на %g%% ниже. Товары из Uzum: /uzum. Трек-номер: /track НОМЕР ТРЕК" % DISCOUNT)
            return
    if customer_step(s, chat, msg):
        return
    if uid == ADMIN:
        return
    tg("sendMessage", chat_id=chat, text="Выберите товар в канале и нажмите «🛒 Заказать».")

def main():
    s = load(); end = time.time() + RUN_SECONDS
    if not ADMIN:
        print("ADMIN_CHAT_ID не задан: админ-функции отключены (бот отвечает на /id)")
    while time.time() < end:
        r = tg("getUpdates", offset=s["offset"], timeout=20, allowed_updates=["message", "callback_query"])
        for u in r.get("result", []):
            s["offset"] = u["update_id"] + 1
            try:
                handle(s, u)
            except Exception as e:
                print("ERR", e)
        flush_albums(s)
        save(s)

if __name__ == "__main__":
    main()
