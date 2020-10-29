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


def get_bc_reg_corps():
    """
    Reads all corps and corp types from the BC Reg database and writes to a csv file.
    """

    # run this query against BC Reg database:
    sql1 = """
    select corp.corp_num, corp.corp_typ_cd
    from bc_registries.corporation corp
    where corp.corp_num not in (
        select corp_num from bc_registries.corp_state where state_typ_cd = 'HWT');
    """

    bc_reg_corps = {}
    bc_reg_count = 0
    with open('bc_reg_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num", "corp_type"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()

        print("Get corp stats from BC Registries DB", datetime.datetime.now())
        start_time = time.perf_counter()
        processed_count = 0
        bc_reg_recs = get_db_sql("bc_registries", sql1)
        for bc_reg_rec in bc_reg_recs:
            if bc_reg_rec['corp_typ_cd'] in CORP_TYPES_IN_SCOPE:
                bc_reg_count = bc_reg_count + 1
                full_corp_num = corp_num_with_prefix(bc_reg_rec['corp_typ_cd'], bc_reg_rec['corp_num'])
                bc_reg_corp = {
                    "corp_num": full_corp_num,
                    "corp_type": bc_reg_rec['corp_typ_cd']
                }
                bc_reg_corps[full_corp_num] = bc_reg_corp
                corp_writer.writerow(bc_reg_corp)
                processed_count = processed_count + 1
                if processed_count >= 10000:
                    processing_time = time.perf_counter() - start_time
                    print("Processing:", bc_reg_count, processing_time)
                    processed_count = 0

    return bc_reg_corps


def get_orgbook_all_corps():
    """
    Reads all companies from the orgbook database
    """
    conn = None
    try:
        params = config(section='org_book')
        conn = psycopg2.connect(**params)
    except (Exception) as error:
        print(error)
        raise

    # get all the corps from orgbook
    print("Get corp stats from OrgBook DB", datetime.datetime.now())
    sql4 = """select topic.source_id, attribute.value from topic 
              left join credential on credential.topic_id = topic.id and credential.latest = true and credential_type_id = 1
              left join attribute on attribute.credential_id = credential.id and attribute.type = 'entity_type'"""
    orgbook_corp_types = {}
    try:
        cur = conn.cursor()
        cur.execute(sql4)
        for row in cur:
            orgbook_corp_types[row[0]] = row[1]
        cur.close()
    except (Exception) as error:
        print(error)
        raise

    return orgbook_corp_types


def get_event_proc_future_corps():
    """
    Reads from the event processor database and writes to a csv file:
    - corps queued for future processing (we don't check if these are in orgbook or not)
    """
    corps = []
    sql1 = """SELECT corp_num FROM event_by_corp_filing WHERE process_date is null;"""
    corp_recs = get_db_sql("event_processor", sql1)
    if 0 < len(corp_recs):
        for corp_rec in corp_recs:
            corps.append({'corp_num': corp_rec['corp_num']})

    with open('event_future_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()
        for corp in corps:
            corp_writer.writerow(corp)

    return corps


def get_event_proc_audit_corps():
    """
    Reads from the event processor database and writes to a csv file:
    - all corps in the event processor audit log
    """
    audit_corps = []
    sql3 = """SELECT corp_num, corp_type FROM CORP_AUDIT_LOG;"""
    corp_audit_recs = get_db_sql("event_processor", sql3)
    if 0 < len(corp_audit_recs):
        for corp_rec in corp_audit_recs:
            audit_corps.append({'corp_num': corp_rec['corp_num'], 'corp_type': corp_rec['corp_type']})

    with open('event_audit_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num", "corp_type"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()
        for corp in audit_corps:
            corp_writer.writerow(corp)

    return audit_corps


