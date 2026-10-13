import asyncio, time, json, re, sys
from playwright.async_api import async_playwright
BASE="https://efeitovendasnachina.com.br"
ADM=("eduleonardo150898@icloud.com","10203040")
R=[]
def ok(cat,nome,passou,detalhe=""):
    R.append({"area":cat,"teste":nome,"ok":bool(passou),"detalhe":str(detalhe)[:160]})
    print(("  ✓ " if passou else "  ✗ ")+f"[{cat}] {nome}"+(f" — {detalhe}" if detalhe and not passou else ""),flush=True)

async def painel(pg):
    errs=[]
    pg.on("pageerror",lambda e: errs.append(str(e)[:120]))
    await pg.goto(f"{BASE}/admin.html?v={int(time.time())}",wait_until="networkidle",timeout=60000)
    await pg.wait_for_timeout(1200)
    await pg.fill("#gtEmail",ADM[0]);await pg.fill("#gtSenha",ADM[1])
    await pg.evaluate("gateEntrar()");await pg.wait_for_timeout(6500)
    ok("painel","login do time",await pg.evaluate("!document.getElementById('app').classList.contains('hidden')"))
    # 1. todas as telas abrem
    for v,lbl in [("geral","Visão geral"),("cot","Cotações"),("ped","Pedidos"),("cat","Catálogo"),
                  ("cfg","Configurações"),("cur","Curadoria"),("sol","Solicitações"),("amo","Amostras"),
                  ("ouro","Fornecedores"),("ver","Verificar fornecedor"),("usr","Usuários")]:
        try:
            await pg.evaluate(f"nav(document.querySelector('.al[data-v=\"{v}\"]'))")
            await pg.wait_for_timeout(900)
            d=await pg.evaluate(f"(()=>{{const e=document.getElementById('v{v[0].upper()+v[1:]}');return e?getComputedStyle(e).display:'sem tela';}})()")
            ok("painel",f"tela {lbl}", d not in ("none","sem tela"), d)
        except Exception as e: ok("painel",f"tela {lbl}",False,e)
    # 2. cotações carregam
    await pg.evaluate("nav(document.querySelector('.al[data-v=\"cot\"]'))");await pg.wait_for_timeout(3000)
    n=await pg.evaluate("typeof COTS!=='undefined'?COTS.length:-1")
    ok("cotações","lista carrega",n>0,f"{n} cotações")
    cards=len(await pg.query_selector_all("#cotList .panel"))
    ok("cotações","cartões aparecem",cards>0,f"{cards} cartões")
    # 3. abrir uma cotação e checar a cadeia de cálculo
    cid=await pg.evaluate("(COTS.find(c=>(c.cotacao_itens||[]).length>0)||{}).id")
    if cid:
        await pg.evaluate(f"abreCot({cid})");await pg.wait_for_timeout(4000)
        ok("cotações","detalhe abre como card",await pg.evaluate("!!document.querySelector('#cotDetail.on')"))
        fin=await pg.eval_on_selector("#cFinal","e=>e.textContent")
        ok("cálculo","preço final preenchido",bool(re.search(r"\d",fin or "")),fin)
        blocos=len(await pg.query_selector_all("#cotDetIn .supfull"))
        itens=len(await pg.query_selector_all("#cotDetIn .ditem")) or await pg.evaluate(f"(COTS.find(c=>c.id=={cid}).cotacao_itens||[]).length")
        ok("cotações","fornecedor em todos os itens",blocos>=itens,f"{blocos} de {itens}")
        # instantânea
        await pg.evaluate("cotacaoInstantanea()");await pg.wait_for_timeout(4000)
        ci=await pg.evaluate("document.getElementById('ciBox')?document.getElementById('ciBox').innerText:''")
        ok("cálculo","cotação instantânea roda",bool(ci),ci[:60])
        m1=re.search(r"Total ao cliente: R\$ ([\d\.,]+)",ci or "")
        fin2=await pg.eval_on_selector("#cFinal","e=>e.textContent")
        if m1: ok("cálculo","instantânea bate com a calculadora",m1.group(1) in (fin2 or ""),f"{m1.group(1)} x {fin2}")
        # modalidade aérea muda o total
        antes=await pg.eval_on_selector("#cFinal","e=>e.textContent")
        await pg.evaluate("document.getElementById('cModal').value='aer';trocaModal();");await pg.wait_for_timeout(1500)
        dep=await pg.eval_on_selector("#cFinal","e=>e.textContent")
        ok("cálculo","trocar para aéreo muda o valor",antes!=dep,f"{antes} → {dep}")
        await pg.evaluate("document.getElementById('cModal').value='mar';trocaModal();");await pg.wait_for_timeout(1200)
        # copiloto: quantidades por m³ coerentes
        await pg.evaluate("abreCopiloto()");await pg.wait_for_timeout(4000)
        await pg.wait_for_timeout(2500)
        txt=await pg.evaluate("(()=>{const m=document.getElementById('cpmodal');if(!m)return '';const t=[...m.querySelectorAll('textarea')].map(x=>x.value).join(' ');return m.innerText+' '+t;})()")
        qs=re.findall(r"([\d\.]+) un \(1 m³",txt.replace(".",""))
        vols=await pg.evaluate(f"""(()=>{{const its=(COTS.find(c=>c.id=={cid}).cotacao_itens||[]);
          return its.map(i=>((window._FBprop||{{}})[i.offer_id]||{{}}).volume_l||null);}})()""")
        ok("copiloto","mensagem em chinês montada","请告知" in txt or "您好" in txt)
        ok("copiloto","volume próprio de cada item carregado",all(v for v in vols),str(vols)[:60])
        if len(qs)>1: ok("copiloto","produtos diferentes → quantidades diferentes",len(set(qs))>1,str(qs)[:60])
        await pg.evaluate("document.getElementById('cpmodal').classList.remove('show')");await pg.wait_for_timeout(600)
        # proposta
        await pg.evaluate("abreProposta()");await pg.wait_for_timeout(5000)
        pp=await pg.evaluate("document.getElementById('ppBox')?document.getElementById('ppBox').innerText:''")
        ok("proposta","proposta pré-montada",bool(pp),pp[:50])
        pu=await pg.evaluate("(()=>{const e=document.querySelector('[id^=pp_p]');return e?e.value:'';})()")
        ok("proposta","preço por unidade preenchido",bool(pu),pu)
        total=re.search(r"Total R\$ ([\d\.,]+)",pp or "")
        if total and pu:
            un=await pg.evaluate(f"(COTS.find(c=>c.id=={cid}).cotacao_itens||[]).reduce((s,i)=>s+i.qtd,0)")
            calc=float(pu.replace(",","."))*un
            tot=float(total.group(1).replace(".","").replace(",","."))
            ok("proposta","preço × quantidade bate com o total",abs(calc-tot)/max(tot,1)<0.05,f"{calc:.2f} x {tot:.2f}")
        await pg.evaluate("document.getElementById('ppBox')?.remove();fechaCotDet()")
    ok("painel","nenhum erro de JavaScript",len(errs)==0,"; ".join(errs[:2]))
    return errs

async def vitrine(pg):
    errs=[];pg.on("pageerror",lambda e: errs.append(str(e)[:120]))
    await pg.goto(f"{BASE}/index.html?v={int(time.time())}",wait_until="networkidle",timeout=60000)
    await pg.wait_for_timeout(5000)
    n=await pg.evaluate("typeof PROD!=='undefined'?PROD.length:-1")
    ok("vitrine","catálogo carrega",n>0,f"{n} produtos na memória")
    cards=len(await pg.query_selector_all(".card"))
    ok("vitrine","produtos aparecem na tela",cards>0,f"{cards} cards")
    cats=len(await pg.query_selector_all("#cats .cat"))
    ok("vitrine","categorias aparecem",cats>0,f"{cats} categorias")
    # adicionar e limite de 2 produtos
    try:
        await pg.evaluate("""(()=>{CART.length=0;const ids=PROD.slice(0,3).map(p=>p.offer_id);ids.forEach(id=>add(id));})()""")
        await pg.wait_for_timeout(800)
        ok("vitrine","limite de 2 produtos por cotação",await pg.evaluate("CART.length<=2"),f"carrinho com {await pg.evaluate('CART.length')}")
    except Exception as e: ok("vitrine","limite de 2 produtos",False,e)
    # preço de fábrica no card
    tem=await pg.evaluate("""(()=>{const t=document.body.innerText;return t.includes('na China')||t.includes('na fábrica');})()""")
    ok("vitrine","mostra preço na fábrica",tem)
    ok("vitrine","nenhum erro de JavaScript",len(errs)==0,"; ".join(errs[:2]))
    return errs

async def outras(pg):
    for url,nome,check in [("/cotacoes.html","quadro de cotações","typeof COTS!=='undefined'"),
                           ("/personalizada.html","cotação personalizada","typeof SRV!=='undefined'&&SRV.length>0")]:
        errs=[];pg.on("pageerror",lambda e: errs.append(str(e)[:120]))
        await pg.goto(f"{BASE}{url}?v={int(time.time())}",wait_until="networkidle",timeout=60000)
        await pg.wait_for_timeout(1200)
        try:
            if await pg.is_visible("#gtEmail"):
                await pg.fill("#gtEmail",ADM[0]);await pg.fill("#gtSenha",ADM[1])
                await pg.evaluate("entrar()")
        except Exception: pass
        await pg.wait_for_timeout(6500)
        try: v=await pg.evaluate(check)
        except Exception as e: v=False
        ok(nome,"abre e carrega dados",v)
        ok(nome,"nenhum erro de JavaScript",len(errs)==0,"; ".join(errs[:2]))

async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",args=["--no-sandbox"])
        ctx=await b.new_context(viewport={"width":1400,"height":900})
        try: await painel(await ctx.new_page())
        except Exception as e: ok("painel","execução do teste",False,e)
        try: await vitrine(await ctx.new_page())
        except Exception as e: ok("vitrine","execução do teste",False,e)
        try: await outras(await ctx.new_page())
        except Exception as e: ok("outras telas","execução do teste",False,e)
        await b.close()
    falhas=[r for r in R if not r["ok"]]
    print(f"\n=== {len(R)-len(falhas)}/{len(R)} testes passaram ===")
    if falhas:
        print("FALHAS:")
        for f in falhas: print(f"  ✗ [{f['area']}] {f['teste']} — {f['detalhe']}")
    json.dump(R,open("resultado_testes.json","w"),ensure_ascii=False,indent=1)
asyncio.run(main())
