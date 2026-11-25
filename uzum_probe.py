"""Разведка поставок: сколько их, как выглядят номера (последние 4 цифры скрыты), статусы."""
import os, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
out = []
m = lambda v: (str(v)[:-4] + "####" + f"({len(str(v))})") if v not in (None, "") else "None"
def lst(page, size, **p):
    r = requests.get(BASE + "/v1/invoice", headers=H, params=dict(page=page, size=size, **p), timeout=30)
    return r.status_code, (r.json() if r.status_code == 200 else [])
for size in (10, 50, 100):
    code, j = lst(0, size)
    out.append(f"size={size} -> {code}, получено {len(j)}")
total, seen = 0, []
for page in range(0, 40):
    code, j = lst(page, 50)
    if code != 200 or not j:
        out.append(f"страниц с данными: {page}, последний код {code}"); break
    total += len(j); seen += j
out.append(f"всего поставок получено: {total}")
for inv in seen[:3] + seen[-3:]:
    out.append(f"number={m(inv.get('invoiceNumber'))} id={m(inv.get('id'))} ext={m(inv.get('externalNumber'))} status={(inv.get('invoiceStatus') or {}).get('value')} date={str(inv.get('dateCreated'))[:10]} products={len(inv.get('productForInvoiceDto') or [])}")
# фильтр по номеру
code, j = lst(0, 5, invoiceNumber=110004288155)
out.append(f"фильтр invoiceNumber -> {code}, {len(j)}")
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
