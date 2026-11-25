"""Разведка поставок (FBO invoices). В файл — только коды ответов и имена полей, без значений."""
import os, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
NUMS = ["110004288155", "110004284738"]
out = []
def keys(x, d=0):
    if isinstance(x, dict):
        return {k: (keys(v, d + 1) if d < 3 else type(v).__name__) for k, v in x.items()}
    if isinstance(x, list):
        return [keys(x[0], d + 1)] if x else []
    return type(x).__name__
def try_(path, **p):
    try:
        r = requests.get(BASE + path, headers=H, params=p, timeout=30)
    except Exception as e:
        out.append(f"{path} {p.keys()} ERR"); return None
    out.append(f"{path} {list(p.keys())} -> {r.status_code}")
    if r.status_code == 200:
        try:
            j = r.json(); out.append("   " + str(keys(j))[:1400]); return j
        except Exception:
            pass
    return None
for path in ("/v1/invoice", "/v1/fbo/invoice", "/v2/fbo/invoice", "/v1/supply", "/v1/fbo/supply", "/v1/invoices"):
    try_(path, page=0, size=3)
shops = requests.get(BASE + "/v1/shops", headers=H, timeout=30).json()
sid = shops[0]["id"] if shops else None
for path in ("/v1/invoice", "/v1/fbo/invoice", "/v2/fbo/invoice", "/v1/shop/%s/invoice" % sid):
    try_(path, page=0, size=3, shopId=sid)
for n in NUMS:
    for path in ("/v1/invoice/products", "/v1/fbo/invoice/products", "/v1/invoice/%s" % n, "/v1/fbo/invoice/%s" % n):
        try_(path, invoiceId=n, page=0, size=3)
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
