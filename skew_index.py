from data_fetchers import fetch_cboe_index


def fetch_skew_index():
    return fetch_cboe_index('SKEW', 'SKEW')
