"""Interpretation-ready SQL marts, reproducible profile clustering and route-removal scenarios."""
from collections import defaultdict,deque
import csv
from datetime import datetime
import json
import math
import statistics
from transit import ROOT,now,config
import warehouse

EXPORTS={
'Places':'SELECT * FROM v_place',
'Months':'SELECT * FROM dim_month',
'Origins':'SELECT * FROM v_place',
'Destinations':'SELECT * FROM v_place',
'RailPlaces':"SELECT * FROM v_place WHERE mode='Train'",
'RailMetrics':"SELECT n.*,c.cluster_label,c.distance_to_centroid FROM v_node_metrics n LEFT JOIN clusters c USING(place_key,month) WHERE n.mode='Train'",
'Periods':"SELECT month||'|'||day_type period_key,month,day_type,days,calendar_status FROM calendar_days",
'Demand':'SELECT * FROM v_demand',
'NodeMetrics':'SELECT n.*,c.cluster_label,c.distance_to_centroid FROM v_node_metrics n LEFT JOIN clusters c USING(place_key,month)',
'Profiles':'SELECT * FROM profiles',
'Clusters':'SELECT c.*,p.place_label FROM clusters c LEFT JOIN v_place p USING(place_key)',
'MapNodes':"SELECT * FROM v_node_metrics WHERE mode='Bus' AND latitude BETWEEN 1.1 AND 1.6 AND longitude BETWEEN 103.5 AND 104.2",
'Flows':'SELECT * FROM v_flow_balance',
'Service':'SELECT * FROM service_metrics',
'Crowding':'SELECT * FROM crowding_metrics',
'Reliability':'SELECT * FROM reliability_metrics',
'Redundancy':'SELECT * FROM redundancy_metrics',
'Scenarios':'SELECT * FROM scenarios',
'Collection':'SELECT * FROM v_collection',
'Releases':'SELECT * FROM v_releases',
'InsightCards':'SELECT * FROM insight_cards',
'CrowdHistory':"SELECT c.*,r.collected_at,COALESCE(n.name,c.station) station_name FROM crowd c JOIN runs r ON r.id=c.run_id LEFT JOIN rail_names n ON n.code=c.station",
}

def replace_table(db,name,columns,rows):
    db.execute(f'DROP TABLE IF EXISTS {name}')
    db.execute(f'CREATE TABLE {name} ({columns})')
    rows=list(rows)
    if rows:db.executemany(f'INSERT INTO {name} VALUES('+','.join('?'*len(rows[0]))+')',rows)

def kmeans(vectors,k=4,iterations=60):
    """Deterministic farthest-point seeding. Squared Euclidean distance on 48 shares."""
    def dist(a,b):return sum((x-y)**2 for x,y in zip(a,b))
    if not vectors:return [],[]
    centers=[list(vectors[0])]
    for _ in range(1,min(k,len(vectors))):
        centers.append(list(max(vectors,key=lambda x:min(dist(x,c) for c in centers))))
    labels=[-1]*len(vectors)
    for _ in range(iterations):
        new=[min(range(len(centers)),key=lambda j:dist(v,centers[j])) for v in vectors]
        if new==labels:break
        labels=new
        for j in range(len(centers)):
            members=[v for v,l in zip(vectors,labels) if l==j]
            if members:centers[j]=[sum(col)/len(members) for col in zip(*members)]
    return labels,centers

def cluster_profiles(db):
    groups=defaultdict(dict)
    for month,node,h,ti,to in db.execute("SELECT month,node,hour,tap_in,tap_out FROM volumes WHERE mode='Train' AND day_type='WEEKDAY' AND hour IS NOT NULL ORDER BY month,node,hour"):
        groups[month].setdefault(node,[0]*48)[h]=ti
        groups[month][node][24+h]=to
    clusters=[];profiles=[]
    for month,nodes in groups.items():
        # Missing source hours are zero within an observed station/month; absent stations are not synthesized.
        eligible=[(n,v) for n,v in nodes.items() if sum(v)>=100 and sum(v[:24]) and sum(v[24:])]
        vectors=[[x/sum(v[:24]) for x in v[:24]]+[x/sum(v[24:]) for x in v[24:]] for n,v in eligible]
        labels,centers=kmeans(vectors)
        for (node,raw),v,label in zip(eligible,vectors,labels):
            distance=math.sqrt(sum((x-y)**2 for x,y in zip(v,centers[label])))
            clusters.append(('Train:'+node,month,f'Pattern {label+1}',distance,'Rail weekday tap-in and tap-out shapes; k=4; labels local to month'))
            days=db.execute("SELECT days FROM calendar_days WHERE month=? AND day_type='WEEKDAY'",(month,)).fetchone()[0]
            for h in range(24):
                profiles.append(('Train:'+node,month,h,f'{h:02}:00',v[h],v[24+h],raw[h]/days if days else None,raw[24+h]/days if days else None,f'Pattern {label+1}'))
    replace_table(db,'clusters','place_key TEXT,month TEXT,cluster_label TEXT,distance_to_centroid REAL,method TEXT',clusters)
    replace_table(db,'profiles','place_key TEXT,month TEXT,hour INTEGER,hour_label TEXT,boarding_share REAL,alighting_share REAL,daily_boardings REAL,daily_alightings REAL,cluster_label TEXT',profiles)

def quantile(xs,q):
    if not xs:return None
    xs=sorted(xs);p=(len(xs)-1)*q;i=int(p);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(p-i)

def operational_metrics(db):
    db.row_factory=__import__('sqlite3').Row
    # One latest monitored next-bus record per service/stop/five-minute bin.
    # This limits polling-frequency bias; it does not identify unique vehicles.
    bins={}
    for r in db.execute('SELECT * FROM v_poll_samples ORDER BY collected_at,run_id'):
        if r['monitored']!=1 or r['wait_minutes']<0:continue
        t=datetime.fromisoformat(r['collected_at'])
        bins[(r['stop_code'],r['service'],int(t.timestamp())//300)]=dict(r)
    groups=defaultdict(list)
    for r in bins.values():groups[(r['stop_code'],r['service'],r['sg_hour'])].append(r)
    crowd=[];reliable=[];cfg=config();min_days=cfg.get('minimum_observation_dates',5)
    for (stop,service,hour),rs in sorted(groups.items()):
        dates=len({r['sg_date'] for r in rs});known=[r for r in rs if r['standing'] is not None]
        status='Sufficient for screening' if dates>=min_days and len(known)>=20 else 'Insufficient history'
        starts=min(r['collected_at'] for r in rs);ends=max(r['collected_at'] for r in rs)
        standing=sum(r['standing'] for r in known);limited=sum(r['limited'] for r in known)
        crowd.append((stop,rs[0]['stop_name'],service,hour,f'{hour:02}:00',len(rs),len(known),dates,standing,limited,standing/len(known) if known else None,limited/len(known) if known else None,status,starts,ends))
        gaps=[r['predicted_gap_minutes'] for r in rs if r['predicted_gap_minutes'] is not None];waits=[r['monitored_wait'] for r in rs if r['monitored_wait'] is not None]
        med=statistics.median(gaps) if gaps else None;p90=quantile(gaps,.9)
        cv=statistics.pstdev(gaps)/statistics.mean(gaps) if len(gaps)>1 and statistics.mean(gaps)>0 else None
        gap_status='Sufficient for screening' if dates>=min_days and len(gaps)>=20 else 'Insufficient history'
        reliable.append((stop,rs[0]['stop_name'],service,hour,f'{hour:02}:00',len(gaps),dates,med,p90,cv,quantile(waits,.9),gap_status,starts,ends))
    db.row_factory=None
    replace_table(db,'crowding_metrics','stop_code TEXT,stop_name TEXT,service TEXT,hour INTEGER,hour_label TEXT,sampled_bins INTEGER,known_load_bins INTEGER,distinct_dates INTEGER,standing_bins INTEGER,limited_bins INTEGER,standing_share REAL,limited_share REAL,evidence_status TEXT,first_seen TEXT,last_seen TEXT',crowd)
    replace_table(db,'reliability_metrics','stop_code TEXT,stop_name TEXT,service TEXT,hour INTEGER,hour_label TEXT,gap_samples INTEGER,distinct_dates INTEGER,median_predicted_gap REAL,p90_predicted_gap REAL,predicted_gap_cv REAL,p90_predicted_wait REAL,evidence_status TEXT,first_seen TEXT,last_seen TEXT',reliable)

def reachable(graph,start,removed=None):
    seen={start};todo=deque([start])
    while todo:
        a=todo.popleft()
        for b,services in graph.get(a,{}).items():
            if b not in seen and (removed is None or services-{removed}):seen.add(b);todo.append(b)
    return seen

def network_metrics(db):
    routes=defaultdict(list);stop_services=defaultdict(set);graph=defaultdict(dict)
    for service,direction,seq,stop in db.execute('SELECT service,direction,sequence,stop_code FROM routes ORDER BY service,direction,sequence'):
        routes[(service,direction)].append((seq,stop));stop_services[stop].add(service)
    for (service,direction),stops in routes.items():
        for (i,a),(j,b) in zip(stops,stops[1:]):
            if j==i+1 and a!=b:graph[a].setdefault(b,set()).add(service)
    names={r[0]:r[1:] for r in db.execute("SELECT node,place_label,latitude,longitude FROM v_place WHERE mode='Bus'")}
    redundancy=[]
    for stop,edges in graph.items():
        single=sum(len(s)==1 for s in edges.values());label,lat,lon=names.get(stop,(stop,None,None))
        redundancy.append(('Bus:'+stop,label,lat,lon,len(stop_services[stop]),len(edges),single,single/len(edges),min(len(x) for x in edges.values())))
    replace_table(db,'redundancy_metrics','place_key TEXT,stop_name TEXT,latitude REAL,longitude REAL,service_count INTEGER,outgoing_links INTEGER,single_service_links INTEGER,single_service_link_share REAL,minimum_link_services INTEGER',redundancy)
    services=[]
    for place,month,label,lat,lon,daily,am,pm,profile in db.execute("SELECT place_key,month,place_label,latitude,longitude,weekday_daily,am_net,pm_net,functional_profile FROM v_node_metrics WHERE mode='Bus'"):
        count=len(stop_services[place.split(':')[1]])
        services.append((place,month,label,lat,lon,daily,count,daily/count if daily is not None and count else None,am,pm,profile))
    replace_table(db,'service_metrics','place_key TEXT,month TEXT,stop_name TEXT,latitude REAL,longitude REAL,weekday_daily REAL,service_count INTEGER,boardings_per_service REAL,am_net REAL,pm_net REAL,functional_profile TEXT',services)
    scenarios=[]
    topology=db.execute("SELECT MAX(collected_at) FROM runs WHERE dataset='BusRoutes' AND status='ok'").fetchone()[0]
    for origin in config()['bus_stops']:
        baseline=reachable(graph,origin)
        flows=db.execute("SELECT month,day_type,destination,SUM(trips) FROM od WHERE mode='Bus' AND origin=? GROUP BY month,day_type,destination",(origin,)).fetchall()
        for service in sorted(stop_services[origin]):
            after=reachable(graph,origin,service);lost=baseline-after;weighted=defaultdict(lambda:[0,0,0])
            for month,day,destination,trips in flows:
                w=weighted[(month,day)];w[0]+=trips if destination in lost else 0;w[1]+=trips if destination in baseline else 0;w[2]+=trips if destination not in baseline else 0
            for (month,day),(lost_trips,base_trips,unmapped_trips) in weighted.items():
                days=db.execute('SELECT days FROM calendar_days WHERE month=? AND day_type=?',(month,day)).fetchone()[0]
                scenarios.append((service,'Bus:'+origin,names.get(origin,(origin,))[0],month,day,len(lost),lost_trips,base_trips,unmapped_trips,lost_trips/base_trips if base_trips else None,lost_trips/days if days else None,topology))
    replace_table(db,'scenarios','removed_service TEXT,origin_key TEXT,origin_name TEXT,month TEXT,day_type TEXT,lost_reachable_stops INTEGER,exposed_trips INTEGER,baseline_reachable_trips INTEGER,baseline_unreachable_trips INTEGER,exposed_trip_share REAL,daily_exposed_trips REAL,topology_as_of TEXT',scenarios)

def insights(db):
    rows=[]
    for (month,) in db.execute('SELECT DISTINCT month FROM volumes ORDER BY month'):
        title=datetime.strptime(month,'%Y%m').strftime('%B %Y')
        top=db.execute("SELECT place_label,weekday_daily FROM v_node_metrics WHERE month=? AND mode='Train' ORDER BY weekday_daily DESC LIMIT 1",(month,)).fetchone()
        if top and top[1] is not None:rows.append((month,'Demand',f'{top[0]} leads rail entries',f'{top[1]:,.0f} entries per weekday in {title}. Entries measure rides, not distinct people.','Observed'))
        rising=db.execute("SELECT place_label,weekend_uplift FROM v_node_metrics WHERE month=? AND mode='Train' AND weekday_daily>=1000 ORDER BY weekend_uplift DESC LIMIT 1",(month,)).fetchone()
        if rising and rising[1] is not None:rows.append((month,'Transformation',f'{rising[0]} changes most at weekends',f'{rising[1]:.2f}x weekday entries per day, among rail stations with at least 1,000 weekday entries/day. Weekend includes public holidays.','Observed; purpose inferred'))
        reversal=db.execute("SELECT COUNT(*) FROM v_node_metrics WHERE month=? AND mode='Train' AND functional_profile='Residential-like origin'",(month,)).fetchone()[0]
        rows.append((month,'Profiles',f'{reversal} rail fare nodes show an outbound-AM / inbound-PM pattern','07:00–09:59 versus 17:00–19:59 SGT; net-flow thresholds +0.20 and -0.20. This suggests, but does not establish, residential use.','Heuristic'))
    coverage=db.execute('SELECT count(DISTINCT sg_date),min(collected_at),max(collected_at) FROM v_poll_samples').fetchone()
    rows.append(('All','Reliability',f'{coverage[0]} sampled date(s): check evidence status',f'Observation window {coverage[1]} to {coverage[2]}. Predicted gaps are not measured punctuality.','Coverage limited'))
    replace_table(db,'insight_cards','month TEXT,chapter TEXT,headline TEXT,explanation TEXT,evidence TEXT',rows)

def refresh(db):
    warehouse.initialize(db,ROOT)
    db.executescript((ROOT/'sql/analytics.sql').read_text())
    with db:
        months=[(m,datetime.strptime(m,'%Y%m').strftime('%B %Y')) for (m,) in db.execute('SELECT DISTINCT month FROM volumes UNION SELECT DISTINCT month FROM od ORDER BY month')]
        replace_table(db,'dim_month','month TEXT PRIMARY KEY,month_label TEXT',months)
        cluster_profiles(db);operational_metrics(db);network_metrics(db);insights(db)
    print('Analytical marts rebuilt from archived facts.',flush=True)

if __name__=='__main__':
    import transit
    with transit.connect() as db:transit.export(db)
