#!/usr/bin/python
import os 
import psycopg2
import datetime
import time
import pytz
import json
import decimal
import requests
import csv

from config import (
    get_connection,
    get_db_sql,
    get_sql_record_count,
    BCREG_SYSTEM_TYPE,
    LEAR_SYSTEM_TYPE,
    CORP_TYPES_IN_SCOPE,
    LEAR_CORP_TYPES_IN_SCOPE,
    corp_num_with_prefix,
    bare_corp_num,
    is_valid_corp_num,
)


QUERY_LIMIT = '200000'
REPORT_COUNT = 10000
ERROR_THRESHOLD_COUNT = 5

# default is to run the audit vs the "*_version" tables
AUDIT_LEAR_MASTER = (os.environ.get('AUDIT_LEAR_MASTER', 'false').lower() == 'true')

# value for PROD is "https://orgbook.gov.bc.ca/api/v3"
ORGBOOK_API_URL = os.environ.get('ORGBOOK_API_URL', 'http://localhost:8081/api/v3')
TOPIC_QUERY = "/topic/registration.registries.ca/"
TOPIC_NAME_SEARCH = "/search/topic?inactive=false&latest=true&revoked=false&name="
TOPIC_ID_SEARCH = "/search/topic?inactive=false&latest=true&revoked=false&topic_id="


def get_bc_reg_corps(USE_LEAR: bool = False):
    """
    Reads all corps and corp types from the BC Reg database and writes to a csv file.
    """

    # short circuit for new LEAR database
    if USE_LEAR:
        return get_bc_reg_lear_corps()
    else:
        return get_bc_reg_colin_corps()


def get_bc_reg_colin_corps():
    """
    Reads all corps and corp types from the BC Reg database and writes to a csv file.
    """

    # run this query against BC Reg database:
    sql1 = """
    select corp.corp_num, corp.corp_typ_cd, corp.recognition_dts, corp.bn_9,
        corp_name.corp_nme, corp_name_as.corp_nme corp_nme_as
    from bc_registries.corporation corp
    left join bc_registries.corp_name corp_name
        on corp_name.corp_num = corp.corp_num
        and corp_name.end_event_id is null
        and corp_name.corp_name_typ_cd in ('CO','NB')
    left join bc_registries.corp_name corp_name_as
        on corp_name_as.corp_num = corp.corp_num
        and corp_name_as.end_event_id is null
        and corp_name_as.corp_name_typ_cd in ('AS')
    where corp.corp_num not in (
        select corp_num from bc_registries.corp_state where state_typ_cd = 'HWT');
    """

    sql2 = """
    select corp.corp_num, corp.corp_typ_cd, corp.recognition_dts, corp.bn_9,
        jurisdiction.can_jur_typ_cd, jurisdiction.xpro_typ_cd, jurisdiction.othr_juris_desc,
        corp_state.state_typ_cd, corp_op_state.op_state_typ_cd, corp_type.corp_class
    from bc_registries.corporation corp
    left join bc_registries.corp_type
        on corp_type.corp_typ_cd = corp.corp_typ_cd
    left join bc_registries.jurisdiction
        on jurisdiction.corp_num = corp.corp_num
        and jurisdiction.end_event_id is null
    left join bc_registries.corp_state
        on corp_state.corp_num = corp.corp_num
        and corp_state.end_event_id is null
    left join bc_registries.corp_op_state
        on corp_op_state.state_typ_cd = corp_state.state_typ_cd
    where corp.corp_num not in (
        select corp_num from bc_registries.corp_state where state_typ_cd = 'HWT');
    """

    bc_reg_corps = {}
    bc_reg_corp_types = {}
    bc_reg_corp_names = {}
    bc_reg_count = 0
    with open('export/bc_reg_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num", "corp_type", "corp_name", "recognition_dts", "bn_9", "can_jur_typ_cd", "xpro_typ_cd", "othr_juris_desc", "state_typ_cd", "op_state_typ_cd", "corp_class"]
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
                corp_name = bc_reg_rec['corp_nme_as'] if (bc_reg_rec['corp_nme_as'] and 0 < len(bc_reg_rec['corp_nme_as'])) else bc_reg_rec['corp_nme']
                bc_reg_corp = {
                    "corp_num": full_corp_num,
                    "corp_type": bc_reg_rec['corp_typ_cd'],
                    "corp_name": corp_name,
                    "recognition_dts": bc_reg_rec['recognition_dts'],
                    "bn_9": bc_reg_rec['bn_9'],
                    "can_jur_typ_cd": "",
                    "xpro_typ_cd": "",
                    "othr_juris_desc": "",
                    "state_typ_cd": "",
                    "op_state_typ_cd": "",
                    "corp_class": "",
                }
                bc_reg_corps[full_corp_num] = bc_reg_corp
                bc_reg_corp_types[bc_reg_corp["corp_num"]] = bc_reg_corp["corp_type"]
                bc_reg_corp_names[bc_reg_corp["corp_num"]] = bc_reg_corp["corp_name"]

        bc_reg_recs_2 = get_db_sql("bc_registries", sql2)
        for bc_reg_rec in bc_reg_recs_2:
            if bc_reg_rec['corp_typ_cd'] in CORP_TYPES_IN_SCOPE:
                full_corp_num = corp_num_with_prefix(bc_reg_rec['corp_typ_cd'], bc_reg_rec['corp_num'])
                if full_corp_num in bc_reg_corps:
                    bc_reg_corp = bc_reg_corps[full_corp_num]
                else:
                    bc_reg_corp = {
                        "corp_num": full_corp_num,
                        "corp_type": bc_reg_rec['corp_typ_cd'],
                        "corp_name": "",
                        "recognition_dts": bc_reg_rec['recognition_dts'],
                        "bn_9": bc_reg_rec['bn_9'],
                    }
                bc_reg_corp["can_jur_typ_cd"] = bc_reg_rec['can_jur_typ_cd']
                bc_reg_corp["xpro_typ_cd"] = bc_reg_rec['xpro_typ_cd']
                bc_reg_corp["othr_juris_desc"] = bc_reg_rec['othr_juris_desc']
                bc_reg_corp["state_typ_cd"] = bc_reg_rec['state_typ_cd']
                bc_reg_corp["op_state_typ_cd"] = bc_reg_rec['op_state_typ_cd']
                bc_reg_corp["corp_class"] = bc_reg_rec['corp_class']
                bc_reg_corps[full_corp_num] = bc_reg_corp

        for full_corp_num in bc_reg_corps:
            bc_reg_corp = bc_reg_corps[full_corp_num]
            corp_writer.writerow(bc_reg_corp)

    return get_bc_reg_corps_csv()


def get_bc_reg_corps_csv():
    """
    Check if all the BC Reg corps are in orgbook (with the same corp type)
    """
    bc_reg_corp_types = {}
    bc_reg_corp_names = {}
    bc_reg_corp_infos = {}
    with open('export/bc_reg_corps.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            bc_reg_corp_types[row["corp_num"]] = row["corp_type"]
            bc_reg_corp_names[row["corp_num"]] = row["corp_name"]

            bc_reg_corp_infos[row["corp_num"]] = {
                "corp_num": row["corp_num"],
                "corp_type": row["corp_type"],
                "corp_name": row["corp_name"],
                "recognition_dts": row["recognition_dts"],
                "bn_9": row["bn_9"],
                "can_jur_typ_cd": row["can_jur_typ_cd"],
                "xpro_typ_cd": row["xpro_typ_cd"],
                "othr_juris_desc": row["othr_juris_desc"],
                "state_typ_cd": row["state_typ_cd"],
                "op_state_typ_cd": row["op_state_typ_cd"],
                "corp_class": row["corp_class"],
            }

    return (bc_reg_corp_types, bc_reg_corp_names, bc_reg_corp_infos)


def get_bc_reg_lear_corps():
    """
    Reads all corps and corp types from the BC Reg LEAR database and writes to a csv file.
    """

    # run this query against BC Reg LEAR database:
    if AUDIT_LEAR_MASTER:
        sql1 = """
            select
                identifier as corp_num,
                legal_type as corp_typ_cd,
                founding_date as recognition_dts,
                tax_id as bn_9,
                legal_name as corp_nme,
                '' as corp_nme_as,
                'BC' as can_jur_typ_cd,
                '' as xpro_typ_cd,
                '' as othr_juris_desc,
                state as state_typ_cd,
                '' as corp_class
            from businesses
            where legal_type in ('SP', 'GP');
        """
    else:
        sql1 = """
            select
                ver.identifier as corp_num,
                ver.legal_type as corp_typ_cd,
                ver.founding_date as recognition_dts,
                bus.tax_id as bn_9,
                ver.legal_name as corp_nme,
                '' as corp_nme_as,
                'BC' as can_jur_typ_cd,
                '' as xpro_typ_cd,
                '' as othr_juris_desc,
                ver.state as state_typ_cd,
                '' as corp_class
            from businesses bus, businesses_version ver
            where bus.legal_type in ('SP', 'GP')
              and bus.identifier = ver.identifier
              and ver.end_transaction_id is null;
    """

    bc_reg_corps = {}
    bc_reg_corp_types = {}
    bc_reg_corp_names = {}
    bc_reg_count = 0
    with open('export/bc_reg_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num", "corp_type", "corp_name", "recognition_dts", "bn_9", "can_jur_typ_cd", "xpro_typ_cd", "othr_juris_desc", "state_typ_cd", "op_state_typ_cd", "corp_class"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()

        print("Get corp stats from BC Registries LEAR DB", datetime.datetime.now())
        start_time = time.perf_counter()
        processed_count = 0
        bc_reg_recs = get_db_sql("bc_reg_lear", sql1)
        for bc_reg_rec in bc_reg_recs:
            if bc_reg_rec['corp_typ_cd'] in LEAR_CORP_TYPES_IN_SCOPE:
                bc_reg_count = bc_reg_count + 1
                full_corp_num = corp_num_with_prefix(bc_reg_rec['corp_typ_cd'], bc_reg_rec['corp_num'])
                corp_name = bc_reg_rec['corp_nme']
                bn_9 = ""
                # take the first 9 digist as the BN9, but only if there are 9 or more digits
                # (otherwise assume it's just bad data)
                if bc_reg_rec['bn_9'] and 9 <= len(bc_reg_rec['bn_9']):
                    bn_9 = bc_reg_rec['bn_9'][:9]
                state_type = 'ACT' if bc_reg_rec['state_typ_cd'] == 'ACTIVE' else 'HIS'
                bc_reg_corp = {
                    "corp_num": full_corp_num,
                    "corp_type": bc_reg_rec['corp_typ_cd'],
                    "corp_name": corp_name,
                    "recognition_dts": bc_reg_rec['recognition_dts'].astimezone(pytz.utc).isoformat(),
                    "bn_9": bn_9,
                    "can_jur_typ_cd": bc_reg_rec['can_jur_typ_cd'],
                    "xpro_typ_cd": bc_reg_rec['xpro_typ_cd'],
                    "othr_juris_desc": bc_reg_rec['othr_juris_desc'],
                    "state_typ_cd": state_type,
                    "op_state_typ_cd": state_type,
                    "corp_class": bc_reg_rec['corp_class'],
                }
                bc_reg_corps[full_corp_num] = bc_reg_corp
                bc_reg_corp_types[bc_reg_corp["corp_num"]] = bc_reg_corp["corp_type"]
                bc_reg_corp_names[bc_reg_corp["corp_num"]] = bc_reg_corp["corp_name"]

        for full_corp_num in bc_reg_corps:
            bc_reg_corp = bc_reg_corps[full_corp_num]
            corp_writer.writerow(bc_reg_corp)

    return get_bc_reg_corps_csv()


def get_bc_reg_lear_all_relations():
    """
    Reads all ACTIVE corp relationships from the BC Reg LEAR database and writes to a csv file.
    """

    # run this query against BC Reg LEAR database:
    sql1 = """
        select
          b.identifier         as firm
          ,p.identifier        as owner
          ,p.organization_name as owner_name
          from parties         p
              ,party_roles     r
              ,businesses      b
          where r.party_id=p.id
            and r.business_id = b.id
            and p.party_type='organization'
            and p.identifier is not null
            and r.role in ('proprietor')
            and r.cessation_date is null;
    """

    bc_reg_owners = {}
    bc_reg_firms = {}
    bc_reg_count = 0
    with open('export/bc_reg_relations.csv', mode='w') as corp_file:
        fieldnames = ["firm", "owner", "owner_name"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()

        print("Get corp relations from BC Registries LEAR DB", datetime.datetime.now())
        start_time = time.perf_counter()
        processed_count = 0
        bc_reg_recs = get_db_sql("bc_reg_lear", sql1)
        for bc_reg_rec in bc_reg_recs:
            if is_valid_corp_num(bc_reg_rec['owner']) and is_valid_corp_num(bc_reg_rec['firm']):
                bc_reg_relation = {
                    "owner": bc_reg_rec['owner'],
                    "firm": bc_reg_rec['firm'],
                    "owner_name": bc_reg_rec['owner_name'],
                }
                bc_reg_owners[bc_reg_rec['owner']] = bc_reg_relation
                bc_reg_firms[bc_reg_rec['firm']] = bc_reg_relation
                corp_writer.writerow(bc_reg_relation)

    return get_bc_reg_lear_all_relations_csv()


def get_bc_reg_lear_all_relations_csv():
    """
    Check if all the BC Reg relations are in orgbook
    """
    bc_reg_owners = []
    bc_reg_firms = []
    with open('export/bc_reg_relations.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            bc_reg_relation = {
                "owner": row['owner'],
                "firm": row['firm'],
                "owner_name": row['owner_name'],
            }
            bc_reg_owners.append(bc_reg_relation)
            bc_reg_firms.append(bc_reg_relation)

    return (bc_reg_owners, bc_reg_firms)


def get_orgbook_all_corps(USE_LEAR: bool = False):
    """
    Reads all companies from the orgbook database
    """
    conn = None
    try:
        conn = get_connection('org_book')
    except (Exception) as error:
        print(error)
        raise

    if USE_LEAR:
        corp_types_filter = LEAR_CORP_TYPES_IN_SCOPE
    else:
        corp_types_filter = CORP_TYPES_IN_SCOPE

    # get all the corps from orgbook
    print("Get corp stats from OrgBook DB", datetime.datetime.now())
    orgbook_corp_types = {}
    orgbook_corp_names = {}
    orgbook_corp_infos = {}
    with open('export/orgbook_search_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num", "corp_type", "registration_date", "corp_name", "home_jurisdiction", "entity_status", "bus_num"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()

        sql4_a = "select id from credential_type where description = 'registration.registries.ca'"

        sql4_b = "select id from credential_type where description = 'business_number.registries.ca'"

        corp_typ_id = None
        bus_num_id = None
        try:
            cur = conn.cursor()
            cur.execute(sql4_a)
            for row in cur:
                corp_typ_id = row[0]
            cur.close()
            cur = conn.cursor()
            cur.execute(sql4_b)
            for row in cur:
                bus_num_id = row[0]
            cur.close()
        except (Exception) as error:
            print(error)
            raise

        sql4 = """
        select topic.source_id, attribute.value entity_type, attr_reg_dt.value registration_date,
            name.text entity_name, name_as.text entity_name_assumed,
            attr_juris.value home_jurisdiction, attr_status.value entity_status,
            attr_bus_num.value bus_num
            from topic
        left join credential as cred_corp_typ on cred_corp_typ.topic_id = topic.id and cred_corp_typ.latest = true and cred_corp_typ.credential_type_id = """ + str(corp_typ_id) + """
        left join attribute on attribute.credential_id = cred_corp_typ.id and attribute.type = 'entity_type'
        left join attribute attr_reg_dt on attr_reg_dt.credential_id = cred_corp_typ.id and attr_reg_dt.type = 'registration_date'
        left join attribute attr_juris on attr_juris.credential_id = cred_corp_typ.id and attr_juris.type = 'home_jurisdiction'
        left join attribute attr_status on attr_status.credential_id = cred_corp_typ.id and attr_status.type = 'entity_status'
        left join name on name.credential_id = cred_corp_typ.id and name.type = 'entity_name'
        left join name name_as on name_as.credential_id = cred_corp_typ.id and name_as.type = 'entity_name_assumed'
        left join credential as cred_bus_num on cred_bus_num.topic_id = topic.id and cred_bus_num.latest = true and cred_bus_num.credential_type_id = """ + str(bus_num_id) + """
        left join attribute as attr_bus_num on attr_bus_num.credential_id = cred_bus_num.id and attr_bus_num.type = 'business_number'
        """
        try:
            cur = conn.cursor()
            cur.execute(sql4)
            for row in cur:
                # row[1] is the corp_type
                # if row[1] in corp_types_filter:
                # load all orgs and check the filter when running the audit report
                orgbook_corp_types[row[0]] = row[1]
                corp_name = row[4] if (row[4] and 0 < len(row[4])) else row[3]
                orgbook_corp_names[row[0]] = corp_name
                write_corp = {
                    "corp_num": row[0],
                    "corp_type": row[1],
                    "registration_date": row[2],
                    "corp_name":corp_name,
                    "home_jurisdiction": row[5],
                    "entity_status": row[6],
                    "bus_num": row[7],
                }
                corp_writer.writerow(write_corp)
                orgbook_corp_infos[row[0]] = write_corp
            cur.close()
        except (Exception) as error:
            print(error)
            raise

    return get_orgbook_all_corps_csv()


def get_orgbook_all_corps_csv():
    orgbook_corp_types = {}
    orgbook_corp_names = {}
    orgbook_corp_infos = {}
    with open('export/orgbook_search_corps.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            orgbook_corp_types[row["corp_num"]] = row["corp_type"]
            orgbook_corp_names[row["corp_num"]] = row["corp_name"]
            orgbook_corp_infos[row["corp_num"]] = row

    return (orgbook_corp_types, orgbook_corp_names, orgbook_corp_infos)


def get_orgbook_active_relations(USE_LEAR: bool = False):
    """
    Checks orgbook for all active relationships.
    """
    conn = None
    try:
        conn = get_connection('org_book')
    except (Exception) as error:
        print(error)
        raise

    # get all the mis-matched relationships from orgbook
    print("Get all corp relationships from OrgBook DB", datetime.datetime.now())
    orgbook_corp_infos = {}
    with open('export/orgbook_corp_active_relations.csv', mode='w') as corp_file:
        fieldnames = ["rel_id", "credential_id", "source_id_1", "source_id_2", "cred_id", "effective_date", "revoked"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()

        if not USE_LEAR:
            sql = """
                select 
                  t_r.id rel_id, t_r.credential_id credential_id,
                  t_1.source_id source_id_1, t_2.source_id source_id_2,
                  c.id cred_id, c.effective_date effective_date,
                  c.revoked revoked
                from topic_relationship t_r,
                     topic t_1,
                     topic t_2,
                     credential c
                where t_r.topic_id = t_1.id
                  and t_r.related_topic_id = t_2.id
                  and c.id = t_r.credential_id
                  and c.revoked = false;
            """

            try:
                cur = conn.cursor()
                cur.execute(sql)
                for row in cur:
                    write_corp = {
                        "rel_id": row[0],
                        "credential_id": row[1],
                        "source_id_1": row[2],
                        "source_id_2":row[3],
                        "cred_id": row[4],
                        "effective_date": row[5],
                        "revoked": row[6],
                    }
                    corp_writer.writerow(write_corp)
                cur.close()
            except (Exception) as error:
                print(error)
                raise

    return get_orgbook_active_relations_csv()


def get_orgbook_active_relations_csv():
    orgbook_corp_relations = []
    with open('export/orgbook_corp_active_relations.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            orgbook_corp_relations.append(row)

    return orgbook_corp_relations


def get_orgbook_missing_relations(USE_LEAR: bool = False):
    """
    Checks orgbook for missing/mis-matched relationships.
    """
    conn = None
    try:
        conn = get_connection('org_book')
    except (Exception) as error:
        print(error)
        raise

    # get all the mis-matched relationships from orgbook
    print("Get mis-matched corp relationships from OrgBook DB", datetime.datetime.now())
    orgbook_corp_infos = {}
    with open('export/orgbook_corp_missing_relations.csv', mode='w') as corp_file:
        fieldnames = ["tr1_topic_id", "tr1_related_topic_id", "id_1", "s_1", "id_2", "s_2"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()

        if not USE_LEAR:
            sql = """
                select tr1_topic_id, tr1_related_topic_id,
                  t1.id id_1, t1.source_id s_1,
                  t2.id id_2, t2.source_id s_2
                from (
                select * from (
                select 
                  tr1.topic_id tr1_topic_id,
                  tr1.related_topic_id tr1_related_topic_id,
                  tr2.topic_id tr2_topic_id,
                  tr2.related_topic_id tr2_related_topic_id
                from topic_relationship tr1
                full outer join topic_relationship tr2
                   on tr1.topic_id = tr2.related_topic_id
                  and tr1.related_topic_id = tr2.topic_id
                order by tr1.topic_id, tr1.related_topic_id
                ) as related
                where (related.tr2_topic_id is null
                   or related.tr2_related_topic_id is null)
                ) as unrelated,
                  topic as t1,
                  topic as t2
                where t1.id = tr1_topic_id
                  and t2.id = tr1_related_topic_id
                order by tr1_topic_id desc;
            """

            try:
                cur = conn.cursor()
                cur.execute(sql)
                for row in cur:
                    write_corp = {
                        "tr1_topic_id": row[0],
                        "tr1_related_topic_id": row[1],
                        "id_1": row[2],
                        "s_1":row[3],
                        "id_2": row[4],
                        "s_2": row[5],
                    }
                    corp_writer.writerow(write_corp)
                cur.close()
            except (Exception) as error:
                print(error)
                raise

    return get_orgbook_missing_relations_csv()


def get_orgbook_missing_relations_csv():
    orgbook_corp_relations = []
    with open('export/orgbook_corp_missing_relations.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            orgbook_corp_relations.append(row)

    return orgbook_corp_relations


def get_event_proc_future_corps(USE_LEAR: bool = False):
    """
    Reads from the event processor database and writes to a csv file:
    - corps queued for future processing (we don't check if these are in orgbook or not)
    """

    # short circuit for new LEAR database
    if USE_LEAR:
        return get_event_proc_future_db_corps(LEAR_SYSTEM_TYPE)
    else:
        return get_event_proc_future_db_corps(BCREG_SYSTEM_TYPE)


def get_event_proc_future_db_corps(system_type_cd):
    """
    Reads from the event processor database and writes to a csv file:
    - corps queued for future processing (we don't check if these are in orgbook or not)
    """
    corps = []
    future_corps = {}
    sql1 = """SELECT corp_num FROM event_by_corp_filing WHERE process_date is null and SYSTEM_TYPE_CD = '""" + system_type_cd + """';"""
    corp_recs = get_db_sql("event_processor", sql1)
    if 0 < len(corp_recs):
        for corp_rec in corp_recs:
            corps.append({'corp_num': corp_rec['corp_num']})

    with open('export/event_future_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()
        for corp in corps:
            corp_writer.writerow(corp)
            future_corps[corp["corp_num"]] = corp["corp_num"]

    return get_event_proc_future_corps_csv()


def get_event_proc_future_corps_csv():
    """
    Corps that are still in the event processor queue waiting to be processed (won't be in orgbook yet)
    """
    future_corps = {}
    with open('export/event_future_corps.csv', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            future_corps[row["corp_num"]] = row["corp_num"]

    return future_corps


def get_event_proc_audit_corps(USE_LEAR: bool = False):
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

    with open('export/event_audit_corps.csv', mode='w') as corp_file:
        fieldnames = ["corp_num", "corp_type"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        corp_writer.writeheader()
        for corp in audit_corps:
            corp_writer.writerow(corp)

    return audit_corps


def get_agent_wallet_ids():
    """
    Reads from the exported list of wallet id's
    """
    agent_wallet_ids = {}
    with open('export/export-wallet-cred-ids.txt', mode='r') as corp_file:
        corp_reader = csv.DictReader(corp_file)
        for row in corp_reader:
            agent_wallet_ids[row["wallet_id"]] = row["wallet_id"]

    return agent_wallet_ids


def append_agent_wallet_ids(agent_ids):
    """
    Appends agent credential ids to our local cache
    """
    with open('export/export-wallet-cred-ids.txt', mode='a') as corp_file:
        fieldnames = ["type", "wallet_id"]
        corp_writer = csv.DictWriter(corp_file, fieldnames=fieldnames, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        for agent_id in agent_ids:
            corp_writer.writerow({"type": "Indy::Credential", "wallet_id": agent_id["credential_id"]})
