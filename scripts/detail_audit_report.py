#!/usr/bin/python
import os
import psycopg2
import datetime
import time
import json
import decimal
import requests
import csv

from config import (
    get_connection,
    get_db_sql,
    get_sql_record_count,
    post_db_sql,
    BCREG_SYSTEM_TYPE,
    LEAR_SYSTEM_TYPE,
    CORP_TYPES_IN_SCOPE,
    LEAR_CORP_TYPES_IN_SCOPE,
    corp_num_with_prefix,
    bare_corp_num,
    get_ignore_list
)
from orgbook_data_load import (
    get_orgbook_all_corps,
    get_orgbook_all_corps_csv,
    get_orgbook_missing_relations,
    get_orgbook_missing_relations_csv,
    get_orgbook_active_relations,
    get_orgbook_active_relations_csv,
    get_event_proc_future_corps,
    get_event_proc_future_corps_csv,
    get_bc_reg_corps,
    get_bc_reg_corps_csv,
    get_bc_reg_lear_all_relations,
    get_bc_reg_lear_all_relations_csv,
)
from orgbook_data_audit import compare_bc_reg_orgbook
from rocketchat_hooks import log_error, log_warning, log_info


USE_CSV = (os.environ.get('USE_CSV', 'false').lower() == 'true')
USE_LEAR = (os.environ.get('USE_LEAR', 'false').lower() == 'true')
USE_IGNORE_LIST = (os.environ.get('USE_IGNORE_LIST', 'false').lower() == 'false')
REQUEUE_WRONG_BN_CORPS = (os.environ.get('REQUEUE_WRONG_BN_CORPS', 'false').lower() == 'true')


# mainline
if __name__ == "__main__":
    """
    Detail audit report - final step.
    Reads from the orgbook database and compares:
    - corps in BC Reg that are not in orgbook (or that are in orgbook with a different corp type)
    - corps in orgbook that are *not* in BC Reg database (maybe have been removed?)
    """

    # read from orgbook database
    if USE_CSV:
        (orgbook_corp_types, orgbook_corp_names, orgbook_corp_infos) = get_orgbook_all_corps_csv()
    else:
        (orgbook_corp_types, orgbook_corp_names, orgbook_corp_infos) = get_orgbook_all_corps(USE_LEAR=USE_LEAR)
    if USE_CSV:
        orgbook_corp_missing_relations = get_orgbook_missing_relations_csv()
        orgbook_corp_active_relations = get_orgbook_active_relations_csv()
    else:
        orgbook_corp_missing_relations = get_orgbook_missing_relations(USE_LEAR=USE_LEAR)
        orgbook_corp_active_relations = get_orgbook_active_relations(USE_LEAR=USE_LEAR)

    # corps that are still in the event processor queue waiting to be processed (won't be in orgbook yet)
    if USE_CSV:
        future_corps = get_event_proc_future_corps_csv()
    else:
        future_corps = get_event_proc_future_corps(USE_LEAR=USE_LEAR)

    # check if all the BC Reg corps are in orgbook (with the same corp type)
    if USE_CSV:
        (bc_reg_corp_types, bc_reg_corp_names, bc_reg_corp_infos) = get_bc_reg_corps_csv()
        (bc_reg_owners, bc_reg_firms) = get_bc_reg_lear_all_relations_csv()
    else:
        (bc_reg_corp_types, bc_reg_corp_names, bc_reg_corp_infos) = get_bc_reg_corps(USE_LEAR=USE_LEAR)
        (bc_reg_owners, bc_reg_firms) = get_bc_reg_lear_all_relations()

    ignore_list = get_ignore_list(USE_IGNORE_LIST=USE_IGNORE_LIST, USE_LEAR=USE_LEAR)

    # do the orgbook/bc reg compare
    wrong_bus_num = compare_bc_reg_orgbook(
        bc_reg_corp_types,
        bc_reg_corp_names,
        bc_reg_corp_infos,
        bc_reg_owners,
        bc_reg_firms,
        orgbook_corp_types,
        orgbook_corp_names,
        orgbook_corp_infos,
        orgbook_corp_missing_relations,
        orgbook_corp_active_relations,
        future_corps,
        ignore_list,
        USE_LEAR=USE_LEAR,
    )

    if 0 < len(wrong_bus_num):
        if not USE_LEAR:
            bn_requeue_sql = """
                WITH rows AS (
                    insert into event_by_corp_filing
                    (system_type_cd, corp_num, prev_event_id, prev_event_date, last_event_id, last_event_date, entry_date)
                    select ebcf.system_type_cd, bc_reg_corp_num, 0, '0001-01-01', ebcf.last_event_id, ebcf.last_event_date, now()
                    from event_by_corp_filing ebcf
                    cross join
                    unnest(ARRAY[
                    $BN_CORP_LIST
                    ])
                    bc_reg_corp_num
                    where record_id = (select max(record_id) from event_by_corp_filing where system_type_cd = 'BC_REG')
                    RETURNING 1
                )
                SELECT count(*) FROM rows;
                """
            wrong_bus_num_str = str(wrong_bus_num)
            wrong_bus_num_str = wrong_bus_num_str.replace("'BC", "'")
            bn_requeue_sql = bn_requeue_sql.replace("$BN_CORP_LIST", wrong_bus_num_str)
            if REQUEUE_WRONG_BN_CORPS and not USE_CSV:
                log_error("Executing: " + bn_requeue_sql)
                count = post_db_sql("event_processor", bn_requeue_sql)
                log_error("Inserted row count: " + str(count))
            else:
                log_error("SQL to fix BN's: " + bn_requeue_sql)
        else:
            bn_requeue_sql = """
                WITH rows AS (
                    insert into event_by_corp_filing
                    (system_type_cd, corp_num, prev_event_id, prev_event_date, last_event_id, last_event_date, entry_date)
                    select ebcf.system_type_cd, bc_reg_corp_num, 0, '0001-01-01', ebcf.last_event_id, ebcf.last_event_date, now()
                    from event_by_corp_filing ebcf
                    cross join
                    unnest(ARRAY[
                    $BN_CORP_LIST
                    ])
                    bc_reg_corp_num
                    where record_id = (select max(record_id) from event_by_corp_filing where system_type_cd = 'BCREG_LEAR')
                    RETURNING 1
                )
                SELECT count(*) FROM rows;
                """
            wrong_bus_num_str = str(wrong_bus_num)
            bn_requeue_sql = bn_requeue_sql.replace("$BN_CORP_LIST", wrong_bus_num_str)
            if REQUEUE_WRONG_BN_CORPS and not USE_CSV:
                log_error("Executing: " + bn_requeue_sql)
                count = post_db_sql("event_processor", bn_requeue_sql)
                log_error("Inserted row count: " + str(count))
            else:
                log_error("SQL to fix BN's: " + bn_requeue_sql)
