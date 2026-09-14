"""Render static analytical previews from the same SQL marts. These are not Desktop screenshots."""
from pathlib import Path
import sqlite3
import textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.colors import LinearSegmentedColormap,TwoSlopeNorm
from matplotlib.ticker import FuncFormatter,PercentFormatter
import numpy as np
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'charts';OUT.mkdir(exist_ok=True)
NAVY='#142D3D';TEAL='#007F7B';AMBER='#B66A19';MUTED='#536773';BG='#F2F5F5'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'text.color':NAVY,'axes.labelcolor':MUTED,'xtick.color':MUTED,'ytick.color':MUTED,'axes.edgecolor':'#DAE3E5','axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold'})
db=sqlite3.connect(ROOT/'data/transit.sqlite');db.row_factory=sqlite3.Row
month=db.execute('SELECT MAX(month) FROM volumes').fetchone()[0]
from datetime import datetime
month_name=datetime.strptime(month,'%Y%m').strftime('%B %Y')
days=dict(db.execute('SELECT day_type,days FROM calendar_days WHERE month=?',(month,)).fetchall())
wd=days['WEEKDAY'];we=days['WEEKENDS/HOLIDAY']
if not wd or not we:raise SystemExit('Verify the holiday calendar for '+month+' before rendering daily-normalized previews.')
topology=db.execute("SELECT MAX(collected_at) FROM runs WHERE dataset='BusRoutes' AND status='ok'").fetchone()[0]

def canvas(title,subtitle,period=None):
    fig=plt.figure(figsize=(16,10),facecolor=BG)
    fig.add_artist(FancyBboxPatch((.025,.855),.95,.12,boxstyle='round,pad=0.008,rounding_size=0.012',transform=fig.transFigure,facecolor=NAVY,edgecolor='none',zorder=0))
    fig.text(.045,.95,'TRANSIT / INTELLIGENCE    •    SINGAPORE',color='#9CC7CA',fontsize=11,weight='bold')
    fig.text(.045,.9,title,color='white',fontsize=27,weight='bold')
    fig.text(.045,.817,subtitle,fontsize=11,color=MUTED)
    fig.text(.045,.022,f'{period or month_name} • LTA DataMall • SGT • Static analytical preview; native Power BI layout may differ.',fontsize=9,color=MUTED)
    return fig

def panel(fig,rect,title,sub=None):
    ax=fig.add_axes(rect,facecolor='white')
    ax.set_title(title,loc='left',fontsize=13,pad=24 if sub else 14)
    if sub:ax.text(0,1.02,sub,transform=ax.transAxes,color=MUTED,fontsize=9)
    ax.grid(axis='y',color='#E5EBEE',zorder=0);ax.set_axisbelow(True)
    return ax

def save(fig,name):
    import io
    buffer=io.BytesIO();fig.savefig(buffer,format='png',dpi=130,facecolor=BG)
    data=buffer.getvalue();temp=OUT/(name+'.tmp');temp.write_bytes(data);temp.replace(OUT/name);plt.close(fig)

fig=canvas('The city changes character through the day.',f'{month_name} | {wd} weekdays + {we} weekend/holiday days | Profiles reveal purpose-like patterns; trip purpose is not observed.')
rows=db.execute("SELECT mode,SUM(tap_in)*1.0/(SELECT days FROM calendar_days WHERE month=volumes.month AND day_type=volumes.day_type) n FROM volumes WHERE month=? AND day_type='WEEKDAY' GROUP BY mode",(month,)).fetchall()
for i,r in enumerate(rows):
    fig.text(.05+i*.27,.756,f'{r["n"]/1e6:.2f}M',fontsize=29,weight='bold',color=TEAL)
    fig.text(.05+i*.27,.724,f'{r["mode"]} entries / weekday',fontsize=11,color=MUTED)
stadium=db.execute("SELECT weekend_uplift FROM v_node_metrics WHERE month=? AND node_name='Stadium'",(month,)).fetchone()
fig.text(.64,.756,f'{stadium[0]:.2f}×' if stadium and stadium[0] is not None else 'Unavailable',fontsize=29,weight='bold',color=AMBER)
fig.text(.64,.724,'Stadium weekend / weekday daily entries',fontsize=11,color=MUTED)
ax=panel(fig,[.07,.40,.39,.245],'The weekday rhythm','Rail entries and exits per day')
rs=db.execute("SELECT hour,SUM(tap_in)*1.0/(SELECT days FROM calendar_days WHERE month=volumes.month AND day_type=volumes.day_type) a,SUM(tap_out)*1.0/(SELECT days FROM calendar_days WHERE month=volumes.month AND day_type=volumes.day_type) b FROM volumes WHERE mode='Train' AND month=? AND day_type='WEEKDAY' AND hour IS NOT NULL GROUP BY hour",(month,)).fetchall()
ax.plot([r['hour'] for r in rs],[r['a'] for r in rs],color=TEAL,lw=2.5,label='Entries')
ax.plot([r['hour'] for r in rs],[r['b'] for r in rs],color=AMBER,lw=2.5,label='Exits')
ax.set_xticks([0,4,8,12,16,20,23]);ax.set_xlabel('Hour of day · Singapore time');ax.yaxis.set_major_formatter(FuncFormatter(lambda x,_:f'{x/1000:.0f}k'));ax.legend(frameon=False,loc='upper left')
ax=panel(fig,[.59,.40,.35,.245],'Where weekends matter more','Rail nodes with ≥1,000 weekday entries/day')
rs=db.execute("SELECT node_name,weekend_uplift FROM v_node_metrics WHERE mode='Train' AND month=? AND weekday_daily>=1000 ORDER BY weekend_uplift DESC LIMIT 5",(month,)).fetchall()
ax.barh([r[0] for r in rs][::-1],[r[1] for r in rs][::-1],color=AMBER,height=.55);ax.axvline(1,color=MUTED,linestyle='--',lw=1);ax.set_xlabel('Weekend/holiday daily entries ÷ weekday daily entries');ax.grid(axis='x',color='#E5EBEE');ax.grid(axis='y',visible=False)
ax=panel(fig,[.14,.10,.80,.20],'Morning exporters become evening receivers','Selected rail examples · net flow (entries − exits) / (entries + exits)')
rs=db.execute("SELECT node_name,am_net,pm_net FROM v_node_metrics WHERE month=? AND mode='Train' AND node_name IN ('Jurong East','Tampines','Raffles Place','Stadium','Woodlands','Punggol') ORDER BY node_name",(month,)).fetchall()
cmap=LinearSegmentedColormap.from_list('net',[AMBER,'#F2F5F5',TEAL])
a=np.array([[r['am_net'],r['pm_net']] for r in rs]);im=ax.imshow(a,cmap=cmap,vmin=-1,vmax=1,aspect='auto');ax.set_yticks(range(len(rs)),[r[0] for r in rs]);ax.set_xticks([0,1],['AM 07:00–09:59','PM 17:00–19:59']);ax.grid(False)
for i in range(len(rs)):
    for j in range(2):ax.text(j,i,f'{a[i,j]:+.2f}',ha='center',va='center',color=NAVY,weight='bold')
fig.text(.14,.057,'Amber = exit-dominant     |     Pale = balanced     |     Teal = entry-dominant',fontsize=10)
save(fig,'01_story_preview.png')

fig=canvas('Station roles are patterns, not labels of people.',f'{month_name} | Rail fare nodes | K-means uses two 24-hour normalised curves. Functional labels use transparent AM/PM thresholds.')
examples=['Woodlands','Raffles Place','Stadium','Jurong East']
for i,name in enumerate(examples):
    row=db.execute('SELECT place_key,functional_profile FROM v_node_metrics WHERE mode=\'Train\' AND node_name=? AND month=?',(name,month)).fetchone()
    if not row:continue
    rect=[.07+(i%2)*.48,.47-(i//2)*.34,.39,.24]
    ax=panel(fig,rect,name,row['functional_profile'])
    rs=db.execute('SELECT hour,boarding_share,alighting_share,cluster_label FROM profiles WHERE place_key=? AND month=? ORDER BY hour',(row['place_key'],month)).fetchall()
    ax.plot([r[0] for r in rs],[r[1] for r in rs],color=TEAL,lw=2.5,label='Entry share');ax.plot([r[0] for r in rs],[r[2] for r in rs],color=AMBER,lw=2.5,label='Exit share');ax.yaxis.set_major_formatter(PercentFormatter(1));ax.set_xticks([0,4,8,12,16,20,23]);ax.set_xlabel('Hour · SGT');ax.legend(frameon=False,fontsize=9)
    ax.text(.98,.95,rs[0]['cluster_label'],transform=ax.transAxes,ha='right',va='top',color=MUTED,fontsize=10)
save(fig,'02_station_profiles.png')

fig=canvas('Service choice is uneven. Test what failure removes.',f'{month_name} OD weights | Bus route reference: {topology[:10] if topology else "Unavailable"} | Coordinates are actual stop positions; this plot has no basemap.')
ax=panel(fig,[.07,.39,.42,.34],'Local link fragility across bus stops','Colour = outgoing-link share supported by one service')
rs=db.execute('SELECT longitude,latitude,single_service_link_share FROM redundancy_metrics WHERE latitude BETWEEN 1.1 AND 1.6 AND longitude BETWEEN 103.5 AND 104.2').fetchall()
sc=ax.scatter([r[0] for r in rs],[r[1] for r in rs],c=[r[2] for r in rs],s=9,cmap=LinearSegmentedColormap.from_list('risk',['#B8DAD7',AMBER]),vmin=0,vmax=1,alpha=.65,linewidths=0)
ax.set_xlabel('Longitude · °E');ax.set_ylabel('Latitude · °N');fig.colorbar(sc,ax=ax,pad=.02,fraction=.025,format=PercentFormatter(1));ax.set_aspect(1)
ax=panel(fig,[.62,.39,.32,.34],'Highest exposure among tested removals','Weekday OD trips losing bus-only reachability / day')
rs=db.execute("SELECT removed_service,origin_name,daily_exposed_trips FROM scenarios WHERE month=? AND day_type='WEEKDAY' ORDER BY daily_exposed_trips DESC LIMIT 5",(month,)).fetchall()
labels=[f"Remove {r[0]}\n{r[1].split(' [')[0]}" for r in rs]
ax.barh(labels[::-1],[r[2] for r in rs][::-1],color=AMBER,height=.55);ax.grid(axis='y',visible=False);ax.set_xlabel('Model-exposed trips per weekday')
fig.text(.07,.26,'WHAT THE SCENARIO MEANS',fontsize=12,weight='bold',color=TEAL)
fig.text(.07,.20,'Remove a service from every directed bus link. Recompute reachable stops from watched origins.\nWeight newly unreachable destinations by observed OD trips. Alternate bus services may preserve connectivity.',fontsize=13,linespacing=1.6)
fig.text(.07,.105,'This is a structural stress test. It excludes walking to nearby stops, rail substitution, capacity and travel time.\nA zero result means a graph path survives; it does not mean journeys are convenient or disruption-free.',fontsize=11,color=MUTED,linespacing=1.6)
save(fig,'03_resilience.png')

window=db.execute('SELECT MIN(first_seen),MAX(last_seen) FROM crowding_metrics').fetchone()
fig=canvas('Evidence improves as observation history grows.',f'{window[0]} to {window[1]} • watched stops • next-bus location-based predictions',period=window[0][:10] if window[0] else 'No observations')
count=db.execute('SELECT count(*) FROM crowding_metrics').fetchone()[0]
qualified=db.execute("SELECT count(*) FROM crowding_metrics WHERE evidence_status='Sufficient for screening'").fetchone()[0]
fig.text(.06,.735,'INSUFFICIENT HISTORY' if not qualified else f'{qualified} QUALIFYING SERVICE–STOP–HOURS',fontsize=25,color=AMBER,weight='bold')
fig.text(.06,.684,f'{count} service–stop–hour groups recorded; {qualified} meet the coverage rule. Inspect dates and sample counts.',fontsize=15)
ax=panel(fig,[.25,.31,.30,.27],'Collection footprint','Known load observations after five-minute sampling')
rs=db.execute('SELECT stop_name,SUM(known_load_bins) n FROM crowding_metrics GROUP BY stop_name ORDER BY n DESC').fetchall()
ax.barh(['\n'.join(textwrap.wrap(r[0],29)) for r in rs][::-1],[r[1] for r in rs][::-1],color=TEAL);ax.set_xlabel('Known-load sampled bins');ax.grid(axis='y',visible=False)
fig.text(.63,.57,'WHEN HISTORY ACCUMULATES',fontsize=12,weight='bold',color=TEAL)
fig.text(.63,.48,'Standing share\n(SDA + LSD) / known-load bins',fontsize=16,linespacing=1.5)
fig.text(.63,.365,'Predicted gap P90\nA screening signal, not punctuality',fontsize=16,linespacing=1.5)
fig.text(.08,.17,'Every useful observation is retained. The heatmap stays blank until a service-hour has at least\n20 known bins across five dates. Missing, stale and failed feeds are visible in the evidence ledger.',fontsize=14,linespacing=1.6)
save(fig,'04_evidence.png')
db.close();print('Rendered four analytical preview PNGs in charts/.')
