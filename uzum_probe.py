"""Разведка: сколько разных фото доступно у товара. В файл пишутся только числа/имена полей, без значений."""
import os, re, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
out = []
def keys(x, d=0):
    if isinstance(x, dict):
        return {k: (keys(v, d + 1) if d < 2 else type(v).__name__) for k, v in x.items()}
    if isinstance(x, list):
        return [keys(x[0], d + 1)] if x else []
    return type(x).__name__
for sh in requests.get(BASE + "/v1/shops", headers=H, timeout=30).json():
    r = requests.get(f"{BASE}/v1/product/shop/{sh['id']}", headers=H, params=dict(searchQuery="", filter="ALL", sortBy="DEFAULT", order="ASC", size=5, page=0), timeout=30)
    if r.status_code != 200:
        continue
    for p in r.json().get("productList", []):
        imgs = {k.get("previewImage") for k in p.get("skuList", []) if k.get("previewImage")}
        out.append(f"product: skus={len(p.get('skuList', []))} distinct sku images={len(imgs)}")
    pid = r.json()["productList"][0]["productId"]
    for path in (f"/v1/product/{pid}", f"/v2/product/{pid}", f"/v1/product/shop/{sh['id']}/{pid}"):
        rr = requests.get(BASE + path, headers=H, timeout=30)
        out.append(f"{path.replace(str(pid),'ID').replace(str(sh['id']),'SHOP')} -> {rr.status_code}")
        if rr.status_code == 200:
            try:
                out.append(str(keys(rr.json()))[:1500])
            except Exception:
                pass
    sk = r.json()["productList"][0]["skuList"][0]
    out.append("sku photo/characteristicsList keys: " + str(keys({"photo": sk.get("photo"), "cl": sk.get("characteristicsList")}))[:500])
    break
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
