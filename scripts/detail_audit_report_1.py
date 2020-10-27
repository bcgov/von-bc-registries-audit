#!/usr/bin/python
import os 
import psycopg2
import datetime
import time
import json
import decimal
import requests
import csv

from config import get_connection, get_db_sql, get_sql_record_count, CORP_TYPES_IN_SCOPE, corp_num_with_prefix, bare_corp_num


QUERY_LIMIT = '200000'
REPORT_COUNT = 10000
ERROR_THRESHOLD_COUNT = 5

# value for PROD is "https://orgbook.gov.bc.ca/api/v3"
ORGBOOK_API_URL = os.environ.get('ORGBOOK_API_URL', 'http://localhost:8081/api/v3')
TOPIC_QUERY = "/topic/registration.registries.ca/"
TOPIC_NAME_SEARCH = "/search/topic?inactive=false&latest=true&revoked=false&name="
TOPIC_ID_SEARCH = "/search/topic?inactive=false&latest=true&revoked=false&topic_id="


"""
Detail audit report - second step.
Reads from the event processor database and writes to a csv file:
- corps queued for future processing (we don't check if these are in orgbook or not)
- all corps in the event processor audit log
"""

corps = []
audit_corps = []
sql1 = """SELECT corp_num FROM event_by_corp_filing WHERE process_date is null;"""
corp_recs = get_db_sql("event_processor", sql1)
if 0 < len(corp_recs):
    for corp_rec in corp_recs:
        corps.append({'corp_num': corp_rec['corp_num']})

sql3 = """SELECT corp_num, corp_type FROM CORP_AUDIT_LOG;"""
corp_audit_recs = get_db_sql("event_processor", sql3)
if 0 < len(corp_audit_recs):
    for corp_rec in corp_audit_recs:
        audit_corps.append({'corp_num': corp_rec['corp_num'], 'corp_type': corp_rec['corp_type']})


with open('event_future_corps.csv', mode='w') as corp_file:
    fieldnames = ["corp_num"]
    corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    corp_writer.writeheader()
    for corp in corps:
        corp_writer.writerow(corp)

with open('event_audit_corps.csv', mode='w') as corp_file:
    fieldnames = ["corp_num", "corp_type"]
    corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    corp_writer.writeheader()
    for corp in audit_corps:
        corp_writer.writerow(corp)

