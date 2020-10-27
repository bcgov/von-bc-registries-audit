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
Detail audit report - first step.
Reads all corps and corp types from the BC Reg database and writes to a csv file.
"""

# run this query against BC Reg database:
sql1 = """
select corp.corp_num, corp.corp_typ_cd
from bc_registries.corporation corp
where corp.corp_num not in (
    select corp_num from bc_registries.corp_state where state_typ_cd = 'HWT');
"""

bc_reg_count = 0
with open('bc_reg_corps.csv', mode='w') as corp_file:
    fieldnames = ["corp_num", "corp_type"]
    corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    corp_writer.writeheader()

    print("Get corp stats from BC Registries DB", datetime.datetime.now())
    start_time = time.perf_counter()
    processed_count = 0
    bc_reg_corps = []
    bc_reg_recs = get_db_sql("bc_registries", sql1)
    for bc_reg_rec in bc_reg_recs:
        if bc_reg_rec['corp_typ_cd'] in CORP_TYPES_IN_SCOPE:
            bc_reg_count = bc_reg_count + 1
            bc_reg_corp = {
                "corp_num": corp_num_with_prefix(bc_reg_rec['corp_typ_cd'], bc_reg_rec['corp_num']),
                "corp_type": bc_reg_rec['corp_typ_cd']
            }
            bc_reg_corps.append(bc_reg_corp)
            corp_writer.writerow(bc_reg_corp)
            processed_count = processed_count + 1
            if processed_count >= 10000:
                processing_time = time.perf_counter() - start_time
                print("Processing:", bc_reg_count, processing_time)
                processed_count = 0
