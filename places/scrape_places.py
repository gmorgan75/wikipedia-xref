#!/usr/bin/env python
# 
# Census Reporter geoids for counties are of the form 06000USXXYYYYY
# where XX is the 2-digit state FIPS code and YYYYY is the 5-digit place FIPS code. Together, these are unique nationwide.
# 
# Wikipedia has no list of all census places, so the strategy here is to go through the Gazetteer (the official list of places)
# and attempt to find them on Wikipedia. This is done by constructing a potential page name from the place name and the state name.
# If the URL return a page, then an attempt is made to find the FIPS ID/geoid in the page. In the best case scenario, that is found
# and it matches the Gazetteer's geoid. 
#
# Because this is an indeterminate process, we expect to run this repeatedly. Therefore, taking advantage of scrapelib's caching and
# reading in what was output on the last run can make things more efficient.
#
import unicodecsv
import statestyle
from lxml.html import fromstring
from urlparse import urljoin
from urllib import quote_plus
import re
import os.path

# is this even necessary?
MANUAL_OVERRIDE = {
    '16000US1150000': 'https://en.wikipedia.org/wiki/Washington,_D.C.',
}

OUTPUT_FILE = "../output/places_with_links.csv"

from scrapelib import Scraper, FileCache, HTTPError
BASE_URL = 'https://en.wikipedia.org/wiki/'

COUNTY_LIST = 'https://en.wikipedia.org/wiki/List_of_United_States_counties_and_county-equivalents'
# Municipalities in Puerto Rico are "county-equivalents"
PR_MUNICIPALITIES = 'https://en.wikipedia.org/wiki/Municipalities_of_Puerto_Rico'

# would like to follow robots, but think that the robots parser is broken...
s = Scraper(requests_per_minute=90, follow_robots=False)
s.cache_storage = FileCache('../wikipedia_cache')
s.cache_write_only = False


def trim_place_name(place_name):
    if place_name.endswith(' zona urbana'):
        return place_name.replace(' zona urbana','')
    place_parts = place_name.split()
    if place_parts[-1] in ['CDP','city','town','village', 'municipality', 'borough', 'comunidad']:
        return ' '.join(place_parts[:-1])
    return place_name

def build_url(row):
    place_name = trim_place_name(row['NAME'])
    state = row['USPS']
    state_name = statestyle.get(state).name
    path = u"%s, %s" % (quote_plus(place_name.encode('utf-8')), state_name)
    path = path.replace(' ','_')
    path = path.replace('+','_')
    return urljoin(BASE_URL,path)


ERROR_CONDITIONS = [ '404','error', '' ]
def try_place(row):
    """For every place, build a URL and try it. Return the URL tried and a message describing the result ('confidence').
        Confidence values:
            'no geocode found to test'
            'exact geocode match'
            'nonmatching geocode found'
            '404'
            'error'
    """
    url = build_url(row)

    geoid = row['GEOID']
    try:
        content = s.urlopen(url)
        confidence = ''
        doc = fromstring(content)
        marker = doc.findall('.//a[@title="Geocode"]')
        if len(marker) != 1:
            marker = doc.findall('.//a[@title="Federal Information Processing Standard"]')
        if len(marker) != 1:
            return url, 'no geocode found to test'
        wiki_geocode = marker[0].getparent().getnext().text_content()
        wiki_geocode = wiki_geocode.replace('-','')
        if re.match('^\d{7}.*',wiki_geocode):
            wiki_geocode = wiki_geocode[:7]

        if wiki_geocode == geoid:
            return url, 'exact geocode match'
        if len(wiki_geocode) == 5 and geoid.endswith(wiki_geocode):
            return url, 'five digit geocode matches'
        return url, 'nonmatching geocode found'
    except HTTPError:
        return url, '404'
    except Exception, e:
        print u"Error %s for %s" % (e,url)
        return url, 'error'

def load_baseline_data(filename):
    baseline = {} # don't repeat ourselves but we may want to re-run to try new strategies
    try: 
        r = unicodecsv.DictReader(open(filename))
        for row in r:
            if row['wiki_url']:
                baseline[row['GEOID']] = (row['wiki_url'],row['confidence'])
    except IOError, e:
        if e.errno != 2: # if the file doesn't exist, that's not worth reporting. we'll just deal
            print "Error reading %s: %s" % (filename, e)
    return baseline

def try_all_places(retry_404=False,retry_error=True):
    missed = found = 0
    baseline = load_baseline_data(OUTPUT_FILE)
    r = unicodecsv.DictReader(open("Gaz_places_national.txt"),delimiter="\t", encoding='latin-1')
    f = list(r.fieldnames)
    f.append('wiki_url')
    f.append('confidence')
    if os.path.exists(OUTPUT_FILE) and os.path.isfile(OUTPUT_FILE):
        os.rename(OUTPUT_FILE,OUTPUT_FILE+'.bak')
    w = unicodecsv.DictWriter(open(OUTPUT_FILE,"w"),f,encoding='utf-8')
    w.writerow(dict(zip(f,f)))
    for row in r:
        try:
            url, confidence = baseline[row['GEOID']]

            if (confidence == '404' and retry_404) or (confidence == 'error' and retry_error) or not url:
                url, confidence = try_place(row)

        except:    
            url, confidence = try_place(row)
            if not url:
                url = ''
                confidence = ''

        if confidence in ERROR_CONDITIONS:
            missed += 1
        else:
            found += 1

        row['wiki_url'] = url
        row['confidence'] = str(confidence)
        w.writerow(row)
        if (found + missed) % 100 == 0: print (found + missed)
    print "Done."
    print "found %i" % found
    print "missed %i" % missed

if __name__ == '__main__':
    try_all_places()
    