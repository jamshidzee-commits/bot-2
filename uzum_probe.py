"""Сверка поставок: сколько счетов подходит под номер и сколько штук/позиций в каждом (номера частично скрыты)."""
import os, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
WANT = ["110004288155", "110004284738", "110004279766", "110004266346", "110004264439", "110004263224"]
out = []
inv_all = []
for sh in requests.get(BASE + "/v1/shops", headers=H, timeout=30).json():
    for page in range(30):
        r = requests.get(BASE + "/v1/invoice", headers=H, params=dict(page=page, size=50, shopId=sh["id"]), timeout=30)
        if r.status_code != 200 or not r.json():
            break
        inv_all += r.json()
out.append(f"всего счетов получено: {len(inv_all)}")
for w in WANT:
    ms = [i for i in inv_all if str(i.get("invoiceNumber")).startswith(w)]
    out.append(f"{w[:-3]}###: совпадений {len(ms)}")
    for i in ms:
        lines = i.get("productForInvoiceDto") or []
        skus = [k for l in lines for k in (l.get("skuForInvoiceDtoList") or [])]
        qty_lines = sum(l.get("quantityToStock") or 0 for l in lines)
        qty_skus = sum(k.get("quantityToStock") or 0 for k in skus)
        out.append(f"   номер длиной {len(str(i.get('invoiceNumber')))}, статус {(i.get('invoiceStatus') or {}).get('value')}, строк {len(lines)}, sku {len(skus)}, sku с qty>0 {sum(1 for k in skus if (k.get('quantityToStock') or 0) > 0)}, штук по строкам {qty_lines}, штук по sku {qty_skus}, totalToStock {i.get('totalToStock')}")
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
