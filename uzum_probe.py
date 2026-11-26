"""Сколько разных фото можно собрать из API: фото вариантов в каталоге и поле photo в строках поставок (только счётчики)."""
import os, re, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
WANT = ("110004288155", "110004284738", "110004279766", "110004266346", "110004264439", "110004263224")
out, invs, seen = [], [], set()
for sh in requests.get(BASE + "/v1/shops", headers=H, timeout=30).json():
    for page in range(30):
        r = requests.get(BASE + "/v1/invoice", headers=H, params=dict(page=page, size=50, shopId=sh["id"]), timeout=30)
        if r.status_code != 200 or not r.json():
            break
        for i in r.json():
            n = str(i.get("invoiceNumber"))
            if n.startswith(WANT) and n not in seen:
                seen.add(n); invs.append(i)
    break
def fmt(v):
    return re.sub(r"[0-9a-z]{16,}", "H", str(v))[:60]
for i in invs[:6]:
    for line in i.get("productForInvoiceDto") or []:
        photos = [k.get("photo") for k in line.get("skuForInvoiceDtoList") or []]
        d = {p for p in photos if p}
        out.append(f"товар: sku={len(photos)} с photo={sum(1 for p in photos if p)} разных photo={len(d)} образец={fmt(next(iter(d), None))}")
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out[:40]))
