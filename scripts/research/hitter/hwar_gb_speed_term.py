"""hwar_gb_speed_term.py: ground-ball speed term on xhb with paired error bars, plus the catcher split in the wins model (2026-11-04). Needs data/_war_honest/speed_YEAR.pkl from hwar_speed_catch_tests.py. Log: data/_war_honest/gb_term.log."""
import sys,os,pickle,io,contextlib,json
R=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); os.chdir(R)
sys.path[:0]=[R,R+'/scripts/research/hitter',R+'/scripts/research/era',R+'/scripts/research/projection']
import numpy as np,pandas as pd
import hwar_component_scale as C, hwar_forecast_honest as HH, hwar_speed_catch_tests as T
SE=C.SEASONS; OUT='data/_war_honest'
S={y:pickle.load(open(f'{OUT}/speed_{y}.pkl','rb')) for y in SE}; SP={y:T.sprint(y) for y in SE}
sl={};lg={}
for y in SE:
    f=S[y]['full']; s=pd.Series(SP[y]).reindex(f.index); m=s.notna()&(f['n']>=50); lg[y]=float(np.average(s[m],weights=f.loc[m,'n']))
    n=f.loc[m,'gb_n']; rr=f.loc[m,'gb_r']-n*(f.loc[m,'gb_r'].sum()/n.sum()); x=s[m]-lg[y]; sl[y]=float((x*rr).sum()/(n*x*x).sum())
lo={y:np.mean([sl[o] for o in SE if o!=y]) for y in SE}
def term(y,sc,k):
    f=S[y][sc]; x=(pd.Series(SP[y]).reindex(f.index)-lg[y]).fillna(0.0); return k*x*lo[y]*f['gb_n']/f['n']
np_=HH.next_pool(150); rp=HH.ros_pool(); ny,nw=HH.yw(np_); ry,rw=HH.yw(rp)
base_n={y:HH.FULL[y].loc[np_[y]['ids'],'xhb'].values for y in np_}; base_r={y:HH.H1[y].loc[rp[y]['ids'],'xhb'].values for y in rp}
idx={(r['y'],r['club']):r for r in C.ROWS}
print('GB-only LOSO slope per GB per ft/s',{y:round(v,4) for y,v in lo.items()})
for k in (.5,1,1.5,2,3):
    a={y:base_n[y]+term(y,'full',k).reindex(np_[y]['ids']).fillna(0).values for y in np_}; b={y:base_r[y]+term(y,'h1',k).reindex(rp[y]['ids']).fillna(0).values for y in rp}
    HH.show(f'k {k} next',HH.paired(a,base_n,ny,nw),4,('gb','xhb')); HH.show(f'k {k} ros',HH.paired(b,base_r,ry,rw),5,('gb','xhb'))
    bias=[]; cal=[]
    for r in C.ROWS: r['bk']=0.0
    for y in SE:
        A=HH.FULL[y].copy(); A['xhb']=A['xhb']+term(y,'full',k).reindex(A.index).fillna(0); L=float(np.average(A['xhb'],weights=A['n'])); b_,_=C.shares(y)
        for pid,q in A.iterrows():
            for c,v in C.spread(str(pid),(q['xhb']-L)*q['n']/HH.SCALE[y],b_).items():
                if (y,c) in idx: idx[(y,c)]['bk']+=v
        g=A[A['n']>=300]; s=pd.Series(SP[y]).reindex(g.index); e=(g['raw_woba']-g['raw_woba'].mean())-(g['xhb']-g['xhb'].mean()); bias.append(float(e[s>=s.quantile(2/3)].mean()-e[s<=s.quantile(1/3)].mean()))
    with contextlib.redirect_stdout(io.StringIO()): f=C.fit('rs',['bk','bsr','park'])
    print(f"   desc: fast minus slow bias {np.mean(bias):+.4f} ({' '.join(f'{v:+.3f}' for v in bias)}) club bsr {f['slopes']['bsr']['b']:.2f} rmse {f['rmse']:.1f}")
t=term(2026,'full',1); a=HH.FULL[2026]; g=a[a['n']>=400].index; runs=t.reindex(g)*a.loc[g,'n']/HH.SCALE[2026]; print('2026 400+ PA k=1 runs sd',round(runs.std(),2),'min',round(runs.min(),1),'max',round(runs.max(),1))
# catcher size
F=C.FRV[2026]; c=sorted([(v.get('framing') or 0,v['name']) for v in F.values() if v.get('catching') is not None]); print('framing 2026 top',c[-4:],'bottom',c[:3])
print('non-catcher sum check, wins model with split')
with contextlib.redirect_stdout(io.StringIO()): w=C.fit('wab',['bat','bsr','nonc','catch','praa','park'],scale={'bat','bsr','nonc','catch','praa','park'})
print({k:(round(v['b'],2),round(v['se'],2)) for k,v in w['slopes'].items()},'rmse',round(w['rmse'],2))
print('pitcher RAA club sd',round(np.std([r['praa'] for r in C.ROWS]),1),'catch club sd',round(np.std([r['catch'] for r in C.ROWS]),1),'nonc club sd',round(np.std([r['nonc'] for r in C.ROWS]),1))
