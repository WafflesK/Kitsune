import cloudscraper
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_scrapper_session(
    useCloudscraper=True,
    retries=10,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504, 423)
):
    session = None
    if useCloudscraper:
        session = cloudscraper.create_scraper()
    else:
        session = Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session