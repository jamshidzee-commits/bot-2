"""Разведка поставки: из каких полей брать размеры (SKU). Пишем только имена полей и счётчики совпадений."""
import os, requests
KEY = os.environ["UZUM_API_KEY"].strip()
BASE = "https://api-seller.uzum.uz/api/seller-openapi"
H = {"Authorization": KEY}
out = []
get = lambda path, **p: requests.get(BASE + path, headers=H, params=p, timeout=30)
sku_ids, prod_ids, barcodes = set(), set(), set()
for sh in get("/v1/shops").json():
    for page in range(30):
        r = get(f"/v1/product/shop/{sh['id']}", searchQuery="", filter="ALL", sortBy="DEFAULT", order="ASC", size=20, page=page)
        if r.status_code != 200:
            break
        lst = r.json().get("productList", [])
        for pr in lst:
            prod_ids.add(str(pr["productId"]))
            for k in pr.get("skuList", []):
                sku_ids.add(str(k.get("skuId"))); barcodes.add(str(k.get("barcode")))
        if len(lst) < 20:
            break
    break
out.append(f"каталог: товаров {len(prod_ids)}, sku {len(sku_ids)}")
inv_all = []
for page in range(3):
    inv_all += get("/v1/invoice", page=page, size=50).json()
for inv in inv_all:
    if str(inv.get("invoiceNumber")).startswith(("110004288155", "110004284738", "110004279766")):
        for pd in inv.get("productForInvoiceDto") or []:
            sk = pd.get("skuForInvoiceDtoList") or []
            out.append(f"line: keys={sorted(pd.keys())} id_is_sku={str(pd.get('id')) in sku_ids} id_is_product={str(pd.get('id')) in prod_ids} qtyToStock={pd.get('quantityToStock')} nested={len(sk)}")
            if sk:
                e = sk[0]
                out.append("   nested keys=" + ",".join(sorted(e.keys())) + f" | skuId_match={sum(str(x.get('skuId')) in sku_ids for x in sk)}/{len(sk)} barcode_match={sum(str(x.get('barcode')) in barcodes for x in sk)}/{len(sk)} id_match={sum(str(x.get('id')) in sku_ids for x in sk)}/{len(sk)}")
        break
open("uzum_probe.txt", "w", encoding="utf-8").write("\n".join(out))
