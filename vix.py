from data_fetchers import fetch_cboe_index


def fetch_vix_index():
    return fetch_cboe_index('VIX', 'CLOSE')
