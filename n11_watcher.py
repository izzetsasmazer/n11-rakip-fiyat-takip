"""Independent N11 catalog price watcher. Fail closed on ambiguous prices/sellers."""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from playwright.sync_api import sync_playwright
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps
import pytesseract

BASE="https://www.n11.com"
OWN="sasmazerltd"
RIVALS=("avrupabeyazesya","erhangulener","haneciogluticaret")
STATE=Path("n11-independent-state.json")
BATCH=int(os.getenv("BATCH_SIZE","8"))
PRICE_RE=re.compile(r"(?<!\d)(\d{1,3}(?:\.\d{3})+|\d{3,7})(?:,(\d{2}))?\s*(?:TL|₺)",re.I)
ID_RE=re.compile(r"-(\d{5,12})(?:\?|$)")
def now(): return datetime.now(timezone.utc).isoformat()
def cash(t):
    m=PRICE_RE.search(t or "")
    if not m: return None
    return int(m.group(1).replace(".",""))*100+int((m.group(2) or "00"))
def load():
    try: return json.loads(STATE.read_text(encoding="utf8"))
    except (OSError,ValueError): return {}
def save(data):
    STATE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
def goto(page,url):
    try:
        response=page.goto(url,wait_until="domcontentloaded",timeout=35000)
        page.wait_for_timeout(1400)
        if not response or response.status>=400: return False
        return True
    except Exception as e:
        print("PAGE_ERROR",url,type(e).__name__)
        return False
def listing(page):
    """Read catalog URLs from the user's publicly visible store, including lazy loading."""
    if not goto(page,BASE+"/magaza/"+OWN): return []
    found={}
    stagnant=0
    for _ in range(90):
        urls=page.locator('a[href*="/urun/"]').evaluate_all(
            "(els) => els.map(e => e.href)")
        previous=len(found)
        for u in urls:
            m=ID_RE.search(urlparse(u).path)
            if m and urlparse(u).hostname=="www.n11.com":
                found[m.group(1)]=u.split("?")[0]
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight*0.75))")
        page.wait_for_timeout(900)
        stagnant=stagnant+1 if previous==len(found) else 0
        if stagnant>=7:
            break
    print("OWN_CATALOG_IDS",len(found))
    return list(found.items())
def offered(page,url,seller):
    """Requires verified seller and single unambiguous price in purchase area."""
    parsed=urlparse(url)
    q=urlencode({"magaza":seller})
    target=urlunparse(parsed._replace(query=q,fragment=""))
    if not goto(page,target): return None
    page.wait_for_timeout(700)
    # A ?magaza= query is NOT evidence of the actual seller.
    # Require an actual seller link near the purchase panel in rendered page.
    outcome=page.evaluate("""(seller) => {
      const norm=s=>String(s||'').toLocaleLowerCase('tr').replace(/\s+/g,'').trim();
      const links=[...document.querySelectorAll('a[href*="/magaza/"]')];
      const verified=links.filter(a=>{
        try{return new URL(a.href).pathname.toLocaleLowerCase().replace(/\/$/,'')==='/magaza/'+seller}
        catch(e){return false}
      });
      const text=[...document.querySelectorAll('[class*="price"],[class*="Price"],[data-testid*="price"]')]
        .filter(e=>e.getClientRects().length>0 && e.children.length<=3)
        .map(e=>e.innerText.trim()).filter(t=>t.length>0 && t.length<100);
      return {sellerVisible:verified.length>0, prices:text.slice(0,100),
              title:document.querySelector('h1')?.innerText||''};
    }""",seller)
    if not outcome["sellerVisible"]:
        print("UNVERIFIED_SELLER",seller,url)
        return None
    # Read PIXELS, not DOM price text. The DOM is used only to locate visual regions.
    # Ambiguous, missing or mixed list/sale prices are deliberately rejected.
    selectors='[class*="price"],[class*="Price"],[data-testid*="price"]'
    observed=set()
    try:
        nodes=page.locator(selectors)
        for i in range(min(nodes.count(),35)):
            node=nodes.nth(i)
            try:
                if not node.is_visible(): continue
                bb=node.bounding_box()
                if not bb or bb["width"]<35 or bb["height"]<10 or bb["width"]>650 or bb["height"]>180:
                    continue
                raw=node.screenshot(timeout=3000)
                img=Image.open(BytesIO(raw)).convert("RGB")
                img=ImageOps.autocontrast(img)
                img=ImageEnhance.Contrast(img).enhance(2)
                img=img.resize((img.width*3,img.height*3))
                for config in ("--psm 6","--psm 7"):
                    value=cash(pytesseract.image_to_string(img,config=config,lang="eng"))
                    if value and 10000<=value<=500000000:
                        observed.add(value)
            except Exception:
                continue
    except Exception as exc:
        print("OCR_ERROR",type(exc).__name__)
        return None
    if len(observed)!=1:
        print("OCR_AMBIGUOUS",seller,url,"distinct_prices",len(observed))
        return None
    return {"cents":next(iter(observed)),"title":outcome["title"],"url":target}

def notify(message):
    token=os.getenv("TELEGRAM_BOT_TOKEN")
    chat=os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat: raise RuntimeError("Telegram secrets missing")
    body=json.dumps({"chat_id":chat,"text":message,"disable_web_page_preview":True}).encode()
    req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",
                               data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=25) as response:
        result=json.load(response)
    if not result.get("ok"): raise RuntimeError("Telegram delivery not confirmed")
def main():
    state=load()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(locale="tr-TR",timezone_id="Europe/Istanbul",
                              viewport={"width":1365,"height":900})
        ids=listing(page)
        if not ids:
            print("NO_INVENTORY: no prices checked, no alert sent")
            browser.close()
            return 2
        # A scan spans successive 15-minute executions to limit cloud usage.
        offset=int(state.get("offset",0))%len(ids)
        batch=(ids+ids)[offset:offset+min(BATCH,len(ids))]
        print("BATCH",offset,len(batch))
        delivered=state.setdefault("delivered",{})
        verified=0
        changes=[]
        for cid,url in batch:
            own=offered(page,url,OWN)
            if not own: continue
            for competitor in RIVALS:
                other=offered(page,url,competitor)
                if not other: continue
                verified+=1
                key=cid+":"+competitor
                if other["cents"]>=own["cents"]: continue
                prior=delivered.get(key)
                if prior is not None and other["cents"]>=prior: continue
                changes.append((key,other,own,competitor))
        browser.close()
    print("VERIFIED_COMPARISONS",verified,"CHEAPER_NEW",len(changes))
    # Save the cursor even when there are no verified prices, but never report full coverage.
    state["offset"]=(offset+len(batch))%len(ids)
    state["last_check"]={"at":now(),"inventory_links":len(ids),
                         "catalogs_attempted":len(batch),"verified_comparisons":verified}
    # Sending is deliberately sequential. A delivery failure does not mark anything as delivered.
    for key,other,own,competitor in changes:
        diff=(own["cents"]-other["cents"])/100
        message=(f"N11 rakip fiyat uyarısı\n{other['title']}\n"
                 f"Rakip: {competitor}\n"
                 f"Şaşmazer: {own['cents']/100:,.2f} TL\n"
                 f"Rakip: {other['cents']/100:,.2f} TL\n"
                 f"Fark: {diff:,.2f} TL\n{other['url']}")
        notify(message)
        delivered[key]=other["cents"]
        save(state)
    save(state)
    return 0
if __name__=="__main__":
    sys.exit(main())
