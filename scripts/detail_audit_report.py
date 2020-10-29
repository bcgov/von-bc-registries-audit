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
from orgbook_data_load import get_orgbook_all_corps
from orgbook_data_audit import compare_bc_reg_orgbook


# mainline
if __name__ == "__main__":
    """
    Detail audit report - final step.
    Reads from the orgbook database and compares:
    - corps in BC Reg that are not in orgbook (or that are in orgbook with a different corp type)
    - corps in orgbook that are *not* in BC Reg database (maybe have been removed?)
    - corps in event processor audit logs that are not in BC Reg database (maybe have been removed?)
    - corps in BC Reg database that are not in the event processor audit logs
    """

    # read from orgbook database
    orgbook_corp_types = get_orgbook_all_corps()

    # corps that are still in the event processor queue waiting to be processed (won't be in orgbook yet)
    future_corps = {}
    with open('event_future_corps.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            future_corps[row["corp_num"]] = row["corp_num"]

    # check if all the BC Reg corps are in orgbook (with the same corp type)
    bc_reg_corp_types = {}
    with open('bc_reg_corps.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            bc_reg_corp_types[row["corp_num"]] = row["corp_type"]

    compare_bc_reg_orgbook(bc_reg_corp_types, orgbook_corp_types, future_corps)
