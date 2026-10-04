import json,csv,io,difflib,statistics as st,math
import pandas as pd
JJM="""Ahmednagar,799703,706393,88.33
Akola,248458,216687,87.21
Amravati,434115,426524,98.25
Beed,472732,358008,75.73
Bhandara,256684,217372,84.68
Buldhana,448293,416427,92.89
Chandrapur,395251,356364,90.16
Chhatrapati Sambhajinagar,488084,412750,84.57
Dharashiv,288559,247988,85.94
Dhule,304263,302717,99.49
Gadchiroli,242119,221452,91.46
Gondia,307730,249098,80.95
Hingoli,214938,172275,80.15
Jalgaon,690913,690329,99.92
Jalna,300063,299804,99.91
Kolhapur,684162,679268,99.28
Latur,374582,363657,97.08
Nagpur,376864,366348,97.21
Nanded,536765,481155,89.64
Nandurbar,362721,199219,54.92
Nashik,718369,663660,92.38
Palghar,452043,308468,68.24
Parbhani,299744,245043,81.75
Pune,895102,752699,84.09
Raigad,548620,485541,88.5
Ratnagiri,448354,384935,85.86
Sangli,459048,401570,87.48
Satara,618518,570034,92.16
Sindhudurg,193373,158446,81.94
Solapur,577245,576668,99.9
Thane,261271,188897,72.3
Wardha,238942,234757,98.25
Washim,220115,195892,89
Yavatmal,522884,409226,78.26"""
PM="""Ahmednagar,3101,7689,8572
Akola,2827,5072,8772
Amravati,7552,8922,14442
Aurangabad,1336,2088,5177
Beed,956,1955,3931
Bhandara,3411,7648,16115
Buldhana,1675,2032,4082
Chandrapur,1486,3867,6608
Dhule,6666,12068,6270
Gadchiroli,1625,3941,4118
Gondia,2619,44740,10599
Hingoli,1056,1409,1582
Jalgaon,4737,6005,11992
Jalna,450,993,2746
Kolhapur,968,1924,2085
Latur,686,676,1193
Nagpur,1840,4282,8329
Nanded,2993,4172,9148
Nandurbar,19927,23661,10601
Nashik,9622,14083,9385
Osmanabad,311,607,751
Palghar,2993,6174,2141
Parbhani,448,577,1430
Pune,971,1767,1824
Raigad,726,1073,985
Ratnagiri,588,863,1526
Sangli,1711,1593,2514
Satara,482,1233,1362
Sindhudurg,543,473,673
Solapur,2851,3371,7595
Thane,254,1193,526
Wardha,1018,1776,3090
Washim,538,623,1321
Yavatmal,3310,3206,7537"""
jjm=[l.split(',') for l in JJM.splitlines()]; pm=[l.split(',') for l in PM.splitlines()]
canon=[r[0] for r in jjm]+['Mumbai','Mumbai Suburban']
RENAME={'aurangabad':'Chhatrapati Sambhajinagar','osmanabad':'Dharashiv','ahilyanagar':'Ahmednagar','garhchiroli':'Gadchiroli','raigarh':'Raigad','bid':'Beed'}
def resolve(name):
    n=name.strip()
    for c in canon:
        if c.lower()==n.lower(): return c,'exact',1.0
    if n.lower() in RENAME: 
        c=RENAME[n.lower()]; return c,('rename' if n.lower() in('aurangabad','osmanabad','ahilyanagar') else 'alias'),round(difflib.SequenceMatcher(None,n.lower(),c.lower()).ratio(),2)
    best=max(canon,key=lambda c:difflib.SequenceMatcher(None,n.lower(),c.lower()).ratio())
    s=difflib.SequenceMatcher(None,n.lower(),best.lower()).ratio()
    return (best,'fuzzy',round(s,2)) if s>=0.75 else (None,'unresolved',round(s,2))
D={c:{'name':c,'src':{}} for c in canon}
for i,r in enumerate(jjm):
    c,m,s=resolve(r[0]); D[c]['src']['jjm']={'raw':r[0],'method':m,'score':s,'row':i+2}
    D[c].update(hh=int(r[1]),tap=int(r[2]),jjm_pct=float(r[3]))
for i,r in enumerate(pm):
    c,m,s=resolve(r[0]); D[c]['src']['pmay']={'raw':r[0],'method':m,'score':s,'row':i+2}
    D[c].update(pm=[int(x) for x in r[1:]])
nf=pd.read_csv('NFHS-5/NFHS-5-Districts.csv'); nf['row']=nf.index+2
nf=nf[nf.State.str.strip().str.lower()=='maharashtra']
IND={'7.':'electricity','8.':'water','9.':'sanitation','10.':'cleanfuel','12.':'insurance'}
for _,r in nf.iterrows():
    for k,v in IND.items():
        if r.Indicator.startswith(k):
            c,m,s=resolve(r.District); assert c,r.District
            D[c]['src']['nfhs']={'raw':r.District,'method':m,'score':s,'row':int(r.row)}
            D[c].setdefault('nfhs',{})[v]=float(r['NFHS-5']); D[c].setdefault('nfhs_rows',{})[v]=int(r.row)
# map
g=json.load(open('g_MAHARASHTRA_DISTRICTS.geojson'))
print('sample coord',g['features'][0]['geometry']['coordinates'][0][0][:2] if g['features'][0]['geometry']['type']=='Polygon' else '')
def dp(pts,eps):
    if len(pts)<3: return pts
    keep=[False]*len(pts); keep[0]=keep[-1]=True; stack=[(0,len(pts)-1)]
    while stack:
        a,b=stack.pop(); ax,ay=pts[a]; bx,by=pts[b]; dx,dy=bx-ax,by-ay; L=math.hypot(dx,dy); md=0;mi=-1
        for i in range(a+1,b):
            d=math.hypot(pts[i][0]-ax,pts[i][1]-ay) if L<1e-9 else abs(dy*(pts[i][0]-ax)-dx*(pts[i][1]-ay))/L
            if d>md: md,mi=d,i
        if md>eps: keep[mi]=True; stack+= [(a,mi),(mi,b)]
    return [p for p,k in zip(pts,keep) if k]
allp=[]
feats=[]
for f in g['features']:
    geo=f['geometry']; polys=[geo['coordinates']] if geo['type']=='Polygon' else geo['coordinates']
    rings=[p[0] for p in polys]; rings=[r for r in rings if len(r)>30] or rings[:1]
    feats.append((f['properties'],rings)); 
    for r in rings: allp+=r
xs=[p[0] for p in allp]; ys=[p[1] for p in allp]; x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
k=math.cos(math.radians((y0+y1)/2)); W=640; sc=W/((x1-x0)*k); H=(y1-y0)*sc
unres=[]
for props,rings in feats:
    c,m,s=resolve(props['dtname'].title())
    if not c: unres.append(props['dtname']); continue
    path='';cx=cy=n=0
    for r in rings:
        pts=[((p[0]-x0)*k*sc,(y1-p[1])*sc) for p in r]; pts=dp(pts,0.6)
        path+='M'+'L'.join(f'{x:.1f},{y:.1f}' for x,y in pts)+'Z'
        if len(pts)>n: n=len(pts); cx=(min(p[0] for p in pts)+max(p[0] for p in pts))/2; cy=(min(p[1] for p in pts)+max(p[1] for p in pts))/2
    D[c]['path']=path; D[c]['c']=[round(cx,1),round(cy,1)]; D[c]['lgd']=props.get('Dist_LGD')
    D[c]['src']['lgd']={'raw':props['dtname'],'method':m,'score':s}
print('unresolved geo',unres,'nopath',[c for c in canon if 'path' not in D[c]])
for d in D.values():
    if 'hh' in d and 'pm' in d:
        d['uncon']=d['hh']-d['tap']; d['pm_total']=sum(d['pm']); d['pm_per1000']=round(d['pm_total']/d['hh']*1000,1)
R=[d for d in D.values() if 'jjm_pct' in d]
mu=st.mean(x['jjm_pct'] for x in R); sd=st.pstdev(x['jjm_pct'] for x in R)
state_pct=round(sum(x['tap'] for x in R)/sum(x['hh'] for x in R)*100,2)
med=round(st.median(x['jjm_pct'] for x in R),2); p66=sorted(x['pm_per1000'] for x in R)[int(len(R)*2/3)]
smu=st.mean(x['nfhs']['sanitation'] for x in R); ssd=st.pstdev(x['nfhs']['sanitation'] for x in R)
F=[]
SJ='Jal Jeevan Mission, Lok Sabha Q.1425 (as on 10 Feb 2025)'; SP='PMAY-Gramin, Lok Sabha Q.2078 (2019-20 to 2021-22)'; SN='NFHS-5 district fact sheets (2019-21)'
def ev(label,val,src,row): return {'label':label,'value':val,'source':src,'row':row}
for d in sorted(R,key=lambda x:x['jjm_pct']):
    z=(d['jjm_pct']-mu)/sd
    if z<-1:
        F.append({'type':'Coverage gap','sev':'high' if z<-2 else 'medium','district':d['name'],
          'title':f"{d['name']}: tap water coverage {d['jjm_pct']}% against a state figure of {state_pct}%",
          'detail':f"{d['uncon']:,} rural households still have no tap connection.",
          'rule':f"District coverage more than 1 standard deviation below the district mean (mean {mu:.1f}%, SD {sd:.1f}; z = {z:.2f}).",
          'evidence':[ev('Rural households',d['hh'],SJ,d['src']['jjm']['row']),ev('Tap connections',d['tap'],SJ,d['src']['jjm']['row']),ev('Coverage %',d['jjm_pct'],SJ,d['src']['jjm']['row'])]})
for d in sorted(R,key=lambda x:-x['pm_per1000']):
    if d['pm_per1000']>=p66 and d['jjm_pct']<med:
        F.append({'type':'Cross-ministry gap','sev':'high' if d['jjm_pct']<mu-sd else 'medium','district':d['name'],
          'title':f"{d['name']}: heavy rural housing construction, lagging water connections",
          'detail':f"{d['pm_total']:,} PMAY-G houses built in three years ({d['pm_per1000']} per 1,000 rural households), yet tap coverage is {d['jjm_pct']}%. Two ministries are working the same households without visible convergence.",
          'rule':f"PMAY-G houses per 1,000 rural households in the top third (at least {p66}) and JJM coverage below the district median ({med}%). Denominator is JJM's rural household count, joined on the resolved district.",
          'evidence':[ev('PMAY-G houses 2019-22',d['pm_total'],SP,d['src']['pmay']['row']),ev('Rural households',d['hh'],SJ,d['src']['jjm']['row']),ev('JJM coverage %',d['jjm_pct'],SJ,d['src']['jjm']['row'])]})
for d in R:
    for i,v in enumerate(d['pm']):
        oth=[x for j,x in enumerate(d['pm']) if j!=i]
        if v>4*max(oth):
            yr=['2019-20','2020-21','2021-22'][i]; d['pm_flag']=yr
            F.append({'type':'Data anomaly','sev':'medium','district':d['name'],
              'title':f"{d['name']}: PMAY-G figure for {yr} is {v/max(oth):.1f} times its next highest year",
              'detail':f"{v:,} houses reported in {yr} against {oth[0]:,} and {oth[1]:,} in the other two years. This is either a one-off sanction surge or an error in the source table. Verify against the source before acting on it.",
              'rule':"Any year more than 4 times the district's next highest year is flagged for verification.",
              'evidence':[ev(y,x,SP,d['src']['pmay']['row']) for y,x in zip(['2019-20','2020-21','2021-22'],d['pm'])]})
for d in sorted(R,key=lambda x:x['nfhs']['sanitation']):
    z=(d['nfhs']['sanitation']-smu)/ssd
    if z<-1:
        F.append({'type':'Outcome gap','sev':'medium','district':d['name'],
          'title':f"{d['name']}: {d['nfhs']['sanitation']}% of people live in households with improved sanitation",
          'detail':f"District mean is {smu:.1f}%. The district received {d['pm_total']:,} PMAY-G houses in 2019-22, which are meant to include a toilet through convergence.",
          'rule':f"NFHS-5 improved sanitation more than 1 standard deviation below the district mean (z = {z:.2f}).",
          'evidence':[ev('Improved sanitation %',d['nfhs']['sanitation'],SN,d['nfhs_rows']['sanitation']),ev('PMAY-G houses 2019-22',d['pm_total'],SP,d['src']['pmay']['row'])]})
for d in sorted(R,key=lambda x:x['jjm_pct']):
    if d['nfhs']['water']>=90 and d['jjm_pct']<80:
        F.append({'type':'Indicator mismatch','sev':'low','district':d['name'],
          'title':f"{d['name']}: {d['nfhs']['water']}% have an improved water source, {d['jjm_pct']}% have a tap",
          'detail':"The two ministries measure different things. NFHS counts handpumps and protected wells as improved sources; JJM counts only household taps. Reading either number alone misstates the district. The periods also differ (2019-21 against 2025).",
          'rule':"NFHS-5 improved drinking-water source at least 90% while JJM tap coverage is below 80%.",
          'evidence':[ev('Improved water source %',d['nfhs']['water'],SN,d['nfhs_rows']['water']),ev('JJM coverage %',d['jjm_pct'],SJ,d['src']['jjm']['row'])]})
top=sorted(R,key=lambda x:-(x['pm_total']*(100-x['jjm_pct'])/100))[:5]
F.append({'type':'Scheme overlap','sev':'medium','district':None,
  'title':"PMAY-G and Jal Jeevan Mission target the same rural households in all 34 districts",
  'detail':"Both schemes are run by different ministries and reported separately. Ranking districts by houses built multiplied by the share of households without a tap gives the places where joint planning would reach the most people: "+", ".join(x['name'] for x in top)+".",
  'rule':"Overlap = both schemes report activity in the district and share the beneficiary unit (rural household). Priority = PMAY-G houses 2019-22 x (1 - JJM coverage).",
  'evidence':[ev(x['name']+': houses x unconnected share',round(x['pm_total']*(100-x['jjm_pct'])/100),SP+' and '+SJ,x['src']['jjm']['row']) for x in top]})
order={'high':0,'medium':1,'low':2}; F.sort(key=lambda f:order[f['sev']])
for i,f in enumerate(F): f['id']=i
out={'districts':list(D.values()),'findings':F,'state':{'jjm_pct':state_pct,'mean':round(mu,1),'sd':round(sd,1),'hh':sum(x['hh'] for x in R),'tap':sum(x['tap'] for x in R),'pm_total':sum(x['pm_total'] for x in R)},'map':{'w':W,'h':round(H)}}
json.dump(out,open('data.json','w'),separators=(',',':'))
print(len(json.dumps(out)), 'findings',len(F)); 
from collections import Counter; print(Counter(f['type'] for f in F)); 
for f in F: print(f['sev'],'|',f['title'])
print(sum(1 for d in D.values() for s in d['src'].values() if s['method']!='exact'),'non-exact matches')
print([(d['name'],{k:v['raw'] for k,v in d['src'].items() if v['method']!='exact'}) for d in D.values() if any(v['method']!='exact' for v in d['src'].values())])
