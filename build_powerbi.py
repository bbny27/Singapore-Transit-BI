"""Generate the semantic model, standalone M queries and designed native PBIR pages.
Default invocation only configures paths; use --rebuild-report to replace report visuals.
"""
import argparse
import csv
import json
import shutil
from pathlib import Path
from transit import ROOT

PBI=ROOT/'powerbi'
SCHEMA='https://developer.microsoft.com/json-schemas/fabric/item/'
NAVY='#142D3D';TEAL='#007F7B';AMBER='#B66A19';MUTED='#536773';BG='#F2F5F5';WHITE='#FFFFFF'

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,indent=2),encoding='utf-8')

def field(table,col,measure=False):
    return {'Measure' if measure else 'Column':{'Expression':{'SourceRef':{'Entity':table}},'Property':col}}

def literal(value):
    if isinstance(value,bool):value='true' if value else 'false'
    elif isinstance(value,(int,float)):value=str(value)+'D'
    else:value="'"+value.replace("'","''")+"'"
    return {'expr':{'Literal':{'Value':value}}}

def color(value):return {'solid':{'color':literal(value)}}

INTS=set('hour days calendar_days tap_in tap_out trips am_trips pm_trips unknown_hour_trips reverse_am_trips reverse_pm_trips wd_boardings we_boardings am_in am_out pm_in pm_out unknown_hour_taps known_hour_boardings service_count outgoing_links single_service_links minimum_link_services sampled_bins known_load_bins distinct_dates standing_bins limited_bins gap_samples lost_reachable_stops exposed_trips baseline_reachable_trips baseline_unreachable_trips attempts successes failures empty_responses release_id archived_bytes year daily_ridership run_id bus_rank monitored rows_loaded id'.split())
FLOATS=set('latitude longitude daily_boardings daily_alightings net_flow weekday_daily weekend_daily weekend_uplift am_net pm_net peak_share reversal_score distance_to_centroid boarding_share alighting_share daily_trips am_direction_balance boardings_per_service standing_share limited_share median_predicted_gap p90_predicted_gap predicted_gap_cv p90_predicted_wait single_service_link_share exposed_trip_share daily_exposed_trips success_share wait_minutes'.split())
MEASURES={
'Demand':{
'Entries':('SUM(Demand[tap_in])','#,0'),
'Exits':('SUM(Demand[tap_out])','#,0'),
'Entries per day':('IF(COUNTROWS(FILTER(Demand,ISBLANK(Demand[calendar_days])))=0,DIVIDE([Entries], SUMX(SUMMARIZE(Demand, Demand[period_key], Demand[calendar_days]), Demand[calendar_days])))','#,0'),
'Exits per day':('IF(COUNTROWS(FILTER(Demand,ISBLANK(Demand[calendar_days])))=0,DIVIDE([Exits], SUMX(SUMMARIZE(Demand, Demand[period_key], Demand[calendar_days]), Demand[calendar_days])))','#,0'),
'Net flow':('DIVIDE([Entries]-[Exits],[Entries]+[Exits])','0.00'),
'Net flow colour':('SWITCH(TRUE(),ISBLANK([Net flow]),"#EDF1F2",[Net flow]<-0.2,"#C77728",[Net flow]>0.2,"#007F7B","#E0E8E8")',''),
'Period context':('"Singapore | " & CONCATENATEX(VALUES(Months[month_label]),Months[month_label],", ") & " | " & CONCATENATEX(VALUES(DayTypes[day_type]),DayTypes[day_type],", ") & " | hours in SGT"','')},
'NodeMetrics':{
'Weekday entries per node':('IF(HASONEVALUE(Months[month]),SUM(NodeMetrics[weekday_daily]))','#,0'),
'Weekend ratio':('IF(HASONEVALUE(Months[month]),DIVIDE(SUM(NodeMetrics[weekend_daily]),SUM(NodeMetrics[weekday_daily])))','0.00"x"'),
'AM net':('IF(HASONEVALUE(Months[month]),DIVIDE(SUM(NodeMetrics[am_in])-SUM(NodeMetrics[am_out]),SUM(NodeMetrics[am_in])+SUM(NodeMetrics[am_out])))','0.00'),
'PM net':('IF(HASONEVALUE(Months[month]),DIVIDE(SUM(NodeMetrics[pm_in])-SUM(NodeMetrics[pm_out]),SUM(NodeMetrics[pm_in])+SUM(NodeMetrics[pm_out])))','0.00'),
'Profile node count':('DISTINCTCOUNT(NodeMetrics[place_key])','#,0')},
'MapNodes':{'Map weekend ratio':('IF(HASONEVALUE(Months[month]),DIVIDE(SUM(MapNodes[weekend_daily]),SUM(MapNodes[weekday_daily])))','0.00"x"')},
'Profiles':{'Mean entry share':('AVERAGE(Profiles[boarding_share])','0.0%'),'Mean exit share':('AVERAGE(Profiles[alighting_share])','0.0%')},
'Flows':{'OD rides':('SUM(Flows[trips])','#,0'),'AM OD rides':('SUM(Flows[am_trips])','#,0'),'PM return rides':('SUM(Flows[reverse_pm_trips])','#,0')},
'Service':{'Daily demand':('IF(HASONEVALUE(Months[month]),SUM(Service[weekday_daily]))','#,0'),'Distinct services':('MAX(Service[service_count])','0')},
'Crowding':{
'Standing share':('DIVIDE(SUM(Crowding[standing_bins]),SUM(Crowding[known_load_bins]))','0.0%'),
'Limited standing share':('DIVIDE(SUM(Crowding[limited_bins]),SUM(Crowding[known_load_bins]))','0.0%'),
'Eligible standing share':('CALCULATE([Standing share],Crowding[evidence_status]="Sufficient for screening")','0.0%'),
'Standing colour':('IF(ISBLANK([Eligible standing share]),"#EDF1F2",IF([Eligible standing share]>=0.3,"#C77728","#76BDB6"))',''),
'Coverage status':('IF(CALCULATE(COUNTROWS(Crowding),Crowding[evidence_status]="Sufficient for screening")>0,"Some service-hours qualify; inspect status","INSUFFICIENT HISTORY — continue collecting")','')},
'Reliability':{'Eligible predicted gap P90':('CALCULATE(MAX(Reliability[p90_predicted_gap]),Reliability[evidence_status]="Sufficient for screening")','0.0" min"')},
'Scenarios':{'Exposed share':('DIVIDE(SUM(Scenarios[exposed_trips]),SUM(Scenarios[baseline_reachable_trips]))','0.0%')},
'Collection':{'API success share':('DIVIDE(SUM(Collection[successes]),SUM(Collection[attempts]))','0.0%')},
'Redundancy':{'Single-service link share':('DIVIDE(SUM(Redundancy[single_service_links]),SUM(Redundancy[outgoing_links]))','0.0%')}
}
TABLES=['Places','RailPlaces','RailMetrics','Periods','Demand','NodeMetrics','MapNodes','Profiles','Clusters','Flows','Service','Crowding','Reliability','Redundancy','Scenarios','Collection','Releases','InsightCards','CrowdHistory','Annual','Runs']

# Tables are imported independently. No query references its own name; this fixes cyclic M dependencies.
def model():
    tables=[];mfolder=PBI/'powerquery';mfolder.mkdir(exist_ok=True)
    folder=ROOT/'data/exports'
    months=sorted({r['month'] for r in csv.DictReader((folder/'Periods.csv').open(encoding='utf-8-sig'))})
    from datetime import datetime
    extra={'Months':(['month','month_label'],[(m,datetime.strptime(m,'%Y%m').strftime('%B %Y')) for m in months]),
           'Modes':(['mode'],[('Bus',),('Train',)]),'DayTypes':(['day_type'],[('WEEKDAY',),('WEEKENDS/HOLIDAY',)]),
           'Hours':(['hour','hour_label'],[(h,f'{h:02}:00') for h in range(24)])}
    for name,(cols,rows) in extra.items():
        with (folder/f'{name}.csv').open('w',newline='',encoding='utf-8-sig') as f:w=csv.writer(f);w.writerow(cols);w.writerows(rows)
    for name in ['Origins','Destinations']:
        shutil.copyfile(folder/'Places.csv',folder/f'{name}.csv')
    for name in TABLES+list(extra)+['Origins','Destinations']:
        path=folder/f'{name}.csv'
        with path.open(encoding='utf-8-sig') as f:cols=next(csv.reader(f))
        types={c:'int64' if c in INTS else 'double' if c in FLOATS else 'string' for c in cols}
        columns=[]
        for c in cols:
            d={'name':c,'dataType':types[c],'sourceColumn':c,'summarizeBy':'none'}
            if c in ['latitude','longitude']:d['dataCategory']=c.title()
            if c.endswith('_share') or c in ['peak_share','boarding_share','alighting_share']:d['formatString']='0.0%'
            if c in ['weekend_uplift']:d['formatString']='0.00"x"'
            if c in ['am_net','pm_net','reversal_score','net_flow']:d['formatString']='0.00'
            if c=='month_label':d['sortByColumn']='month'
            columns.append(d)
        mtypes=', '.join('{"'+c+'", '+{'int64':'Int64.Type','double':'type number','string':'type text'}[types[c]]+'}' for c in cols)
        expression=['let','  Source = Csv.Document(File.Contents("'+str(path).replace('\\','/').replace('"','""')+'"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        '  Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
        '  Nulls = Table.ReplaceValue(Headers, "", null, Replacer.ReplaceValue, Table.ColumnNames(Headers)),',
        '  Typed = Table.TransformColumnTypes(Nulls, {'+mtypes+'}, "en-SG")','in Typed']
        (mfolder/f'{name}.pq').write_text('\n'.join(expression)+'\n',encoding='utf-8')
        table={'name':name,'columns':columns,'partitions':[{'name':name,'mode':'import','source':{'type':'m','expression':expression}}]}
        if name in MEASURES:table['measures']=[{'name':n,'expression':e,'formatString':fmt} for n,(e,fmt) in MEASURES[name].items()]
        tables.append(table)
    relations=[]
    def relation(ft,fc,dt,dc):relations.append({'name':f'{ft}_{fc}_{dt}','fromTable':ft,'fromColumn':fc,'toTable':dt,'toColumn':dc,'crossFilteringBehavior':'oneDirection','fromCardinality':'many','toCardinality':'one'})
    for name in ['Demand','NodeMetrics','MapNodes','Service','Redundancy']:relation(name,'place_key','Places','place_key')
    for name in ['Profiles','Clusters','RailMetrics']:relation(name,'place_key','RailPlaces','place_key')
    for name in ['Demand','RailMetrics','NodeMetrics','MapNodes','Profiles','Clusters','Flows','Service','Scenarios','Releases']:relation(name,'month','Months','month')
    for name in ['Demand','Flows','Scenarios']:relation(name,'day_type','DayTypes','day_type')
    for name in ['Demand','Profiles','Crowding','Reliability']:relation(name,'hour','Hours','hour')
    relation('Places','mode','Modes','mode');relation('Flows','mode','Modes','mode')
    relation('Flows','origin_key','Origins','place_key');relation('Flows','destination_key','Destinations','place_key')
    write(PBI/'Transit.SemanticModel/model.bim',{'name':'Transit','compatibilityLevel':1567,'model':{'culture':'en-US','sourceQueryCulture':'en-SG','defaultPowerBIDataSourceVersion':'powerBI_V3','tables':tables,'relationships':relations}})
    write(PBI/'Transit.SemanticModel/definition.pbism',{'version':'1.0','settings':{}})
    (PBI/'measures.dax').write_text('\n\n'.join('// '+t+'\n'+n+' = '+e for t,ms in MEASURES.items() for n,(e,_) in ms.items()),encoding='utf-8')

class Report:
    def __init__(self):
        self.folder=PBI/'Transit.Report';self.pages=[];self.counter=0
        if (self.folder/'definition').exists():shutil.rmtree(self.folder/'definition')
        write(PBI/'Transit.pbip',{'version':'1.0','artifacts':[{'report':{'path':'Transit.Report'}}],'settings':{'enableAutoRecovery':True}})
        write(self.folder/'definition.pbir',{'$schema':SCHEMA+'report/definitionProperties/2.0.0/schema.json','version':'4.0','datasetReference':{'byPath':{'path':'../Transit.SemanticModel'}}})
        write(self.folder/'definition/version.json',{'$schema':SCHEMA+'report/definition/versionMetadata/1.0.0/schema.json','version':'2.0.0'})
        write(self.folder/'definition/report.json',{'$schema':SCHEMA+'report/definition/report/1.0.0/schema.json','themeCollection':{},'layoutOptimization':'None'})
    def save_visual(self,p,kind,x,y,w,h,visual):
        self.counter+=1;name=f'v{self.counter:04}'
        obj={'$schema':SCHEMA+'report/definition/visualContainer/2.1.0/schema.json','name':name,'position':{'x':x,'y':y,'z':self.counter,'height':h,'width':w,'tabOrder':self.counter},'visual':{'visualType':kind,**visual}}
        write(p/'visuals'/name/'visual.json',obj)
    def text(self,p,text,x,y,w,h,size=12,fg=MUTED,bg=WHITE):
        self.save_visual(p,'textbox',x,y,w,h,{'objects':{'general':[{'properties':{'paragraphs':[{'textRuns':[{'value':text,'textStyle':{'fontFamily':'Segoe UI','fontSize':f'{size}pt','color':fg}}]}]}}]},'visualContainerObjects':{'background':[{'properties':{'show':literal(True),'color':color(bg),'transparency':literal(0)}}]}})
    def page(self,name,title,question,caption):
        self.pages.append(name);p=self.folder/'definition/pages'/name
        write(p/'page.json',{'$schema':SCHEMA+'report/definition/page/1.0.0/schema.json','name':name,'displayName':title,'displayOption':'FitToPage','width':1440,'height':960,'objects':{'background':[{'properties':{'color':color(BG),'transparency':literal(0)}}]}})
        self.text(p,'TRANSIT / INTELLIGENCE     •     SINGAPORE',24,12,1392,28,11,WHITE,NAVY)
        self.text(p,question,24,40,1392,55,25,WHITE,NAVY)
        self.text(p,caption,24,100,1392,50,12,MUTED,BG)
        self.text(p,'DEMAND  →  FLOW  →  SERVICE  →  RELIABILITY  →  RESILIENCE     |     Select a chapter using the tabs below.',24,920,1392,30,11,MUTED,BG)
        return p
    def visual(self,p,kind,title,roles,x,y,w,h,conditional=None):
        query={role:{'projections':[{'field':field(*f),'queryRef':f[0]+'.'+f[1],'nativeQueryRef':f[1].replace('_',' ').capitalize()} for f in fs]} for role,fs in roles.items()}
        vc={'title':[{'properties':{'show':literal(True),'text':literal(title),'fontColor':color(NAVY),'fontSize':literal(13),'fontFamily':literal('Segoe UI')}}],
            'background':[{'properties':{'show':literal(True),'color':color(WHITE),'transparency':literal(0)}}],
            'border':[{'properties':{'show':literal(True),'color':color('#DBE3E6'),'radius':literal(8)}}]}
        objects={'categoryAxis':[{'properties':{'labelColor':color(MUTED),'fontSize':literal(11),'showAxisTitle':literal(True)}}],
                 'valueAxis':[{'properties':{'labelColor':color(MUTED),'fontSize':literal(11),'showAxisTitle':literal(True)}}],
                 'legend':[{'properties':{'show':literal(True),'fontSize':literal(11),'labelColor':color(MUTED),'position':literal('Top')}}],
                 'dataPoint':[{'properties':{'defaultColor':color(TEAL)}}]}
        if kind=='tableEx' or kind=='pivotTable':
            objects={'columnHeaders':[{'properties':{'fontColor':color(WHITE),'backColor':color(NAVY),'fontSize':literal(11),'wordWrap':literal(True)}}],
                     'values':[{'properties':{'fontColorPrimary':color(NAVY),'backColorPrimary':color(WHITE),'backColorSecondary':color('#F0F5F5'),'fontSize':literal(11),'wordWrap':literal(True)}}],
                     'grid':[{'properties':{'rowPadding':literal(6)}}]}
        if kind=='slicer':objects={'data':[{'properties':{'mode':literal('Dropdown')}}]}
        if conditional:
            value_field=roles['Values'][0]
            objects['cellElements']=[{'properties':{'backColor':{'solid':{'color':{'expr':field(*conditional)}}},'backColorShow':literal(True)},'selector':{'metadata':value_field[0]+'.'+value_field[1],'data':[{'dataViewWildcard':{'matchingOption':1}}]}}]
        v={'query':{'queryState':query},'visualContainerObjects':vc,'objects':objects,'drillFilterOtherVisuals':True}
        if kind=='lineChart':
            objects['dataPoint']=[{'properties':{'fill':color(c)},'selector':{'metadata':f[0]+'.'+f[1]}} for f,c in zip(roles.get('Y',[]),[TEAL,AMBER,'#5B74A7'])]
        if kind=='lineChart':v['query']['sortDefinition']={'sort':[{'field':field(*roles['Category'][0]),'direction':'Ascending'}],'isDefaultSort':False}
        if kind=='clusteredBarChart':v['query']['sortDefinition']={'sort':[{'field':field(*roles['Y'][0]),'direction':'Descending'}],'isDefaultSort':False}
        if kind=='map':
            for role in ['Latitude','Longitude']:
                proj=v['query']['queryState'][role]['projections'][0]
                proj['field']={'Aggregation':{'Expression':proj['field'],'Function':3}}
                proj['queryRef']='Min('+proj['queryRef']+')'
            objects['mapControls']=[{'properties':{'autoZoom':literal(True)}}]
        self.save_visual(p,kind,x,y,w,h,v)
    def slicer(self,p,t,c,title,x,w=280):self.visual(p,'slicer',title,{'Values':[(t,c)]},x,164,w,75)
    def table(self,p,t,cols,title,x,y,w,h):self.visual(p,'tableEx',title,{'Values':[(t,c) for c in cols]},x,y,w,h)
    def finish(self):
        write(self.folder/'definition/pages/pages.json',{'$schema':SCHEMA+'report/definition/pagesMetadata/1.0.0/schema.json','pageOrder':self.pages,'activePageName':self.pages[0]})
        print(f'Built {len(self.pages)} pages / {self.counter} visuals')

def report():
    r=Report()
    p=r.page('01_demand','01 | Demand','Where does the city enter the network?','Compare daily entries using a holiday-aware calendar. Bus and rail counts are ride entries; adding them does not count unique people.')
    r.slicer(p,'Months','month_label','Month',24);r.slicer(p,'Modes','mode','Transport mode',320);r.slicer(p,'DayTypes','day_type','Day type',616)
    r.visual(p,'card','Average entries per selected day',{'Values':[('Demand','Entries per day',True)]},24,256,430,120)
    r.visual(p,'card','Current selection',{'Values':[('Demand','Period context',True)]},474,256,942,120)
    r.visual(p,'lineChart','When demand builds | hourly entries and exits per day',{'Category':[('Hours','hour_label')],'Y':[('Demand','Entries per day',True),('Demand','Exits per day',True)]},24,394,865,470)
    r.table(p,'InsightCards',['month','headline','explanation'],'Computed findings | full available month; independent of mode/day filters',910,394,506,470)
    p=r.page('02_profiles','02 | Station roles','Which stations export commuters in the morning?','Rail fare nodes • Weekdays • AM 07:00–09:59, PM 17:00–19:59 SGT. Functional labels are hypotheses about usage, not verified trip purpose.')
    r.slicer(p,'Months','month_label','Select one month',24);r.slicer(p,'RailPlaces','place_label','Station / stop name',320,450);r.slicer(p,'RailMetrics','functional_profile','Profile (table only)',790,350)
    r.visual(p,'lineChart','24-hour rail profile | share of daily entries / exits',{'Category':[('Hours','hour_label')],'Y':[('Profiles','Mean entry share',True),('Profiles','Mean exit share',True)]},24,258,740,320)
    r.table(p,'RailMetrics',['place_label','functional_profile','am_net','pm_net','cluster_label'],'Station roles | + net = more entering; − net = more exiting',784,258,632,620)
    r.table(p,'Clusters',['place_label','cluster_label','distance_to_centroid','method'],'Cluster assignment | lower distance = closer to its pattern centroid',24,596,740,282)
    p=r.page('03_transformation','03 | Daily transformation','Commuter pattern or weekend destination?','Weekend uplift = entries per weekend/holiday day ÷ entries per weekday. 1.00x means equal daily demand. Select one month; net-flow grid responds to day type.')
    r.slicer(p,'Months','month_label','Select one month',24);r.slicer(p,'Modes','mode','Mode',320);r.slicer(p,'Places','place_label','Choose places for the hourly grid',616,450)
    r.visual(p,'map','Bus stops only | size = weekend / weekday daily-entry ratio',{'Category':[('MapNodes','place_label')],'Latitude':[('MapNodes','latitude')],'Longitude':[('MapNodes','longitude')],'Size':[('MapNodes','Map weekend ratio',True)]},24,258,680,310)
    r.table(p,'NodeMetrics',['place_label','weekday_daily','weekend_daily','weekend_uplift'],'Read volume alongside uplift: a small base can give a large ratio',724,258,692,310)
    r.visual(p,'pivotTable','Hourly net flow | teal: entering-dominant; amber: exiting-dominant',{'Rows':[('Places','place_label')],'Columns':[('Hours','hour_label')],'Values':[('Demand','Net flow',True)]},24,586,1392,292,('Demand','Net flow colour',True))
    p=r.page('04_flow','04 | Flow','Where do these passengers go—and do they return?','OD endpoints describe observed trips, not the path or bus service taken. The original August bus extract covers watched endpoints; inspect od_scope for every release.')
    r.slicer(p,'Months','month_label','Month',24);r.slicer(p,'Modes','mode','Mode',320);r.slicer(p,'Origins','place_label','Origin name',616,390);r.slicer(p,'DayTypes','day_type','Day type',1022,394)
    r.visual(p,'clusteredBarChart','Destination demand | select an origin to tell a local story',{'Category':[('Flows','destination_name')],'Y':[('Flows','OD rides',True)]},24,258,650,400)
    r.table(p,'Flows',['origin_name','destination_name','am_trips','reverse_pm_trips','reversal_label','od_scope'],'Morning direction and evening return | compare directions, not individuals',694,258,722,620)
    r.text(p,'INTERPRETATION\nA strong AM outbound / PM inbound pair suggests a commuting relationship. Aggregate records cannot establish that the same people returned, nor which service or transfer path they used.',24,678,650,200,16,NAVY)
    p=r.page('05_service','05 | Service','Where should we investigate demand versus service?','Structural supply = distinct bus services calling at a stop. Entries per service is a screening proxy; it excludes vehicle capacity, frequency and passenger load between stops.')
    r.slicer(p,'Months','month_label','Select one month',24);r.slicer(p,'Places','place_label','Bus stop name',320,480)
    r.visual(p,'scatterChart','Demand versus service choice | each point is a bus stop',{'Category':[('Service','stop_name')],'X':[('Service','Distinct services',True)],'Y':[('Service','Daily demand',True)]},24,258,710,430)
    r.table(p,'Service',['stop_name','weekday_daily','service_count','boardings_per_service'],'Review high demand with few distinct services; no capacity claim',754,258,662,430)
    r.text(p,'A QUESTION TO INVESTIGATE\nDoes a high-demand stop also show sustained standing conditions or long predicted gaps? Use the next page to inspect sampled evidence. A large demand/service ratio alone does not justify adding buses.',24,710,1392,168,17,NAVY)
    p=r.page('06_reliability','06 | Reliability','Is pressure persistent, or have we sampled too little?','Watched bus stops only • next bus • location-based predictions • latest record per 5-minute bin. Qualifying service-hours require ≥20 known bins across ≥5 dates.')
    r.slicer(p,'Crowding','stop_name','Crowding stop',24,370);r.slicer(p,'Crowding','service','Crowding service',410);r.slicer(p,'Hours','hour_label','SGT hour (both panels)',706)
    r.visual(p,'card','Evidence available for the selected crowding cells',{'Values':[('Crowding','Coverage status',True)]},24,258,1392,100)
    r.visual(p,'pivotTable','Standing share | SDA + LSD / known loads; blank = insufficient history',{'Rows':[('Crowding','stop_name'),('Crowding','service')],'Columns':[('Hours','hour_label')],'Values':[('Crowding','Eligible standing share',True)]},24,376,1392,235,('Crowding','Standing colour',True))
    r.table(p,'Crowding',['stop_name','service','known_load_bins','distinct_dates','standing_share','evidence_status','first_seen','last_seen'],'Crowding sample audit | raw fractions are exploratory',24,629,682,250)
    r.table(p,'Reliability',['stop_name','service','hour_label','gap_samples','p90_predicted_gap','evidence_status','first_seen','last_seen'],'Predicted gap audit | not actual punctuality; stop/service filters above affect left panel',726,629,690,250)
    p=r.page('07_resilience','07 | Resilience','What breaks if one bus service disappears?','Directed bus-stop graph • remove all links supported only by the selected service • allow transfers at the same stop. No walking, rail substitution, capacity or journey-time modelling.')
    r.slicer(p,'Scenarios','removed_service','Remove service',24);r.slicer(p,'Scenarios','origin_name','Watched origin',320,430);r.slicer(p,'Months','month_label','OD month',766);r.slicer(p,'DayTypes','day_type','Day type',1062,354)
    r.visual(p,'map','Bus structural fragility | size = fraction of outgoing links with one service',{'Category':[('Redundancy','stop_name')],'Latitude':[('Redundancy','latitude')],'Longitude':[('Redundancy','longitude')],'Size':[('Redundancy','Single-service link share',True)]},24,258,650,380)
    r.table(p,'Scenarios',['removed_service','origin_name','lost_reachable_stops','daily_exposed_trips','exposed_trip_share','baseline_unreachable_trips','topology_as_of'],'Scenario results | exposed OD trips lose reachability in this bus-only model',694,258,722,620)
    r.text(p,'HOW TO READ THE MAP\nEvery circle is a verified bus-stop coordinate. Larger circles have more outgoing links supported by just one service. This map describes local link redundancy; the table separately tests end-to-end reachability after a service removal.',24,658,650,220,16,NAVY)
    p=r.page('08_archive','08 | Evidence & archive','What do we know, and what is still missing?','Monthly history grows as releases arrive. Every downloaded monthly version and useful raw response is stored in SQLite. Export timestamps are not the observation period.')
    r.slicer(p,'Releases','month','Archive month',24);r.slicer(p,'Collection','dataset','Collection dataset',320)
    r.table(p,'Releases',['dataset','month','source_kind','version_status','scope','archived_at'],'Release ledger | original bytes versus explicitly labelled legacy extracts',24,258,1392,265)
    r.table(p,'Collection',['dataset','scope','attempts','failures','empty_responses','first_seen','last_seen'],'Collection coverage | empty is distinct from failed',24,541,850,337)
    r.table(p,'Periods',['month','day_type','days','calendar_status'],'Holiday-aware denominators',894,541,522,337)
    r.finish()
    write(PBI/'Transit_Theme.json',{'name':'Transit Intelligence','dataColors':[TEAL,AMBER,'#5B74A7','#A06687','#6B8E55'],'background':WHITE,'foreground':NAVY,'tableAccent':TEAL,'textClasses':{'title':{'fontFace':'Segoe UI','fontSize':13},'label':{'fontFace':'Segoe UI','fontSize':11}}})

def configure_paths():
    path=PBI/'Transit.SemanticModel/model.bim'
    if not path.exists():model();return
    obj=json.loads(path.read_text())
    for table in obj['model']['tables']:
        name=table['name'];csv_path=ROOT/'data/exports'/f'{name}.csv'
        if not csv_path.exists():continue
        for partition in table.get('partitions',[]):
            source=partition.get('source',{})
            expression=source.get('expression',[])
            if source.get('type')!='m' or not isinstance(expression,list):continue
            import re
            newpath=str(csv_path).replace('\\','/').replace('"','""')
            expression=[re.sub(r'File\.Contents\("(?:[^"]|"")*"\)',lambda _: 'File.Contents("'+newpath+'")',line) for line in expression]
            source['expression']=expression
            (PBI/'powerquery').mkdir(exist_ok=True)
            (PBI/'powerquery'/f'{name}.pq').write_text('\n'.join(expression)+'\n',encoding='utf-8')
    write(path,obj)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--rebuild-report',action='store_true');args=parser.parse_args()
    if args.rebuild_report or not (PBI/'Transit.Report/definition/pages/08_archive/page.json').exists():model();report()
    else:configure_paths()
    print('Configured independent M queries and model paths. Open powerbi/Transit.pbip, then Refresh.')
