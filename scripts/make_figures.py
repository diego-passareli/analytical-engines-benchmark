#!/usr/bin/env python3
"""
make_figures.py — Gera as figuras de dados do artigo a partir dos CSVs do repositório.

Uso (na raiz do repositório):
  python scripts/make_figures.py            # grava em figures/
  python scripts/make_figures.py --out DIR

Figuras: fig_speedup.pdf (speedup mediano e razão de tempo total por suíte),
fig_boxplot.pdf (distribuição dos speedups por consulta), fig_scaling.pdf
(tempo mediano por fator de escala) e fig_polars.pdf (resultado de cada
consulta no Polars, a partir de results/verificacao/). Medianas sobre as
execuções válidas: reps 1-4 nos CSVs sintéticos; reps 2-5 nos dados reais.
Também grava figlog.txt com os valores usados.
"""
import argparse, collections, csv, glob, re, statistics as st, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = str(ROOT / "results") + "/"
FILES = {"tpch1": "tpch_sf1_20260929_014656.csv", "tpch10": "tpch_sf10_20260929_135434.csv",
         "tpch100": "tpch_sf100_20260929_173811.csv", "ds1": "tpcds_sf1_20261022_221128.csv",
         "ds10": "tpcds_sf10_20260930_152117.csv", "cb": "clickbench_20260929_231522.csv",
         "real": "real_20261022_191400.csv"}

def load(key):
    """Mediana por (motor, consulta); descarta pares com alguma execução falha."""
    minrep = 2 if key == "real" else 1
    d = collections.defaultdict(list)
    for r in csv.DictReader(open(R + FILES[key])):
        if int(r["rep"]) >= minrep:
            d[(r["engine"], int(r["query"]))].append(float(r["elapsed_s"]))
    out = collections.defaultdict(dict)
    for (e, q), v in d.items():
        if min(v) > 0:
            out[e][q] = st.median(v)
    return out

def summ(key):
    m = load(key); pg, dk = m["postgresql"], m["duckdb"]
    com = sorted(set(pg) & set(dk)); sp = {q: pg[q] / dk[q] for q in com}
    return dict(med_sp=st.median(sp.values()), tot_ratio=sum(pg.values()) / sum(dk.values()),
                n_com=len(com)), m, sp

ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(ROOT / "figures"))
OUT = ap.parse_args().out.rstrip("/") + "/"; Path(OUT).mkdir(parents=True, exist_ok=True)
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, FuncFormatter
plt.rcParams.update({'font.family':'serif','font.serif':['Liberation Serif','DejaVu Serif'],
 'font.size':7.5,'axes.titlesize':8,'axes.labelsize':7.5,'legend.fontsize':6.8,'xtick.labelsize':7,'ytick.labelsize':7,
 'pdf.fonttype':42,'axes.linewidth':0.6,'lines.linewidth':1.1})
C={'postgresql':'#c0504d','duckdb':'#1f4e79','polars':'#e0a030'}
NAME={'postgresql':'PostgreSQL','duckdb':'DuckDB','polars':'Polars'}
CFG=[('tpch1','TPC-H\nSF=1'),('tpch10','TPC-H\nSF=10'),('tpch100','TPC-H\nSF=100'),('ds1','TPC-DS\nSF=1'),('ds10','TPC-DS\nSF=10'),('cb','Click-\nBench'),('real','Real')]
fmtx=FuncFormatter(lambda v,_: f'{v:g}'+'×')
log=[]
# ---------- Fig 1: median speedup and total-time ratio per suite
med=[];tot=[]
for k,_ in CFG:
    r,m,sp=summ(k)
    med.append(r['med_sp']); tot.append(r['tot_ratio'])
    log.append(f"F1 {k} median={r['med_sp']:.1f} total={r['tot_ratio']:.1f} n_com={r['n_com']}")
fig,ax=plt.subplots(figsize=(3.35,2.0))
x=range(len(CFG)); w=0.38
b1=ax.bar([i-w/2 for i in x],med,w,color=C['duckdb'],label='Median per-query speedup')
b2=ax.bar([i+w/2 for i in x],tot,w,color='#8faadc',label='Total-time ratio')
ax.set_yscale('log'); ax.set_ylim(1,600); ax.yaxis.set_major_formatter(fmtx)
for b,v in list(zip(b1,med))+list(zip(b2,tot)):
    ax.text(b.get_x()+b.get_width()/2,v*1.08,f'{v:.0f}',ha='center',va='bottom',fontsize=5.8)
ax.set_xticks(list(x)); ax.set_xticklabels([l for _,l in CFG])
ax.set_ylabel('PostgreSQL / DuckDB'); ax.legend(frameon=False,loc='upper left',ncol=1)
ax.spines[['top','right']].set_visible(False)
fig.tight_layout(pad=0.3); fig.savefig(OUT+'fig_speedup.pdf')
# ---------- Fig 2: scalability (median per-query time over queries completed at all SFs)
fig,axs=plt.subplots(1,2,figsize=(5.0,2.0),sharey=True)
for ax,(suite,keys,sfs) in zip(axs,[('TPC-H',['tpch1','tpch10','tpch100'],[1,10,100]),('TPC-DS',['ds1','ds10'],[1,10])]):
    M=[load(k) for k in keys]
    for e in ['postgresql','duckdb','polars']:
        qs=set.intersection(*[set(mm[e]) for mm in M])
        y=[st.median(mm[e][q] for q in qs) for mm in M]
        ax.plot(sfs,y,marker='o',ms=3,color=C[e],label=f'{NAME[e]} (n={len(qs)})')
        log.append(f"F2 {suite} {e} n={len(qs)} medians={[round(v,4) for v in y]}")
    ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xticks(sfs); ax.set_xticklabels([f'SF={s}' for s in sfs])
    ax.set_title(suite); ax.spines[['top','right']].set_visible(False)
    ax.legend(frameon=False,fontsize=6.5,loc='lower right'); ax.set_ylim(2e-4,200)
axs[0].set_ylabel('Median query time (s)')
fig.tight_layout(pad=0.3,w_pad=0.6); fig.savefig(OUT+'fig_scaling.pdf')
# ---------- Fig 3: per-query speedup distribution
data=[];labels=[]
for k,l in CFG:
    r,m,sp=summ(k); data.append(list(sp.values())); labels.append(l)
fig,ax=plt.subplots(figsize=(3.35,2.0))
bp=ax.boxplot(data,whis=(0,100),widths=0.55,patch_artist=True,medianprops=dict(color='black',lw=1))
for p in bp['boxes']: p.set(facecolor='#c9d7ec',edgecolor=C['duckdb'],lw=0.7)
for wl in bp['whiskers']+bp['caps']: wl.set(color=C['duckdb'],lw=0.7)
ax.axhline(1,color='grey',lw=0.6,ls='--'); ax.set_yscale('log'); ax.yaxis.set_major_formatter(fmtx)
ax.set_xticks(range(1,len(labels)+1)); ax.set_xticklabels(labels)
ax.set_ylabel('Per-query speedup (PG / DuckDB)'); ax.spines[['top','right']].set_visible(False)
fig.tight_layout(pad=0.3); fig.savefig(OUT+'fig_boxplot.pdf')
for (k,_),d in zip(CFG,data): log.append(f"F3 {k} n={len(d)} min={min(d):.2f} q1={sorted(d)[len(d)//4]:.1f} med={st.median(d):.1f} max={max(d):.0f}")
# ---------- Fig 4: Polars outcome per suite
V=R+'verificacao/'
VF={'tpch1':'equiv_tpch_sf1_2*.csv','tpch10':'equiv_tpch_sf10_ref*.csv','tpch100':'equiv_tpch_sf100_ref*.csv','ds1':'equiv_tpcds_sf1_2*.csv','ds10':'equiv_tpcds_sf10_2*.csv','cb':'equiv_clickbench_refduckdb_2*.csv','real':'equiv_real_2*.csv'}
TOT={'tpch1':22,'tpch10':22,'tpch100':22,'ds1':99,'ds10':99,'cb':43,'real':10}
MEM=re.compile(r'processo encerrado|Cannot allocate|2\^32|Timeout|MemoryError',re.I)
cats=['Correct','Incorrect','Failed: SQL support','Failed: memory/limits','Failed on all engines']
col=['#4f8f4f','#c0504d','#e0a030','#7f7f7f','#d9d9d9']
rows=[]
for k,_ in CFG:
    m=load(k); ok=set(m['polars']); allok=set(m['postgresql'])|set(m['duckdb'])|ok
    ver={int(r['query']):r for r in csv.DictReader(open(glob.glob(V+VF[k])[0])) if r['engine']=='polars'}
    cnt=dict.fromkeys(cats,0)
    for q in range(1,TOT[k]+1):
        if q not in allok: cnt['Failed on all engines']+=1
        elif q in ok:
            st_=ver.get(q,{}).get('status','')
            wrong = st_.startswith('DIFERENTE') and k.startswith('tpch') and q==6
            cnt['Incorrect' if wrong else 'Correct']+=1
        else:
            msg=ver.get(q,{}).get('detail','')
            cnt['Failed: memory/limits' if (MEM.search(msg) or ver.get(q,{}).get('status')!='ERRO') else 'Failed: SQL support']+=1
    rows.append(cnt); log.append(f"F4 {k} {cnt}")
fig,ax=plt.subplots(figsize=(3.35,2.05))
y=list(range(len(CFG)))[::-1]
left=[0]*len(CFG)
for c,cl in zip(cats,col):
    v=[100*r[c]/sum(r.values()) for r in rows]
    ax.barh(y,v,left=left,color=cl,label=c,height=0.62,edgecolor='white',lw=0.4)
    for yi,vi,li,r in zip(y,v,left,rows):
        if vi>=7: ax.text(li+vi/2,yi,str(r[c]),ha='center',va='center',fontsize=5.6,color='white' if cl not in ('#d9d9d9','#e0a030') else 'black')
    left=[a+b for a,b in zip(left,v)]
ax.set_yticks(y); ax.set_yticklabels([l.replace('-\n','').replace('\n',' ') for _,l in CFG]); ax.set_xlim(0,100)
ax.set_xlabel('Share of queries (%)'); ax.spines[['top','right']].set_visible(False)
ax.legend(frameon=False,ncol=2,fontsize=5.6,loc='upper center',bbox_to_anchor=(0.42,-0.24))
fig.tight_layout(pad=0.3); fig.savefig(OUT+'fig_polars.pdf')
open(OUT+'figlog.txt','w').write('\n'.join(log)); print('\n'.join(log))
