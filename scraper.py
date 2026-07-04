#!/usr/bin/env python3
# GARIMPO - robo resumivel. Roda em ciclos, continua de onde parou.
# Fases por rodada: 1) migra imagens pendentes  2) puxa produtos de lojas sem produto
#                   3) descobre novas lojas+produtos varrendo categorias uteis
import os, requests, re, io, time, random
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

URL=os.environ["SB_URL"]; KEY=os.environ["SB_KEY"]
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36","Referer":"https://en.yiwugo.com/"}
RH={"apikey":KEY,"Authorization":f"Bearer {KEY}"}
WH={**RH,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates"}
PH={**RH,"Content-Type":"application/json"}
IMGH={"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"image/jpeg","x-upsert":"true"}
S=requests.Session(); S.headers.update(H)
PUB=f"{URL}/storage/v1/object/public/produtos/"
FX=float(os.environ.get("FX","0.79")); MULT=2
UTEIS=[2,6,7,8,10,14,1,5]  # brinquedo, cabelo, bijuteria, natal, acessorio, tecido, festa, deco
EXCLUI=re.compile(r"buddh|religio|ceramic|porcelain|pottery|glass|painting|photo.?frame|\bvase|furnitur|marble|incense|sculptur",re.I)
RUN_SECONDS=int(os.environ.get("RUN_SECONDS","1500"))
T0=time.time()
def timeleft(): return RUN_SECONDS-(time.time()-T0)

def cn(s): s=re.sub(r'\s+',' ',(s or '')).strip(); return (s[:1].upper()+s[1:])[:78]

def migrate_images(budget):
    t=time.time(); done=0
    def mig(p):
        pid=p["id"];src=p["imgs"][0]
        try:
            r=S.get(src,timeout=12)
            if r.status_code!=200 or len(r.content)<800: return 0
            im=Image.open(io.BytesIO(r.content)).convert("RGB");im.thumbnail((600,600))
            buf=io.BytesIO();im.save(buf,"JPEG",quality=82)
            up=requests.post(f"{URL}/storage/v1/object/produtos/{pid}.jpg",headers=IMGH,data=buf.getvalue(),timeout=25)
            if up.status_code>=300: return 0
            requests.patch(f"{URL}/rest/v1/produtos?id=eq.{pid}",headers=PH,json={"imgs":[PUB+pid+'.jpg']},timeout=15)
            return 1
        except: return 0
    while time.time()-t<budget and timeleft()>60:
        p=requests.get(f"{URL}/rest/v1/produtos?select=id,imgs&imgs->>0=like.*ywgimg*&limit=120",headers=RH,timeout=30).json()
        if not p: break
        ok=0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for f in as_completed([ex.submit(mig,x) for x in p]): ok+=f.result()
        done+=ok
        if ok==0: break
    print(f"[imagens] migradas {done}",flush=True)

def parse_shopdetail(h,shop_code):
    out=[]
    for m in re.finditer(r'/product/detail/(\d+)\.html"[^>]*title="([^"]{5,})"[^<]*</a>\s*<p class="cpprice">\s*CN¥\s*([\d]+)(?:<font>\.?(\d+)</font>)?',h):
        pid,title,i,d=m.groups();rmb=float(f"{i}.{d or 0}")
        pre=h[max(0,m.start()-600):m.start()]
        img=re.search(r'(https?://ywgimg\.yiwugo\.com/product/[^"\'\s]+\.(?:jpg|png))',pre)
        brl=rmb*FX*MULT
        out.append({"id":pid,"name":cn(title),"rmb":rmb,"brl":round(brl,2),"brl_min":round(brl*.9,2),
          "brl_max":round(brl*1.1,2),"imgs":[img.group(1).split("?")[0]] if img else [],
          "subcategoria":"Distrito 1","shop_code":shop_code})
    return out

def products_for_pending(budget):
    t=time.time(); total=0
    sup=requests.get(f"{URL}/rest/v1/fornecedores?select=code,shop_id,map_url&product_count=is.null&order=years.desc&limit=40",headers=RH,timeout=30).json()
    for s in sup:
        if time.time()-t>budget or timeleft()<90: break
        sid=None
        if s.get("map_url"):
            m=re.search(r'shopID=(\d+)',s["map_url"]); sid=m.group(1) if m else None
        if not sid:
            try:
                hh=S.get(f"https://en.yiwugo.com/hu/{s['shop_id']}.html",timeout=15).text
                m=re.search(r'shopID=(\d+)',hh); sid=m.group(1) if m else None
            except: pass
        if not sid:
            requests.patch(f"{URL}/rest/v1/fornecedores?code=eq.{s['code']}",headers=PH,json={"product_count":0},timeout=15); continue
        allp={}
        for pg in range(1,9):
            try: h=S.get(f"https://en.yiwugo.com/shopdetail/1/{sid}_{pg}.html",timeout=15).text
            except: break
            pr=parse_shopdetail(h,s["code"])
            if not pr: break
            for p in pr: allp[p["id"]]=p
            if len(pr)<30: break
            time.sleep(0.15)
        if allp:
            rows=list(allp.values())
            for i in range(0,len(rows),200): requests.post(f"{URL}/rest/v1/produtos",headers=WH,json=rows[i:i+200],timeout=60)
            total+=len(rows)
        requests.patch(f"{URL}/rest/v1/fornecedores?code=eq.{s['code']}",headers=PH,json={"product_count":len(allp)},timeout=15)
        time.sleep(0.2)
    print(f"[produtos] +{total} de {len(sup)} lojas",flush=True)

def discover(budget):
    t=time.time(); newsup=0
    cats=UTEIS[:]; random.shuffle(cats)
    for cat in cats:
        if time.time()-t>budget or timeleft()<90: break
        pg=random.randint(1,80)
        try: h=S.get(f"https://en.yiwugo.com/product/list.html?subIndustry={cat}&cpage={pg}",timeout=20).text
        except: continue
        stubs={}
        for m in re.finditer(r'data-url="https?://ywgimg[^"]*?shop_(\d+)/normal/(\d+)/',h):
            sc=m.group(1); stubs.setdefault(sc,True)
        # cria stubs de fornecedor (sem nome ainda; enriquecimento pega depois)
        rows=[{"code":sc,"distrito":"Distrito 1"} for sc in stubs]
        if rows:
            for i in range(0,len(rows),200): requests.post(f"{URL}/rest/v1/fornecedores",headers=WH,json=rows[i:i+200],timeout=60)
            newsup+=len(rows)
        time.sleep(0.3)
    print(f"[descoberta] +{newsup} lojas novas (stubs)",flush=True)

if __name__=="__main__":
    print(f"== rodada garimpo (orcamento {RUN_SECONDS}s) ==",flush=True)
    migrate_images(RUN_SECONDS*0.4)
    products_for_pending(RUN_SECONDS*0.4)
    discover(RUN_SECONDS*0.2)
    print("== fim da rodada ==",flush=True)
