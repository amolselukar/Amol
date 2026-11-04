#!/usr/bin/env python3
"""LVL ENGINE (standalone paper, NIFTY + SENSEX) — 2026-10-22.
Levels decide direction; ride the level-ratchet; exit on 15m close back through the ratcheted stop.
Runs every ~15 min during market (cron) on COMPLETED 15m candles; stateful + idempotent, so it
fires each entry/exit ONCE to Telegram (V2520 channel, like V2520) and books each trade ONCE.

 LEVELS : daily pivots (P/R1/R2/S1/S2) + PDH/PDL + DYNAMIC structural walls (multi-touch daily
          swings + period extremes) as ride rungs. No ±300 clip.
 ENTRY  : 15m CLOSE beyond a major level (gap vs PDC, or in-session vs prior candle); one trade per
          candle -> outermost broken level, break direction. Chop cap = 2 stop-outs/day.
 EXIT   : spot level-ratchet on 15m closes (stop=last level broken, trails to each new one); exit
          when a 15m close reverts through it, else EOD. ONE rule.
 Fills  : ATM option (nearest listed weekly > day) 1m close.
"""
import sys, csv, os, json, requests
from datetime import datetime, timedelta
import credentials as c
from upstox_kite_shim import UpstoxKite, IST

k=UpstoxKite(c.UPSTOX_ACCESS_TOKEN); BUF=0.001
HERE=os.path.dirname(os.path.abspath(__file__)); STATE=os.path.join(HERE,"state_LVL.json")
DRY = ("test" in sys.argv)
TG_TOK=getattr(c,"TELEGRAM_LVL_BOT_TOKEN",None) or getattr(c,"TELEGRAM_V2520_BOT_TOKEN",None) or c.TELEGRAM_BOT_TOKEN
TG_CID=getattr(c,"TELEGRAM_LVL_CHAT_ID",None) or getattr(c,"TELEGRAM_V2520_CHAT_ID",None) or c.TELEGRAM_CHAT_ID
INSTR={
 "NIFTY":  dict(spot=256265, exch="NFO", name="NIFTY",  step=50,  lot=65, swingbin=40,  round=100, minroom=40,  book=os.path.join(HERE,"LVL_Nifty_TradeBook.csv")),
 "SENSEX": dict(spot=265,    exch="BFO", name="SENSEX", step=100, lot=20, swingbin=120, round=500, minroom=120, book=os.path.join(HERE,"LVL_Sensex_TradeBook.csv")),
}
def tg(msg):
    if DRY: print("[TG]",msg); return
    try: requests.post(f"https://api.telegram.org/bot{TG_TOK}/sendMessage",
        json={"chat_id":TG_CID,"text":msg,"parse_mode":"HTML"},timeout=15)
    except Exception as e: print("TG err",e)
def fetch(tok,frm,to,iv):
    try: return k.historical_data(tok,frm,to,iv)
    except Exception as e: print("fetch err",e); return []
# caches so the per-minute loop is light (heavy calls done once/day)
_INSTR={}; _DAILY={}
def instruments_cached(exch):
    if exch not in _INSTR: _INSTR[exch]=k.instruments(exch)
    return _INSTR[exch]
def daily_cached(spot,day,d0):
    key=(spot,day)
    if key not in _DAILY: _DAILY[key]=fetch(spot,d0-timedelta(days=120),d0+timedelta(days=1),"day")
    return _DAILY[key]
def structural(daily,binpt,N=2,nt=2):
    if len(daily)<10: return []
    hi=[x[2] for x in daily]; lo=[x[3] for x in daily]; sw=[]
    for i in range(N,len(daily)-N):
        if all(hi[i]>=hi[i-j] for j in range(1,N+1)) and all(hi[i]>=hi[i+j] for j in range(1,N+1)): sw.append(hi[i])
        if all(lo[i]<=lo[i-j] for j in range(1,N+1)) and all(lo[i]<=lo[i+j] for j in range(1,N+1)): sw.append(lo[i])
    sw.sort(); out=[]; i=0
    while i<len(sw):
        g=[sw[i]]; j=i+1
        while j<len(sw) and sw[j]-g[0]<=binpt: g.append(sw[j]); j+=1
        if len(g)>=nt: out.append(round(sum(g)/len(g),1))
        i=j
    return out+[round(max(hi),1),round(min(lo),1)]
def opt_map(exch,name,day):
    inst=instruments_cached(exch); opts=[r for r in inst if r.get('name')==name and r.get('instrument_type') in ('CE','PE')]
    exps=sorted({str(r['expiry'])[:10] for r in opts}); fe=next((e for e in exps if e>day), exps[-1] if exps else None)
    return {(int(float(r['strike'])),r['instrument_type']):r['instrument_token'] for r in opts if str(r['expiry'])[:10]==fe}

_LVL={}
def day_levels(key,day):
    """ALL levels for the day (cached once/day): daily pivots + CPR + R3/S3 + PDH/PDL + weekly
    pivots (entry-trigger 'major'); structural walls + round numbers are extra ride/veto 'rungs'."""
    if (key,day) in _LVL: return _LVL[(key,day)]
    cfg=INSTR[key]; d0=datetime.strptime(day,"%Y-%m-%d")
    dr=daily_cached(cfg['spot'],day,d0)
    dd=sorted([(x['date'].strftime('%Y-%m-%d'),x['open'],x['high'],x['low'],x['close']) for x in dr])
    pri=[x for x in dd if x[0]<day]
    if not pri: _LVL[(key,day)]=None; return None
    _,o,H,Lo,C=pri[-1]; P=(H+Lo+C)/3; pdc=C; BC=(H+Lo)/2.0; TC=P+(P-BC)
    named={"PDH":H,"PDL":Lo,"P":P,"TC":TC,"BC":BC,"R1":2*P-Lo,"S1":2*P-H,
           "R2":P+(H-Lo),"S2":P-(H-Lo),"R3":H+2*(P-Lo),"S3":Lo-2*(H-P)}
    cw=d0.isocalendar()[:2]; wk={}
    for dte,_o,h2,l2,c2 in pri:
        w=datetime.strptime(dte,"%Y-%m-%d").isocalendar()[:2]; wk.setdefault(w,[]).append((h2,l2,c2))
    pw=[w for w in sorted(wk) if w<cw]
    if pw:
        g=wk[pw[-1]]; wh=max(x[0] for x in g); wl=min(x[1] for x in g); wc=g[-1][2]; WP=(wh+wl+wc)/3
        named.update({"WPH":wh,"WPL":wl,"WP":WP,"WR1":2*WP-wl,"WS1":2*WP-wh})
    named={n:round(v,1) for n,v in named.items()}
    major=sorted(named.items(),key=lambda x:x[1])
    walls=[round(w,1) for w in structural(pri,cfg['swingbin'])]
    rstep=cfg['round']; rounds=[]; r=int((pdc*0.97)//rstep+1)*rstep
    while r<pdc*1.03: rounds.append(float(r)); r+=rstep
    # round numbers are INFORMATIONAL only (too dense to act as ride/veto walls); trade logic
    # (ratchet/target/ceiling-floor veto) uses pivots + structural walls.
    rungs=sorted(set(named.values()) | set(walls))
    out=dict(major=major,rungs=rungs,named=named,walls=walls,rounds=rounds,pdc=round(pdc,1))
    _LVL[(key,day)]=out; return out

def compute(key,day):
    """Deterministic: returns (closed_trades, open_pos) for the day from completed 15m candles so far."""
    cfg=INSTR[key]; d0=datetime.strptime(day,"%Y-%m-%d")
    L=day_levels(key,day)
    if not L: return [],None
    major=L['major']; rungs=L['rungs']; pdc=L['pdc']
    b15=fetch(cfg['spot'],d0.replace(hour=9,minute=15,tzinfo=IST),d0.replace(hour=15,minute=30,tzinfo=IST),"15minute")
    if not b15: return [],None
    b15=sorted(b15,key=lambda x:x['date'])
    # Only act on COMPLETED 15m candles. The data feed returns the in-progress bar too; its
    # close is NOT final, so using it fires premature entries/exits that flip when the bar
    # actually closes (root cause of the 2026-11-02 double "exit 11:15 then 11:30" messages,
    # and a real-money risk for the live bot that shares this compute). Design is explicitly
    # "15m CLOSE" — so drop any bar whose 15-minute window has not fully elapsed yet.
    _now=datetime.now(IST)
    b15=[x for x in b15 if x['date']+timedelta(minutes=15)<=_now]
    if not b15: return [],None
    Cl=[(x['date'],x['close']) for x in b15]; n=len(Cl)
    omap=opt_map(cfg['exch'],cfg['name'],day); o1,o2=b15[0]['date'],b15[-1]['date']; oc={}
    def opt(st,sd):
        if (st,sd) in oc: return oc[(st,sd)]
        tok=omap.get((st,sd)); ob=fetch(tok,o1,o2,"minute") if tok else []; oc[(st,sd)]=ob; return ob
    pos=None; stops=0; closed=[]
    def mk(p,xt,xo,why):
        th=(p['target'] is not None) and ((p['sgn']>0 and p['stop']>=p['target']) or (p['sgn']<0 and p['stop']<=p['target']))
        # OBSERVE-ONLY give-back metrics (do NOT affect entry/exit/stop):
        #  mfe_o   = peak option close between entry and exit (max favourable premium we saw)
        #  giveback= peak premium minus the premium we actually exited at (pts left on the table)
        #  gap     = distance from broken level to the mapped target (how far the next rung is)
        #  reach_pct=how far spot ran toward that target before we exited (100% = reached target)
        peak_o=max((x['close'] for x in p['ob'] if p['t']<=x['date']<=xt), default=p['eo'])
        gap=round(abs(p['target']-p['lval']),1) if p['target'] is not None else None
        reach_pct=None
        if gap:
            reach=((p['peak_spot']-p['lval'])/(p['target']-p['lval'])) if p['sgn']>0 else ((p['lval']-p['peak_spot'])/(p['lval']-p['target']))
            reach_pct=round(max(0.0,reach)*100)
        return dict(index=key,day=day,entry=p['t'].strftime('%H:%M'),exit=xt.strftime('%H:%M'),side=p['side'],
            strike=p['strike'],level=p['lname'],lval=round(p['lval'],1),target=p['target'],xstop=round(p['stop'],1),target_hit=int(th),
            espot=round(p['espot'],1),eo=round(p['eo'],1),xo=round(xo,1),
            pts=round(xo-p['eo'],1),rupees=round((xo-p['eo'])*cfg['lot']),reason=why,
            mfe_o=round(peak_o,1),giveback=round(peak_o-xo,1),gap=gap,reach_pct=reach_pct)
    for i in range(0,n):
        t,px=Cl[i]; ref=pdc if i==0 else Cl[i-1][1]
        if pos:
            sgn=pos['sgn']
            pos['peak_spot']=max(pos['peak_spot'],px) if sgn>0 else min(pos['peak_spot'],px)  # MFE spot (observe-only)
            for rg in rungs:
                if (sgn>0 and rg>pos['stop'] and px>=rg*(1+BUF)) or (sgn<0 and rg<pos['stop'] and px<=rg*(1-BUF)): pos['stop']=rg
            if (sgn>0 and px<=pos['stop']) or (sgn<0 and px>=pos['stop']):
                b=next((x for x in pos['ob'] if x['date']>=t),None); xo=b['close'] if b else pos['eo']
                if xo<pos['eo']: stops+=1
                closed.append(mk(pos,t,xo,"ratchet")); pos=None; continue
        if pos is None and stops<2:
            up=[(nm,lp) for nm,lp in major if ref<lp and px>=lp*(1+BUF)]
            dn=[(nm,lp) for nm,lp in major if ref>lp and px<=lp*(1-BUF)]
            cand=None; sgn=0
            if up and not dn: cand=max(up,key=lambda x:x[1]); sgn=1
            elif dn and not up: cand=min(dn,key=lambda x:x[1]); sgn=-1
            if cand:
                nm,lp=cand; side='CE' if sgn>0 else 'PE'
                others=[r for r in rungs if (sgn>0 and r>lp) or (sgn<0 and r<lp)]
                tgt=(min(others) if sgn>0 else max(others)) if others else None
                # (ceiling/floor veto removed 10-23 per owner: levels are targets/ratchet rungs,
                #  NOT a pre-entry block; fakes are cut reactively by the stop, per 10-22 design.)
                strike=int(round(px/cfg['step'])*cfg['step'])
                ob=opt(strike,side); b=next((x for x in ob if x['date']>=t),None)
                if b:
                    pos=dict(sgn=sgn,side=side,strike=strike,eo=b['close'],stop=lp,lval=lp,target=tgt,lname=nm,t=t,ob=ob,espot=px,peak_spot=px)
    openp=None
    if pos:
        lasto=next((x['close'] for x in reversed(pos['ob'])),pos['eo'])
        last_t=Cl[-1][0]
        is_eod=(last_t.hour>=15)  # 15:00/15:15 candle = session's last completed 15m bar
        if is_eod:
            # EOD FORCE-CLOSE: book any position still open at the last 15m candle (fill = last option close ~15:30)
            closed.append(mk(pos,last_t,lasto,"eod")); pos=None
        else:
            openp=dict(index=key,day=day,entry=pos['t'].strftime('%H:%M'),side=pos['side'],strike=pos['strike'],
                level=pos['lname'],lval=round(pos['lval'],1),target=pos['target'],stop=round(pos['stop'],1),
                espot=round(pos['espot'],1),eo=round(pos['eo'],1),ltp=round(lasto,1))
    return closed,openp

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(s):
    if not DRY: json.dump(s,open(STATE,"w"))

def rewrite_book(cfg,day,closed):
    rows=[]
    if os.path.exists(cfg['book']):
        rows=[r for r in csv.DictReader(open(cfg['book'])) if r.get('day')!=day]
    cols=["index","day","entry","exit","side","strike","level","lval","target","xstop","target_hit","espot","eo","xo","pts","rupees","reason","mfe_o","giveback","gap","reach_pct"]
    if DRY: return
    with open(cfg['book'],"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k2:r.get(k2,"") for k2 in cols})
        for t in closed: w.writerow(t)

def main():
    day=datetime.now(IST).strftime("%Y-%m-%d")
    st=load_state()
    if st.get("date")!=day: st={"date":day}
    daypnl={}  # per-index LVL P&L for the separate EOD flash
    for key in ("NIFTY","SENSEX"):
        cfg=INSTR[key]; sk=st.setdefault(key,{"entries":[],"exits":[]})
        # broadcast ALL levels once/day so the channel knows the full ladder
        L=day_levels(key,day)
        if L and not sk.get("lvlmsg"):
            nm=L['named']; order=["R3","R2","R1","TC","P","BC","PDH","PDL","S1","S2","S3","WR1","WP","WS1","WPH","WPL"]
            line=" | ".join(f"{z} {nm[z]}" for z in order if z in nm)
            wl=" ".join(str(w) for w in L['walls']) or "-"
            rd=" ".join(str(int(x)) for x in L['rounds']) or "-"
            tg(f"📐 <b>LVL {key} levels {day}</b> (PDC {L['pdc']})\n{line}\nwalls: {wl}\nround#: {rd}")
            sk["lvlmsg"]=True
        closed,openp=compute(key,day)
        # ENTRY alerts (closed + still-open), once each
        ent=[(t['entry'],t['side'],t['strike'],t['level'],t['lval'],t['target'],t['espot']) for t in closed]
        if openp: ent.append((openp['entry'],openp['side'],openp['strike'],openp['level'],openp['lval'],openp['target'],openp['espot']))
        for e,side,strike,lvl,lval,tgt,espot in ent:
            if e not in sk["entries"]:
                # SL + target ALWAYS present at signal instant (user-directed 11-03). SL = the
                # broken level (lval): a 15m close back through it exits; target = next rung.
                tgt_s = f"{tgt}" if tgt is not None else "—"
                tg(f"🟢 <b>LVL {key}</b> — {side} {strike} | break <b>{lvl} {lval}</b> @ {espot} | "
                   f"🎯 target <b>{tgt_s}</b> | 🛑 SL <b>{lval}</b> ({lvl}) (15m) | {e}")
                sk["entries"].append(e)
        # EXIT alerts, once each
        _done_entries=set(kx.split('|')[0] for kx in sk["exits"])
        for t in closed:
            kx=f"{t['entry']}|{t['exit']}"
            if t['entry'] in _done_entries: continue  # already exit-messaged this entry → never double-send (anti-flip safety)
            if kx not in sk["exits"]:
                emoji="🔴" if t['rupees']<0 else "✅"
                th="🎯tgt " if t.get('target_hit') else ""
                tg(f"{emoji} <b>LVL {key}</b> exit {t['side']}{t['strike']} @ {t['xo']} (stop {t['xstop']}) ({t['pts']:+.1f}pt, Rs{t['rupees']:+.0f}) {th}[{t['reason']}] | {t['exit']}")
                sk["exits"].append(kx); _done_entries.add(t['entry'])
        rewrite_book(cfg,day,closed)
        daypnl[key]=dict(n=len(closed),rs=sum(t['rupees'] for t in closed),
                         w=sum(1 for t in closed if t['rupees']>0),
                         openq=1 if openp else 0,trades=closed)
        print(f"[LVL {key}] {day}: {len(closed)} closed, open={'yes' if openp else 'no'}")
    # SEPARATE LVL-ENGINE DAILY P&L FLASH — once/day, at/after EOD when all positions are closed
    now=datetime.now(IST); hm=now.hour*60+now.minute
    noopen=all(v['openq']==0 for v in daypnl.values())
    anytr=any(v['n']>0 for v in daypnl.values())
    if hm>=15*60+16 and noopen and anytr and not st.get("pnlmsg"):
        tot=sum(v['rs'] for v in daypnl.values()); ntot=sum(v['n'] for v in daypnl.values())
        wtot=sum(v['w'] for v in daypnl.values())
        em="✅" if tot>=0 else "🔴"
        # per-trade breakdown: entry -> exit premium, peak premium after entry, and the give-back
        # (peak minus exit = premium handed back by exiting on the level-ratchet). Totals include
        # total give-back in Rs = how much profit the ratchet left on the table across the day.
        plines=[]; ntr=0; tot_gb=0
        for key2,v in daypnl.items():
            if v['n']==0: continue
            plines.append(f"<b>{key2}</b>  {v['n']}tr {v['w']}W  Rs{v['rs']:+.0f}")
            for t in v['trades']:
                ntr+=1; lot=INSTR[t['index']]['lot']; gb_rs=round(t['giveback']*lot); tot_gb+=gb_rs
                th="🎯" if t['target_hit'] else ""
                plines.append(f" Trade-{ntr} {t['side']}{t['strike']} {t['level']}{th} | entry {t['eo']} → exit {t['xo']} | peak {t['mfe_o']} | gaveback {t['giveback']:+.1f}pt (Rs{gb_rs:+.0f}) | Rs{t['rupees']:+.0f}")
        per="\n".join(plines)
        tg(f"💰 <b>LVL ENGINE P&amp;L {day}</b> {em}\n{per}\n<b>TOTAL: {ntr}tr {wtot}W  profit Rs{tot:+.0f} | gaveback Rs{tot_gb:+.0f}</b>")
        st["pnlmsg"]=True
    save_state(st)

def loop():
    """Persistent: poll every 60s during market hours, like V2520. Self-exit after close."""
    import time
    print(f"[LVL] loop start {datetime.now(IST)}")
    while True:
        now=datetime.now(IST); hm=now.hour*60+now.minute
        if hm>=15*60+32:  # 15:32 IST -> done for the day
            print(f"[LVL] market closed, loop exit {now}"); break
        if hm>=9*60+15:   # 09:15 IST
            try: main()
            except Exception as e: print("[LVL] run err",e)
        time.sleep(60)

if __name__=="__main__":
    if "loop" in sys.argv: loop()
    else: main()
