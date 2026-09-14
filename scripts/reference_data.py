"""Versioned name dictionary transcribed from LTA's 2026 system map; no invented coordinates."""
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GROUPS={
'EW':'Pasir Ris|Tampines|Simei|Tanah Merah|Bedok|Kembangan|Eunos|Paya Lebar|Aljunied|Kallang|Lavender|Bugis|City Hall|Raffles Place|Tanjong Pagar|Outram Park|Tiong Bahru|Redhill|Queenstown|Commonwealth|Buona Vista|Dover|Clementi|Jurong East|Chinese Garden|Lakeside|Boon Lay|Pioneer|Joo Koon|Gul Circle|Tuas Crescent|Tuas West Road|Tuas Link',
'NS':'Jurong East|Bukit Batok|Bukit Gombak|Choa Chu Kang|Yew Tee|~|Kranji|Marsiling|Woodlands|Admiralty|Sembawang|Canberra|Yishun|Khatib|Yio Chu Kang|Ang Mo Kio|Bishan|Braddell|Toa Payoh|Novena|Newton|Orchard|Somerset|Dhoby Ghaut|City Hall|Raffles Place|Marina Bay|Marina South Pier',
'NE':'HarbourFront|~|Outram Park|Chinatown|Clarke Quay|Dhoby Ghaut|Little India|Farrer Park|Boon Keng|Potong Pasir|Woodleigh|Serangoon|Kovan|Hougang|Buangkok|Sengkang|Punggol|Punggol Coast',
'CC':'Dhoby Ghaut|Bras Basah|Esplanade|Promenade|Nicoll Highway|Stadium|Mountbatten|Dakota|Paya Lebar|MacPherson|Tai Seng|Bartley|Serangoon|Lorong Chuan|Bishan|Marymount|Caldecott|~|Botanic Gardens|Farrer Road|Holland Village|Buona Vista|one-north|Kent Ridge|Haw Par Villa|Pasir Panjang|Labrador Park|Telok Blangah|HarbourFront|Keppel|Cantonment|Prince Edward Road|Marina Bay|Bayfront',
'DT':'Bukit Panjang|Cashew|Hillview|Hume|Beauty World|King Albert Park|Sixth Avenue|Tan Kah Kee|Botanic Gardens|Stevens|Newton|Little India|Rochor|Bugis|Promenade|Bayfront|Downtown|Telok Ayer|Chinatown|Fort Canning|Bencoolen|Jalan Besar|Bendemeer|Geylang Bahru|Mattar|MacPherson|Ubi|Kaki Bukit|Bedok North|Bedok Reservoir|Tampines West|Tampines|Tampines East|Upper Changi|Expo',
'TE':'Woodlands North|Woodlands|Woodlands South|Springleaf|Lentor|Mayflower|Bright Hill|Upper Thomson|Caldecott|~|Stevens|Napier|Orchard Boulevard|Orchard|Great World|Havelock|Outram Park|Maxwell|Shenton Way|Marina Bay|~|Gardens by the Bay|Tanjong Rhu|Katong Park|Tanjong Katong|Marine Parade|Marine Terrace|Siglap|Bayshore',
'BP':'Choa Chu Kang|South View|Keat Hong|Teck Whye|Phoenix|Bukit Panjang|Petir|Pending|Bangkit|Fajar|Segar|Jelapang|Senja',
'SE':'Compassvale|Rumbia|Bakau|Kangkar|Ranggung','SW':'Cheng Lim|Farmway|Kupang|Thanggam|Fernvale|Layar|Tongkang|Renjong',
'PE':'Cove|Meridian|Coral Edge|Riviera|Kadaloor|Oasis|Damai','PW':'Sam Kee|Teck Lee|Punggol Point|Samudera|Nibong|Sumang|Soo Teck',
'CG':'Expo|Changi Airport'}
def main():
    path=ROOT/'data/reference/rail_names.csv'
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['code','name','source'])
        for prefix,names in GROUPS.items():
            for i,name in enumerate(names.split('|'),1):
                if name!='~':w.writerow([prefix+str(i),name,'LTA system map SM-26-01-EN (21 July 2026)'])
        w.writerows([['STC','Sengkang','LTA system map SM-26-01-EN'],['PTC','Punggol','LTA system map SM-26-01-EN']])
if __name__=='__main__':main()
