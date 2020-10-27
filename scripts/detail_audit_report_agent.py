#!/usr/bin/python
import os 
import psycopg2
import datetime
import time
import json
import decimal
import requests
import csv
import asyncio

from config import get_connection, get_db_sql, get_sql_record_count, CORP_TYPES_IN_SCOPE, corp_num_with_prefix, bare_corp_num


QUERY_LIMIT = '200000'
REPORT_COUNT = 10000
ERROR_THRESHOLD_COUNT = 5

# value for PROD is "https://orgbook.gov.bc.ca/api/v3"
ORGBOOK_API_URL = os.environ.get('ORGBOOK_API_URL', 'http://localhost:8081/api/v3')
TOPIC_QUERY = "/topic/registration.registries.ca/"
TOPIC_NAME_SEARCH = "/search/topic?inactive=false&latest=true&revoked=false&name="
TOPIC_ID_SEARCH = "/search/topic?inactive=false&latest=true&revoked=false&topic_id="

# value for PROD is "https://agent-admin.orgbook.gov.bc.ca/?count=100&start="
AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://localhost:8021/?count=100&start=")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY")


"""
Detail audit report - credential list from orgbook.
Reads from the orgbook database:
- wallet id for each credential
"""

async def process_credential_queue():
    conn = None
    try:
        params = config('org_book')
        conn = psycopg2.connect(**params)
    except (Exception) as error:
        print(error)
        raise

    # get all the corps from orgbook
    print("Get credential stats from OrgBook DB", datetime.datetime.now())
    sql4 = """select 
                  credential.credential_id, credential.id, credential.topic_id, credential.update_timestamp,
                  topic.source_id, credential.credential_type_id, credential_type.description
                from credential, topic, credential_type
                where topic.id = credential.topic_id
                and credential_type.id = credential.credential_type_id
                order by id desc;"""
                #limit 50000;"""
    corp_creds = []
    try:
        cur = conn.cursor()
        cur.execute(sql4)
        for row in cur:
            corp_creds.append({
                'credential_id': row[0], 'id': row[1], 'topic_id': row[2], 'timestamp': row[3],
                'source_id': row[4], 'credential_type_id': row[5], 'credential_type': row[6]
            })
        cur.close()
    except (Exception) as error:
        print(error)
        raise

    i = 0
    print("Checking for valid credentials ...", datetime.datetime.now())
    while True:
        api_key_hdr = {"x-api-key": AGENT_API_KEY}
        url = AGENT_API_URL + str(i+1)
        try:
            if 0 == i % 100000:
                print(i)
            response = requests.get(url, headers=api_key_hdr)
            response.raise_for_status()
            credentials = response.json()["results"]
            # TODO check credentials
            i = i + 100
        except Exception as e:
            print("Exception for:", i)


try:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(process_credential_queue())
except Exception as e:
    print("Exception", e)
    raise

