import sys,os,io,contextlib,json,math
R='/Users/wallyhuron/Huronalytics'; os.chdir(R); sys.path[:0]=[R,R+'/scripts/research/projection',R+'/scripts/research/era',R+'/scripts/research/hitter']
import numpy as np
import hpwar_total_backtest as B, pt_backtest as PT
def ip(x):
    x=float(x or 0); return int(x)+(x-int(x))*10/3
def solve(s,t,b):
    lo,hi=-500.,500.
    for _ in range(60):
        a=(lo+hi)/2
        if np.clip(a+b*s,0,None).sum()>t: hi=a
        else: lo=a
    return (lo+hi)/2
def curve(s,y,edges):
    xs,ys=[],[]
    for lo,hi in zip(edges[:-1],edges[1:]):
        m=(s>lo)&(s<=hi)
        if m.sum()>=20: xs.append(s[m].mean()); ys.append(y[m].mean())
    ys=np.maximum.accumulate(ys); return np.array(xs),ys
TS=[2018,2019,2021,2022,2023,2024,2025]
for side,key,conv,name,fl,E_list in (('bat','PA',float,'hit',5.,{'5 bins':[5,100,300,500,600,800],'8 bins':[5,50,100,200,300,400,500,600,800],'11 bins':[5,25,50,100,150,200,300,400,500,575,650,800]}),('pit','IP',ip,'pit',2.,{'5 bins':[2,20,50,100,150,300],'8 bins':[2,10,20,35,50,75,100,150,300],'11 bins':[2,10,20,35,50,65,80,100,125,150,175,300]})):
    with contextlib.redirect_stdout(io.StringIO()): pt=B.pt_heldout(name)
    tab={}
    for T in TS:
        st=B.fg('steamer',T,side); ac=B.fg('actual',T,side)
        if not st or not ac: continue
        ids=[p for p in pt[T] if p in st and st[p].get(key)]
        tab[T]=(np.array([pt[T][p] for p in ids]),np.array([float(st[p][key]) for p in ids]),np.array([conv((ac.get(p) or {}).get(key) or 0) for p in ids]))
    Ts=sorted(tab)
    own=[math.sqrt(np.mean((tab[T][0]-tab[T][2])**2)) for T in Ts]
    lin=[]
    for T in Ts:
        o,s,y=tab[T]; f=s<=fl; a=solve(s[~f],o[~f].sum(),.8); pr=o.copy(); pr[~f]=np.clip(a+.8*s[~f],0,None); lin.append(math.sqrt(np.mean((pr-y)**2)))
    print(f'\n{side}: RMSE ours {np.mean(own):.2f}, linear+floor {np.mean(lin):.2f}')
    for nm,edges in E_list.items():
        rm=[];bias=[];top=[]
        for T in Ts:
            o,s,y=tab[T]; trS=np.concatenate([tab[t][1] for t in Ts if t!=T]); trY=np.concatenate([tab[t][2] for t in Ts if t!=T]); xs,ys=curve(trS,trY,edges)
            f=s<=fl; pr=o.copy(); pr[~f]=np.interp(s[~f],xs,ys); rm.append(math.sqrt(np.mean((pr-y)**2))); bias.append(pr.sum()/y.sum()); hi=s>=np.percentile(s,97); top.append((pr[hi].mean(),y[hi].mean()))
        print(f"  {nm}: held-out RMSE {np.mean(rm):.2f}, beats ours {sum(a<b for a,b in zip(rm,own))}/{len(Ts)}, beats linear {sum(a<b for a,b in zip(rm,lin))}/{len(Ts)}, pool sum / actual {np.mean(bias):.3f}, top 3pct pred/actual {np.mean([a for a,_ in top]):.0f}/{np.mean([b for _,b in top]):.0f}")
    edges=E_list['8 bins']; S=np.concatenate([tab[t][1] for t in Ts]); Y=np.concatenate([tab[t][2] for t in Ts]); xs,ys=curve(S,Y,edges); print('  curve x',xs.round(1).tolist(),'y',np.round(ys,1).tolist())
    st={int(r['xMLBAMID']):float(r.get(key) or 0) for r in json.load(open(f'data/_proj/fg/steamer_2027_{side}.json')) if r.get('xMLBAMID')}
    with contextlib.redirect_stdout(io.StringIO()): P=PT.project(name,2026)
    c=[p for p in P if p in st and st[p]>fl]; s=np.array([st[p] for p in c]); pr=np.interp(s,xs,ys); o=np.array([P[p] for p in c]); fsum=sum(P[p] for p in P if p not in set(c))
    print(f'  NOV: covered {len(c)}, Steamer {s.sum():.0f}, curve {pr.sum():.0f}, ours on them {o.sum():.0f}, floor/uncovered ours {fsum:.0f}; full pool curve+model {pr.sum()+fsum:.0f} vs ours {sum(P.values()):.0f}; history actual on pool mean {np.mean([tab[t][2].sum() for t in Ts if t>=2022]):.0f}')
    for pid,nm in ((677951,'Witt'),(691718,'PCA'),(669373,'Skubal'),(694973,'Skenes')):
        if pid in st and pid in P: print('   ',nm,'steamer',round(st[pid]),'curve',round(float(np.interp(st[pid],xs,ys))),'ours',round(P[pid]))
