#!/usr/bin/python
import os
import psycopg2
import sys

from config import (
    get_connection,
    get_db_sql,
    get_sql_record_count,
    CORP_TYPES_IN_SCOPE,
    corp_num_with_prefix,
    bare_corp_num,
    is_valid_corp_num
)


all_companies = []


def get_related_companies(corp_num):
    sql = """
            select
              b.identifier         as firm
              ,p.identifier        as owner
              ,p.organization_name as owner_name
              from parties_version p
                  ,party_roles_version r
                  ,businesses      b
              where r.party_id=p.id
                and r.business_id = b.id
                and p.party_type='organization'
                and r.role in ('proprietor')
                and (b.identifier = %s or p.identifier = %s);
          """

    bc_reg_recs = get_db_sql("bc_reg_lear", sql, (corp_num, corp_num))
    corps = []
    for bc_reg_rec in bc_reg_recs:
        if is_valid_corp_num(bc_reg_rec['owner']) and not (bc_reg_rec['owner'] in all_companies):
            corps.append(bc_reg_rec['owner'])
            all_companies.append(bc_reg_rec['owner'])
        if is_valid_corp_num(bc_reg_rec['firm']) and not (bc_reg_rec['firm'] in all_companies):
            corps.append(bc_reg_rec['firm'])
            all_companies.append(bc_reg_rec['firm'])

    return corps


def get_related_companies_recursive(corp_num):
    corps = get_related_companies(corp_num)
    for related_corp_num in corps:
        get_related_companies_recursive(related_corp_num)


# mainline
if __name__ == "__main__":
    # start with a list of companies on the command line (index 0 is the script name)
    for arg in sys.argv[1:]:
        if is_valid_corp_num(arg):
            get_related_companies_recursive(arg)

    # build lists of corp_nums for each database
    orgbook_corp_nums = []
    bcreg_corp_nums = []
    lear_corp_nums = []
    colin_corp_nums = []
    for corp_num in all_companies:
        s_corp_num = "'" + corp_num + "'"
        print(s_corp_num)
        orgbook_corp_nums.append(s_corp_num)
        bcreg_corp_nums.append(s_corp_num)
        if corp_num.startswith("BC"):
            b_corp_num = "'" + corp_num[2:] + "'"
            bcreg_corp_nums.append(b_corp_num)
            colin_corp_nums.append(b_corp_num)
        elif corp_num.startswith("FM"):
            lear_corp_nums.append(s_corp_num)
        else:
            colin_corp_nums.append(s_corp_num)

    # print SQL's for deleting corps from OrgBook
    delete_sqls_orgbook = {
        'attribute': 'delete from attribute where credential_id in (select id from credential where credential_set_id in (select id from credential_set where topic_id in (select id from topic where source_id in (!!corp_nums!!))));',
        'claim': 'delete from claim where credential_id in (select id from credential where credential_set_id in (select id from credential_set where topic_id in (select id from topic where source_id in (!!corp_nums!!))));',
        'name': 'delete from name where credential_id in (select id from credential where credential_set_id in (select id from credential_set where topic_id in (select id from topic where source_id in (!!corp_nums!!))));',
        'credential': 'delete from credential where credential_set_id in (select id from credential_set where topic_id in (select id from topic where source_id in (!!corp_nums!!)));',
        'credential_set': 'delete from credential_set where topic_id in (select id from topic where source_id in (!!corp_nums!!));',
        'hookable_cred': 'delete from hookable_cred where corp_num in (!!corp_nums!!);',
        'topic_relationship': 'delete from topic_relationship where topic_id in (select id from topic where source_id in (!!corp_nums!!)) or related_topic_id in (select id from topic where source_id in (!!corp_nums!!));',
        'topic': 'delete from topic where source_id in (!!corp_nums!!);',
    }
    print(">>> OrgBook:")
    corp_nums = ','.join(str(x) for x in orgbook_corp_nums)
    for idx, table in enumerate(delete_sqls_orgbook):
        x_sql = delete_sqls_orgbook[table].replace("!!corp_nums!!", corp_nums)
        print("")
        print(x_sql)
    print("")

    # print SQL's for queuing corps in BC Reg Isser
    delete_sqls_bcreg = {
        'credential_log': 'delete from credential_log where corp_num in (!!corp_nums!!);',
        'corp_history_log': 'delete from corp_history_log where corp_num in (!!corp_nums!!);',
        'event_by_corp_filing': 'delete from event_by_corp_filing where corp_num in (!!corp_nums!!);',
    }
    print(">>> BC Reg Issuer:")
    corp_nums = ','.join(str(x) for x in bcreg_corp_nums)
    for idx, table in enumerate(delete_sqls_bcreg):
        x_sql = delete_sqls_bcreg[table].replace("!!corp_nums!!", corp_nums)
        print("")
        print(x_sql)
    print("")

    insert_sqls_bcreg = {
        'lear': """insert into event_by_corp_filing
(system_type_cd, corp_num, prev_event_id, prev_event_date, last_event_id, last_event_date, entry_date)
select ebcf.system_type_cd, bc_reg_corp_num, 0, '0001-01-01', ebcf.last_event_id, ebcf.last_event_date, now()
from event_by_corp_filing ebcf
cross join 
unnest(ARRAY[
    !!corp_nums!!
]) 
bc_reg_corp_num
where record_id = (select max(record_id) from event_by_corp_filing where system_type_cd = 'BCREG_LEAR');""",
        'colin': """insert into event_by_corp_filing
(system_type_cd, corp_num, prev_event_id, prev_event_date, last_event_id, last_event_date, entry_date)
select ebcf.system_type_cd, bc_reg_corp_num, 0, '0001-01-01', ebcf.last_event_id, ebcf.last_event_date, now()
from event_by_corp_filing ebcf
cross join 
unnest(ARRAY[
    !!corp_nums!!
]) 
bc_reg_corp_num
where record_id = (select max(record_id) from event_by_corp_filing where system_type_cd = 'BC_REG');""",
    }
    print(">>> BC Reg Issuer:")
    corp_nums = ','.join(str(x) for x in lear_corp_nums)
    x_sql = insert_sqls_bcreg['lear'].replace("!!corp_nums!!", corp_nums)
    print("")
    print(x_sql)
    corp_nums = ','.join(str(x) for x in colin_corp_nums)
    x_sql = insert_sqls_bcreg['colin'].replace("!!corp_nums!!", corp_nums)
    print("")
    print(x_sql)
    print("")

