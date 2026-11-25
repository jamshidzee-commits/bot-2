"""Разведка форматов фото: пишет в uzum_probe.txt только МАСКИРОВАННЫЕ шаблоны ссылок на публичные фото (без значений и ключа)."""
import os, re, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
mask = lambda v: re.sub(r"[0-9a-zA-Z]{12,}", "X", str(v))[:200] if v else repr(v)
out = []
for sh in requests.get(BASE + "/v1/shops", headers=H, timeout=30).json():
    r = requests.get(f"{BASE}/v1/product/shop/{sh['id']}", headers=H, params=dict(searchQuery="", filter="ALL", sortBy="DEFAULT", order="ASC", size=2, page=0), timeout=30)
    if r.status_code != 200:
        continue
    for p in r.json().get("productList", [])[:2]:
        out.append("image=" + mask(p.get("image")) + " | previewImg=" + mask(p.get("previewImg")))
        k = (p.get("skuList") or [{}])[0]
        out.append("sku.previewImage=" + mask(k.get("previewImage")) + " | photo=" + mask(k.get("photo")))
        out.append("product keys: " + ",".join(sorted(p.keys())))
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
