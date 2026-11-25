"""Telegram do'kon boti: kanalga mahsulot joylash + buyurtma + to'lov + yetkazib berish (EMU Post)."""
import os, re, json, time, html, requests

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

# EMU Post: доставка до пункта выдачи (ПВЗ), тариф "Do ofisa", отправка из Ташкентской области (Янгиюль).
REGIONS = [("Каракалпакстан", 3), ("Андижан", 2), ("Бухара", 3), ("Джизак", 2), ("Кашкадарья", 3), ("Навои", 3), ("Наманган", 2),
           ("Самарканд", 2), ("Сурхандарья", 4), ("Сырдарья", 1), ("Ташкентская обл.", 0), ("Фергана", 2), ("Хорезм", 3), ("г. Ташкент", 1)]
BASE_1KG = [22000, 25000, 27000, 29000, 33000]   # первый кг, по зонам 0..4
EXTRA_KG = [3000, 6000, 7000, 8000, 9000]        # каждый следующий кг (до 20 кг)
VAT = 1.06
WEIGHT_KG = float(os.environ.get("DEFAULT_WEIGHT_KG") or 0.5)  # вес одной вещи, кг

def delivery_fee(zone, kg=None):
    kg = max(1, int(-(-(kg or WEIGHT_KG) // 1)))  # округляем вверх до целого кг, минимум 1
    return int(round((BASE_1KG[zone] + EXTRA_KG[zone] * (kg - 1)) * VAT))

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
    t += f"\n💰 Цена: <b>{money(p['price'])}</b>\n🚚 Доставка EMU Post — платная (считается при заказе)"
    return t

WEBAPP_URL = os.environ.get("WEBAPP_URL") or "https://jamshidzee-commits.github.io/online-shop-bot/"

def export_catalog(s):
    """Каталог для мини-приложения (docs/products.json) — только товары с фото-ссылкой."""
    items = []
    for pid, p in s["products"].items():
        ph = (p.get("photos") or [""])[0]
        if p.get("hidden") or not ph.startswith("http"):
            continue
        items.append({"id": pid, "title": p["title"], "price": p["price"], "old": p.get("uzum", 0), "photo": ph, "photos": [u for u in p.get("photos", []) if u.startswith("http")],
                      "opts": p.get("opts", []), "desc": p.get("desc", "")})
    os.makedirs("docs", exist_ok=True)
    data = json.dumps({"bot": me(s), "products": items[::-1]}, ensure_ascii=False)
    try:
        if open("docs/products.json", encoding="utf-8").read() == data:
            return
    except Exception:
        pass
    open("docs/products.json", "w", encoding="utf-8").write(data)

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
    ap = s.get("add_pid")
    if not cap and ap and time.time() - ap["t"] < 600:
        s["add_pid"] = None
        return add_photos(s, ap["pid"], photos)
    if cap and cap.strip().startswith("+"):
        return add_photos(s, cap.strip()[1:].split()[0], photos)
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

def post_to_channel(s, pid):
    d = s["products"][pid]
    kb = product_kb(s, pid)
    ids = d.get("photo_ids", {})
    photos = [ids.get(u, u) for u in d["photos"][:10]]
    cap = product_caption(d)
    msgs = []
    if len(photos) == 1:
        r = tg("sendPhoto", chat_id=CHANNEL, photo=photos[0], caption=cap, parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            msgs.append(r["result"]["message_id"])
    else:
        media = [{"type": "photo", "media": f} for f in photos]
        media[0]["caption"] = cap; media[0]["parse_mode"] = "HTML"
        r = tg("sendMediaGroup", chat_id=CHANNEL, media=media)
        if r.get("ok"):
            msgs += [m["message_id"] for m in r["result"]]
        r = tg("sendMessage", chat_id=CHANNEL, text=f"👆 {esc(d['title'])}", parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            msgs.append(r["result"]["message_id"])
    d["msgs"] = msgs

def add_photos(s, pid, fids):
    """Дополнительные фото к опубликованному товару: сохраняем в docs/img (для приложения) и переопубликуем пост."""
    p = s["products"].get(pid)
    if not p:
        tg("sendMessage", chat_id=ADMIN, text="Не нашёл такой товар. Номера: /list"); return
    os.makedirs("docs/img", exist_ok=True)
    p.setdefault("photo_ids", {})
    for n, fid in enumerate(fids):
        info = tg("getFile", file_id=fid).get("result") or {}
        if not info.get("file_path"):
            continue
        try:
            data = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}", timeout=60).content
        except Exception as e:
            print("download", type(e).__name__); continue
        name = f"{pid}_{int(time.time())}_{n}.jpg"
        open(f"docs/img/{name}", "wb").write(data)
        url = WEBAPP_URL + "img/" + name
        p["photos"].append(url); p["photo_ids"][url] = fid
    p["photos"] = p["photos"][:10]
    for m in p.get("msgs", []):
        tg("deleteMessage", chat_id=CHANNEL, message_id=m)
    post_to_channel(s, pid)
    export_catalog(s)
    tg("sendMessage", chat_id=ADMIN, text=f"Добавлено фото. Теперь у товара «{p['title'][:40]}» {len(p['photos'])} фото. Пост в канале обновлён, в приложении фото появятся через 1–2 минуты.")

def publish(s, did):
    d = s["drafts"].pop(did, None)
    if not d:
        return "Уже обработано"
    if d.get("uzum_id"):
        s.setdefault("uzum_done", []).append(d["uzum_id"])
    pid = str(s["next_product"]); s["next_product"] += 1
    s["products"][pid] = d
    export_catalog(s)
    post_to_channel(s, pid)
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

def best_img(url):
    """Берём самое крупное фото, которое реально отдаётся."""
    base = url.rsplit("/", 1)[0]
    for name in ("original.jpg", "t_product_1080_high.jpg", "t_product_540_high.jpg"):
        try:
            if requests.head(f"{base}/{name}", timeout=15, allow_redirects=True).status_code == 200:
                return f"{base}/{name}"
        except Exception:
            pass
    return url

UZUM_ERRORS = 0
UZUM_MATCHED = set()

def sku_codes(k):
    return {str(x).strip() for x in (k.get("skuId"), k.get("barcode"), k.get("sellerItemCode"), k.get("article")) if x not in (None, "")}

def uzum_products(my=None, need_stock=False):
    """Все товары всех магазинов продавца, в наличии."""
    global UZUM_ERRORS, UZUM_MATCHED
    UZUM_ERRORS = 0
    UZUM_MATCHED = set()
    my = set(my) if my else None
    out = []
    for sh in uzum_get("/v1/shops"):
        page = 0
        while page < 40:
            try:
                j = uzum_get(f"/v1/product/shop/{sh['id']}", searchQuery="", filter="ALL", sortBy="DEFAULT", order="ASC", size=20, page=page)
            except requests.HTTPError as e:
                print("UZUM shop", sh["id"], "->", e.response.status_code)
                if e.response.status_code != 403:  # 403 = ключ не даёт доступ к чужому магазину, это нормально
                    UZUM_ERRORS += 1
                break
            lst = j.get("productList") or []
            for pr in lst:
                if my:  # режим «мой склад»: берём только позиции из твоего списка, остаток Uzum не важен
                    skus = []
                    for k in pr.get("skuList", []):
                        hit = (sku_codes(k) | {str(pr.get("productId"))}) & my
                        if hit and (not need_stock or ((k.get("quantityAvailable") or 0) > 0 and not k.get("archived") and not k.get("blocked"))):
                            UZUM_MATCHED |= hit; skus.append(k)
                else:
                    skus = [k for k in pr.get("skuList", []) if (k.get("quantityAvailable") or 0) > 0 and not k.get("archived") and not k.get("blocked")]
                if not skus:
                    continue
                price = min((k.get("price") or 0) for k in skus) or pr.get("price") or 0
                opts = []
                for k in skus:
                    c = (k.get("characteristics") or k.get("skuTitle") or "").strip()
                    if c and c not in opts:
                        opts.append(c)
                img = uzum_img(pr.get("image") or pr.get("previewImg") or (skus[0].get("previewImage")))
                photos, seen = [], set()
                for u in [img] + [uzum_img(k.get("previewImage")) for k in pr.get("skuList", [])]:
                    if u and u.split("/")[3:4] and u.split("/")[3] not in seen:
                        seen.add(u.split("/")[3]); photos.append(u)
                if price and img:
                    out.append({"id": str(pr["productId"]), "title": pr.get("title") or skus[0].get("productTitle"), "uzum": int(price),
                                "photo": img, "photos": photos[:10], "opts": opts[:12]})
            if len(lst) < 20:
                break
            page += 1
    return out

def uzum_offer(s, chat):
    if not UZUM_KEY:
        tg("sendMessage", chat_id=chat, text="Ключ Uzum не подключён (секрет UZUM_API_KEY).")
        return
    try:
        items = uzum_products(s.get("mystock"), s.get("mystock_instock", False))
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", "")
        tg("sendMessage", chat_id=chat, text=f"Ошибка Uzum API: {type(e).__name__} {code}")
        print("UZUM ERR", repr(e)[:300])
        return
    done = set(s.setdefault("uzum_done", []))
    new = [i for i in items if i["id"] not in done]
    tg("sendMessage", chat_id=chat, text=f"Товаров в наличии на Uzum: {len(items)}, ещё не в канале: {len(new)}. Показываю до 10.")
    from concurrent.futures import ThreadPoolExecutor
    batch = new[:10]
    with ThreadPoolExecutor(8) as ex:
        for i in batch:
            i["photos"] = list(ex.map(best_img, i.get("photos") or [i["photo"]]))
    for i in batch:
        d = {"title": i["title"], "uzum": i["uzum"], "price": shop_price(i["uzum"]), "photos": i["photos"],
             "desc": ("Варианты: " + "; ".join(i["opts"])) if i["opts"] else "", "uzum_id": i["id"], "opts": i["opts"]}
        did = f"u{i['id']}"
        s["drafts"][did] = d
        cap = product_caption(d) + f"\n\n(на Uzum: {money(d['uzum'])}, фото: {len(d['photos'])})"
        kb = {"inline_keyboard": [[{"text": "✅ Опубликовать", "callback_data": f"pub:{did}"},
                                   {"text": "⏭ Пропустить", "callback_data": f"del:{did}"}]]}
        ok = False
        if len(d["photos"]) > 1:
            media = [{"type": "photo", "media": u} for u in d["photos"]]
            media[0]["caption"] = cap; media[0]["parse_mode"] = "HTML"
            ok = tg("sendMediaGroup", chat_id=chat, media=media).get("ok")
            if ok:
                tg("sendMessage", chat_id=chat, text=f"👆 {i['title'][:60]}", reply_markup=kb)
        if not ok:
            r = tg("sendPhoto", chat_id=chat, photo=d["photos"][0], parse_mode="HTML", caption=cap, reply_markup=kb)
            if not r.get("ok"):
                tg("sendMessage", chat_id=chat, text=f"Не удалось показать фото для «{i['title']}»")

def remove_product(s, pid):
    p = s["products"].get(pid)
    if not p:
        return False
    for m in p.get("msgs", []):
        tg("deleteMessage", chat_id=CHANNEL, message_id=m)
    p["msgs"] = []; p["hidden"] = True
    export_catalog(s)
    return True

def collect_codes(x, out):
    """Собирает ID/штрихкоды/артикулы из строки поставки Uzum (структура может меняться)."""
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(v, (dict, list)):
                collect_codes(v, out)
            elif v not in (None, "") and k in ("id", "skuId", "productId", "barcode", "sellerItemCode", "article"):
                out.add(str(v).strip())
    elif isinstance(x, list):
        for v in x:
            collect_codes(v, out)

def supply_codes(numbers):
    """Коды товаров из поставок Uzum по их номерам. Возвращает (коды, найденные номера, подсказка)."""
    want = set(numbers); found, codes, hint = set(), set(), ""
    for shop in uzum_get("/v1/shops"):
        for page in range(0, 30):
            try:
                lst = uzum_get("/v1/invoice", page=page, size=50, shopId=shop["id"])
            except requests.HTTPError:
                break
            if not lst:
                break
            for inv in lst:
                full = str(inv.get("invoiceNumber"))
                # в API номер на одну цифру длиннее, чем в кабинете: сравниваем по началу
                n = next((w for w in want if full == w or full.startswith(w)), None)
                if n:
                    found.add(n)
                    for pd in inv.get("productForInvoiceDto") or []:
                        collect_codes(pd, codes)
                        if not hint and pd.get("skuForInvoiceDtoList"):
                            hint = ",".join(sorted(pd["skuForInvoiceDtoList"][0].keys()))
            if found >= want:
                return codes, found, hint
    return codes, found, hint

def product_kb(s, pid):
    return {"inline_keyboard": [[{"text": "🛍 Открыть магазин", "url": f"https://t.me/{me(s)}/shop"}]]}

def sync_stock(s, chat=None):
    """Убирает товары Uzum без остатка и обновляет список размеров/вариантов по наличию."""
    if not UZUM_KEY:
        return
    try:
        have = {i["id"]: i for i in uzum_products(s.get("mystock"), s.get("mystock_instock", False))}
    except Exception as e:
        print("sync", repr(e)[:200]); return
    if UZUM_ERRORS:
        print("sync: ошибки Uzum, пропускаю"); return
    gone, changed = [], []
    for pid, p in list(s["products"].items()):
        uid = p.get("uzum_id")
        if not uid or p.get("hidden"):
            continue
        if uid not in have:
            gone.append(pid); continue
        opts = have[uid]["opts"]
        if opts != p.get("opts", []):
            p["opts"] = opts
            p["desc"] = ("Варианты: " + "; ".join(opts)) if opts else ""
            changed.append(p["title"])
            if p.get("msgs"):
                kb = product_kb(s, pid) if len(p.get("photos", [])) <= 1 else None
                data = dict(chat_id=CHANNEL, message_id=p["msgs"][0], caption=product_caption(p), parse_mode="HTML")
                if kb:
                    data["reply_markup"] = kb
                tg("editMessageCaption", **data)
    names = [s["products"][pid]["title"] for pid in gone if remove_product(s, pid)]
    if changed:
        export_catalog(s)
    if chat is not None or names or changed:
        txt = []
        if names:
            txt.append("Убраны (нет в наличии):\n• " + "\n• ".join(names))
        if changed:
            txt.append("Обновлены размеры/варианты:\n• " + "\n• ".join(changed))
        tg("sendMessage", chat_id=chat or ADMIN, text="\n\n".join(txt) or "Всё в наличии, изменений нет.")

# ---------- покупатель: заказ ----------
def cart_of(s, chat):
    return s.setdefault("carts", {}).setdefault(str(chat), [])

def start_order(s, chat, user, pid):
    p = s["products"].get(pid)
    if not p:
        tg("sendMessage", chat_id=chat, text="Этот товар не найден.")
        return
    s["sessions"][str(chat)] = {"step": "note", "pid": pid, "user": user}
    tg("sendPhoto", chat_id=chat, photo=p["photos"][0], parse_mode="HTML", caption=product_caption(p))
    tg("sendMessage", chat_id=chat, text="Напишите размер, цвет и количество (или «-», если не нужно):")

def start_cart(s, chat, user, code):
    items = []
    for part in code.split("-"):
        try:
            pid, oi, q = part.split("_"); p = s["products"].get(pid)
            if not p:
                continue
            oi, q = int(oi), max(1, min(int(q), 20))
            opts = p.get("opts") or []
            items.append({"pid": pid, "qty": q, "note": opts[oi] if oi < len(opts) else ""})
        except Exception:
            continue
    if not items:
        tg("sendMessage", chat_id=chat, text="Корзина пуста или товары больше недоступны. Откройте магазин заново.")
        return
    s.setdefault("carts", {})[str(chat)] = items
    s["sessions"][str(chat)] = {"step": "cart", "user": user}
    body, total = cart_text(s, items)
    tg("sendMessage", chat_id=chat, parse_mode="HTML", text=f"🛒 Ваш заказ:\n{body}\n\nТовары: {money(total)} (доставка считается дальше)",
       reply_markup={"inline_keyboard": [[{"text": "✅ Оформить заказ", "callback_data": "checkout:1"}],
                                         [{"text": "🗑 Очистить корзину", "callback_data": "clear:1"}]]})

def cart_text(s, items):
    lines, total = [], 0
    for n, it in enumerate(items, 1):
        p = s["products"][it["pid"]]; q = it.get("qty", 1); total += p["price"] * q
        lines.append(f"{n}. {esc(p['title'])}" + (f" × {q}" if q > 1 else "") + f" — {money(p['price'] * q)}" + (f"\n    📝 {esc(it['note'])}" if it.get("note") else ""))
    return "\n".join(lines), total

def order_items(s, o):
    return o.get("items") or [{"pid": o["pid"], "note": o.get("comment", "")}]

def order_text(s, o):
    body, total = cart_text(s, order_items(s, o))
    return (f"<b>Заказ №{o['id']}</b>\n{body}\n\n"
            f"👤 {esc(o['name'])}\n📞 {esc(o['phone'])}\n📍 {esc(o.get('region',''))}, {esc(o['address'])}\n\n"
            f"Товары: {money(total)}\nДоставка EMU Post до пункта выдачи: {money(o['fee'])}\n"
            f"<b>Итого: {money(total + o['fee'])}</b>")

def items_weight(items):
    return sum(i.get("qty", 1) for i in items) * WEIGHT_KG

def customer_step(s, chat, msg):
    ses = s["sessions"].get(str(chat))
    if not ses:
        return False
    text = (msg.get("text") or "").strip()
    step = ses["step"]
    if step == "note" and text:
        items = cart_of(s, chat)
        items.append({"pid": ses["pid"], "note": "" if text == "-" else text})
        body, total = cart_text(s, items)
        ses["step"] = "cart"
        tg("sendMessage", chat_id=chat, parse_mode="HTML", text=f"🛒 Ваша корзина:\n{body}\n\nТовары: {money(total)} (доставка считается дальше)",
           reply_markup={"inline_keyboard": [[{"text": "➕ Добавить ещё товар", "url": f"https://t.me/{CHANNEL.lstrip('@')}" if CHANNEL.startswith("@") else "https://t.me"}],
                                             [{"text": "✅ Оформить заказ", "callback_data": "checkout:1"}],
                                             [{"text": "🗑 Очистить корзину", "callback_data": "clear:1"}]]})
        tg("sendMessage", chat_id=chat, text="Чтобы добавить ещё товар, откройте канал и нажмите «🛒 Заказать» на нужной карточке: корзина сохранится.")
    elif step == "name" and text:
        ses["name"] = text; ses["step"] = "phone"
        tg("sendMessage", chat_id=chat, text="Ваш номер телефона (можно кнопкой ниже):",
           reply_markup={"keyboard": [[{"text": "📞 Отправить номер", "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True})
    elif step == "phone" and (text or msg.get("contact")):
        ses["phone"] = msg["contact"]["phone_number"] if msg.get("contact") else text
        ses["step"] = "region"
        tg("sendMessage", chat_id=chat, text="Принято.", reply_markup={"remove_keyboard": True})
        rows = [[{"text": REGIONS[i][0], "callback_data": f"reg:{i}"} for i in range(j, min(j + 2, len(REGIONS)))] for j in range(0, len(REGIONS), 2)]
        tg("sendMessage", chat_id=chat, text="В какую область доставить?", reply_markup={"inline_keyboard": rows})
    elif step == "address" and text:
        items = list(cart_of(s, chat))
        if not items:
            del s["sessions"][str(chat)]
            tg("sendMessage", chat_id=chat, text="Корзина пуста. Выберите товар в канале.")
            return True
        oid = str(s["next_order"]); s["next_order"] += 1
        o = {"id": oid, "chat": chat, "items": items, "name": ses["name"], "phone": ses["phone"], "address": text,
             "region": ses["region"], "fee": delivery_fee(ses["zone"], items_weight(items)), "status": "new", "user": ses.get("user")}
        s["orders"][oid] = o
        s["carts"][str(chat)] = []
        ses["step"] = "pay"; ses["oid"] = oid
        tg("sendMessage", chat_id=chat, parse_mode="HTML",
           text=order_text(s, o) + f"\n\n💳 Оплата:\n{esc(PAY_INFO)}\n\nПосле оплаты нажмите кнопку и пришлите скриншот чека.",
           reply_markup={"inline_keyboard": [[{"text": "✅ Я оплатил(а)", "callback_data": f"paid:{oid}"}]]})
    elif step == "receipt" and (msg.get("photo") or msg.get("document")):
        oid = ses["oid"]; o = s["orders"][oid]; o["status"] = "paid_wait"
        tg("forwardMessage", chat_id=ADMIN, from_chat_id=chat, message_id=msg["message_id"])
        tg("sendMessage", chat_id=ADMIN, parse_mode="HTML", text="💰 Проверьте оплату\n\n" + order_text(s, o),
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
    elif act == "rm" and who == ADMIN:
        ans = "Удалено" if remove_product(s, arg) else "Не найдено"
        tg("editMessageReplyMarkup", chat_id=chat, message_id=cq["message"]["message_id"], reply_markup={"inline_keyboard": []})
    elif act == "checkout":
        items = cart_of(s, chat)
        if items:
            ses = s["sessions"].setdefault(str(chat), {"user": None})
            ses["step"] = "name"
            tg("sendMessage", chat_id=chat, text="Как вас зовут?")
    elif act == "clear":
        s.setdefault("carts", {})[str(chat)] = []
        s["sessions"].pop(str(chat), None)
        tg("sendMessage", chat_id=chat, text="Корзина очищена.")
    elif act == "reg":
        ses = s["sessions"].get(str(chat))
        if ses and ses.get("step") == "region" and arg.isdigit() and int(arg) < len(REGIONS):
            name, zone = REGIONS[int(arg)]
            fee = delivery_fee(zone, items_weight(cart_of(s, chat)))
            ses["region"] = name; ses["zone"] = zone; ses["step"] = "address"
            tg("sendMessage", chat_id=chat, text=f"{name}. Доставка до пункта выдачи EMU Post: {money(fee)}.\nНапишите город/район и адрес или номер пункта выдачи EMU Post, куда привезти:")
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
        if (arg.startswith("ph") or arg.startswith("rm")) and uid == ADMIN:
            pid = arg[2:]; p = s["products"].get(pid)
            if not p:
                return tg("sendMessage", chat_id=chat, text="Не нашёл такой товар. Список: /list")
            if arg.startswith("ph"):
                s["add_pid"] = {"pid": pid, "t": time.time()}
                return tg("sendMessage", chat_id=chat, text=f"📷 «{p['title'][:50]}» сейчас {len(p.get('photos', []))} фото.\nПришлите новые фото (можно альбомом до 10 штук) в течение 10 минут.")
            return tg("sendMessage", chat_id=chat, text=f"Удалить «{p['title'][:50]}» из канала и приложения?",
                      reply_markup={"inline_keyboard": [[{"text": "🗑 Да, удалить", "callback_data": f"rm:{pid}"}, {"text": "Отмена", "callback_data": "x:0"}]]})
        if arg.startswith("c"):
            return start_cart(s, chat, msg["from"].get("username"), arg[1:])
        if arg.startswith("p"):
            return start_order(s, chat, msg["from"].get("username"), arg[1:])
        tg("sendMessage", chat_id=chat, text="Здравствуйте! Откройте магазин кнопкой ниже или выберите товар в нашем канале.",
           reply_markup={"inline_keyboard": [[{"text": "🛍 Открыть магазин", "web_app": {"url": WEBAPP_URL + ("?admin=1" if uid == ADMIN else "")}}]]})
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
        if text.startswith("/delall"):
            n = sum(1 for pid in list(s["products"]) if not s["products"][pid].get("hidden") and remove_product(s, pid))
            tg("sendMessage", chat_id=chat, text=f"Убрано товаров из приложения: {n}. Их посты в канале, которые бот помнит, удалены. Остальные старые посты можно стереть командой /clearchannel yes")
            return
        if text.startswith("/clearchannel"):
            if text.split()[-1].lower() != "yes":
                tg("sendMessage", chat_id=chat, text="Эта команда удалит последние ~300 сообщений в канале (включая закреплённое). Подтвердите: /clearchannel yes")
                return
            r = tg("sendMessage", chat_id=CHANNEL, text="…")
            if not r.get("ok"):
                tg("sendMessage", chat_id=chat, text="Не получилось: проверьте права бота в канале."); return
            top = r["result"]["message_id"]; n = 0
            for mid in range(top, max(top - 300, 0), -1):
                if tg("deleteMessage", chat_id=CHANNEL, message_id=mid).get("ok"):
                    n += 1
            for p in s["products"].values():
                p["msgs"] = []
            tg("sendMessage", chat_id=chat, text=f"Удалено сообщений в канале: {n}. Закреплённую кнопку магазина верните командой /pin")
            return
        if text.startswith("/supply"):
            nums = [c for c in re.split(r"[\s,;]+", text[len("/supply"):].strip()) if c]
            if not nums:
                tg("sendMessage", chat_id=chat, text="Пришлите номера поставок Uzum:\n/supply 110004288155 110004284738 ...")
                return
            try:
                codes, found, hint = supply_codes(nums)
            except Exception as e:
                tg("sendMessage", chat_id=chat, text=f"Ошибка Uzum: {type(e).__name__}"); return
            miss = [n for n in nums if n not in found]
            if not codes:
                tg("sendMessage", chat_id=chat, text=f"Поставки не найдены или пустые. Не найдены: {', '.join(miss) or '—'}. Поля: {hint}")
                return
            s["mystock"] = sorted(codes); s["mystock_instock"] = True
            try:
                items = uzum_products(s["mystock"], True)
            except Exception as e:
                tg("sendMessage", chat_id=chat, text=f"Поставки прочитаны, но Uzum не ответил: {type(e).__name__}"); return
            tg("sendMessage", chat_id=chat, text=f"Поставок найдено: {len(found)} из {len(nums)}" + (f" (нет: {', '.join(miss)})" if miss else "") +
               f".\nТоваров из них в наличии на Uzum: {len(items)}.\n\nПоказать для публикации: /uzum\nОтключить фильтр: /mystock clear")
            sync_stock(s, chat)  # сразу убираем ранее опубликованные товары, которых нет в поставках
            return
        if text.startswith("/mystock"):
            body = text[len("/mystock"):].strip()
            if body.lower().startswith("clear"):
                s["mystock"] = []
                tg("sendMessage", chat_id=chat, text="Список «мой склад» отключён. Теперь наличие берётся из остатков Uzum.")
                return
            add = body.lower().startswith("add")
            if add:
                body = body[3:]
            codes = [c for c in re.split(r"[\s,;]+", body) if c]
            if not codes:
                tg("sendMessage", chat_id=chat, text=("Список «мой склад»: " + str(len(s.get("mystock", []))) + " кодов.\n\n" if s.get("mystock") else "") +
                   "Пришлите команду и коды товаров из Uzum (SKU ID, штрихкод или артикул) через пробел, запятую или с новой строки:\n/mystock 123456 789012 ...\nДобавить к списку: /mystock add коды\nОтключить: /mystock clear")
                return
            s["mystock"] = sorted(set(s.get("mystock", [])) | set(codes)) if add else sorted(set(codes))
            s["mystock_instock"] = False
            try:
                items = uzum_products(s["mystock"])
            except Exception as e:
                tg("sendMessage", chat_id=chat, text=f"Список сохранён, но Uzum не ответил: {type(e).__name__}"); return
            miss = [c for c in s["mystock"] if c not in UZUM_MATCHED]
            tg("sendMessage", chat_id=chat, text=f"Список сохранён: {len(s['mystock'])} кодов. Найдено товаров в Uzum: {len(items)}." +
               (f"\nНе найдены коды ({len(miss)}): " + ", ".join(miss[:30]) if miss else "") + "\n\nЧтобы показать их для публикации: /uzum")
            return
        if text.startswith("/sync"):
            return sync_stock(s, chat)
        if text.startswith("/list"):
            lines = [f"{pid}. {p['title'][:50]} — {money(p['price'])}" for pid, p in s["products"].items() if not p.get("hidden")]
            tg("sendMessage", chat_id=chat, text=("Товары в магазине:\n" + "\n".join(lines) + "\n\nУдалить: /del НОМЕР") if lines else "Товаров нет.")
            return
        if text.startswith("/del"):
            arg = text.split(maxsplit=1)[1].strip() if " " in text else ""
            ok = remove_product(s, arg)
            tg("sendMessage", chat_id=chat, text="Удалено из канала и приложения." if ok else "Не нашёл такой номер. Список: /list")
            return
        if text.startswith("/pin"):
            r = tg("sendMessage", chat_id=CHANNEL, text="🛍 Весь ассортимент — в нашем магазине. Откройте и выбирайте:",
                   reply_markup={"inline_keyboard": [[{"text": "🛍 Открыть магазин", "url": f"https://t.me/{me(s)}/shop"}]]})
            if r.get("ok"):
                tg("pinChatMessage", chat_id=CHANNEL, message_id=r["result"]["message_id"])
                tg("sendMessage", chat_id=chat, text="Готово: сообщение с кнопкой магазина опубликовано и закреплено в канале.")
            else:
                tg("sendMessage", chat_id=chat, text="Не получилось опубликовать в канале. Проверьте, что у бота есть право публикации и закрепления сообщений.")
            return
        if text.startswith("/uzum"):
            return uzum_offer(s, chat)
        if msg.get("photo"):
            return admin_photo(s, msg)
        if text.startswith("/help") or text.startswith("/admin"):
            tg("sendMessage", chat_id=chat, text="Чтобы добавить товар, пришлите фото (можно несколько) с подписью:\nНазвание | цена на Uzum | описание\nЦена в канале будет на %g%% ниже. Товары из Uzum: /uzum. Товары из поставок: /supply НОМЕРА. Удалить всё: /delall. Добавить фото к товару: пришлите фото с подписью +НОМЕР (номер из /list). «Мой склад» по кодам: /mystock. Список: /list, удалить: /del НОМЕР, проверка наличия: /sync, закрепить магазин: /pin. Трек-номер: /track НОМЕР ТРЕК" % DISCOUNT)
            return
    if customer_step(s, chat, msg):
        return
    if uid == ADMIN:
        return
    tg("sendMessage", chat_id=chat, text="Выберите товар в канале и нажмите «🛒 Заказать».")

def main():
    s = load(); end = time.time() + RUN_SECONDS
    try:
        if s.get("kb_v") != 2:  # одноразово: у старых постов оставляем только кнопку магазина
            s["kb_v"] = 2
            for pid, p in s["products"].items():
                if p.get("msgs") and not p.get("hidden"):
                    tg("editMessageReplyMarkup", chat_id=CHANNEL, message_id=p["msgs"][-1], reply_markup=product_kb(s, pid))
        export_catalog(s)
        tg("setChatMenuButton", menu_button={"type": "web_app", "text": "🛍 Магазин", "web_app": {"url": WEBAPP_URL}})
        if ADMIN:  # у админа в приложении открывается ещё и кабинет
            tg("setChatMenuButton", chat_id=int(ADMIN), menu_button={"type": "web_app", "text": "🛍 Магазин", "web_app": {"url": WEBAPP_URL + "?admin=1"}})
    except Exception as e:
        print("catalog/menu", e)
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
        if time.time() - s.get("last_sync", 0) > 1800:
            s["last_sync"] = time.time()
            try:
                sync_stock(s)
            except Exception as e:
                print("sync err", e)
        save(s)

if __name__ == "__main__":
    main()
