"""Разведка Uzum Seller API. Пишет в uzum_probe.txt ТОЛЬКО имена полей и типы (никаких значений, ключа и текстов ответа)."""
import os, json, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
out = []
def shape(x, d=0):
    if isinstance(x, dict):
        return {k: (shape(v, d + 1) if d < 4 else type(v).__name__) for k, v in x.items()}
    if isinstance(x, list):
        return [shape(x[0], d + 1)] if x else []
    return type(x).__name__
def get(path, **p):
    for name, hdr in (("raw", {"Authorization": KEY}), ("bearer", {"Authorization": "Bearer " + KEY})):
        try:
            r = requests.get(BASE + path, headers=hdr, params=p, timeout=30)
        except Exception as e:
            out.append(f"{path} {name} ERR {type(e).__name__}"); return None
        out.append(f"{path} {name} -> {r.status_code}")
        if r.status_code == 200:
            try:
                j = r.json()
            except Exception:
                out.append("not json"); return None
            out.append(json.dumps(shape(j), ensure_ascii=False)[:3000]); return j
    return None
shops = get("/v1/shops")
ids = []
if shops:
    lst = shops.get("payload", shops) if isinstance(shops, dict) else shops
    ids = [s.get("id") for s in lst if isinstance(s, dict)]
out.append(f"shops: {len(ids)}")
for sid in ids[:1]:
    get(f"/v1/product/shop/{sid}", searchQuery="", filter="ALL", sortBy="DEFAULT", order="ASC", size=2, page=0)
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
