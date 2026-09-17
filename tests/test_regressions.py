"""Regression checks for the original zero/error-text contamination."""
import utils


def test_error_message_cannot_become_a_csv_number():
    assert utils.extract_numeric_value('錯誤: HTTP 403; driver exit 0') == ''


def test_failed_zeroes_are_excluded_from_direction():
    for key in ('BOND_10Y', 'NAAIM', 'SKEW'):
        assert '⚠️' in utils.get_indicator_status(key, '0')
