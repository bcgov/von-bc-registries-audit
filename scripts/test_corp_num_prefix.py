import unittest
from unittest.mock import patch

from config import CORP_TYPES_IN_SCOPE, corp_num_with_prefix
from orgbook_data_audit import compare_bc_reg_orgbook


class CorpNumPrefixTests(unittest.TestCase):
    def test_existing_prefixes_are_preserved(self):
        for corp_type in CORP_TYPES_IN_SCOPE:
            for corp_num in (
                'BC1234567', 'C0123456', 'C1198486', 'C1565383', 'Q0000001',
            ):
                with self.subTest(corp_type=corp_type, corp_num=corp_num):
                    self.assertEqual(
                        corp_num_with_prefix(corp_type, corp_num), corp_num
                    )

    def test_numeric_numbers_keep_existing_prefix_rules(self):
        for corp_type in CORP_TYPES_IN_SCOPE:
            with self.subTest(corp_type=corp_type):
                expected = (
                    'BC1234567' if corp_type in ('BC', 'ULC', 'CC', 'BEN')
                    else '1234567'
                )
                self.assertEqual(
                    corp_num_with_prefix(corp_type, '1234567'), expected
                )

    def test_other_prefixes_are_unchanged_for_other_types(self):
        for corp_type, corp_num in (
            ('CP', 'CP1234567'), ('S', 'S0012345'), ('CUL', 'C2123456'),
            ('GP', 'FM1234567'), ('SP', 'FM1234567'),
        ):
            with self.subTest(corp_type=corp_type, corp_num=corp_num):
                self.assertEqual(corp_num_with_prefix(corp_type, corp_num), corp_num)

    def audit_continued_in_benefit_corp(self, corp_num, orgbook_type):
        full_corp_num = corp_num_with_prefix('BEN', corp_num)
        corp_names = {full_corp_num: 'TEST COMPANY'}
        bc_reg_info = {
            'op_state_typ_cd': 'ACT', 'bn_9': '', 'recognition_dts': '',
            'corp_type': 'BEN', 'corp_class': 'BC',
            'can_jur_typ_cd': '', 'othr_juris_desc': '',
        }
        orgbook_info = {
            'entity_status': 'ACT', 'bus_num': '', 'registration_date': '',
            'home_jurisdiction': 'BC',
        }
        orgbook_types = {} if orgbook_type is None else {corp_num: orgbook_type}
        with patch('orgbook_data_audit.log_error') as log_error, patch(
            'orgbook_data_audit.log_info'
        ) as log_info:
            compare_bc_reg_orgbook(
                {full_corp_num: 'BEN'}, corp_names, {full_corp_num: bc_reg_info},
                [], [], orgbook_types, {corp_num: 'TEST COMPANY'},
                {corp_num: orgbook_info}, [], [], [], [],
            )
        return log_error, log_info

    def test_matching_continued_in_benefit_corps_do_not_report_missing_topics(self):
        for corp_num in ('C1198486', 'C1565383'):
            with self.subTest(corp_num=corp_num):
                log_error, log_info = self.audit_continued_in_benefit_corp(
                    corp_num, 'BEN'
                )
                log_error.assert_not_called()
                log_info.assert_called_once()
                self.assertIn('Missing in OrgBook:      0', log_info.call_args.args[0])

    def test_genuinely_missing_topic_is_still_reported(self):
        log_error, _ = self.audit_continued_in_benefit_corp('C1565383', None)
        self.assertEqual(
            log_error.call_args_list[0].args[0],
            'Topic not found for: C1565383\n',
        )
        self.assertEqual(
            log_error.call_args_list[1].args[0],
            './manage -e prod queueOrganization C1565383\n',
        )

    def test_stale_legal_type_is_reported_instead_of_missing_topic(self):
        log_error, _ = self.audit_continued_in_benefit_corp('C1565383', 'C')
        self.assertEqual(
            log_error.call_args_list[0].args[0],
            'Corp Type mis-match for: C1565383; BC Reg: "BEN", OrgBook: "C"\n',
        )


if __name__ == '__main__':
    unittest.main()
