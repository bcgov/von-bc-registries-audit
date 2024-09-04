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
from orgbook_data_load import get_orgbook_all_corps, get_orgbook_missing_relations, get_orgbook_active_relations

USE_LEAR = (os.environ.get('USE_LEAR', 'false').lower() == 'true')


# mainline
if __name__ == "__main__":
    """
    Detail audit report - final step.
    Reads from the orgbook database and compares:
    """
    # read from orgbook database
    (orgbook_corp_types, orgbook_corp_names, orgbook_corp_infos) = get_orgbook_all_corps(USE_LEAR=USE_LEAR)
    orgbook_corp_missing_relations = get_orgbook_missing_relations(USE_LEAR=USE_LEAR)
    orgbook_corp_active_relations = get_orgbook_active_relations(USE_LEAR=USE_LEAR)
