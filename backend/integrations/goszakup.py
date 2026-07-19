"""
Клиент для API goszakup.gov.kz
Документация: https://www.goszakup.gov.kz/ru/developer/ows_v3
Токен: запросить на https://www.goszakup.gov.kz/ru/developer/
"""
import requests
from django.conf import settings

BASE_URL = 'https://www.goszakup.gov.kz/v3'

def _get_token():
    return getattr(settings, 'GOSZAKUP_TOKEN', None)

def _headers():
    token = _get_token()
    if not token:
        raise ValueError('GOSZAKUP_TOKEN не задан в настройках')
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

def is_connected():
    """Проверить что токен задан и API доступен"""
    try:
        r = requests.get(f'{BASE_URL}/contract', headers=_headers(),
                         params={'limit': 1}, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

def get_contracts(customer_bin=None, supplier_bin=None, limit=100, offset=0):
    """Получить контракты"""
    params = {'limit': limit, 'offset': offset}
    if customer_bin:
        params['customer_bin'] = customer_bin
    if supplier_bin:
        params['supplier_bin'] = supplier_bin
    r = requests.get(f'{BASE_URL}/contract', headers=_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def get_contract_by_bin_customer(customer_bin, limit=500):
    """Все контракты заказчика (например отдела акимата)"""
    return get_contracts(customer_bin=customer_bin, limit=limit)

def get_supplier_info(bin_iin):
    """Информация о поставщике"""
    r = requests.get(f'{BASE_URL}/subject/biin/{bin_iin}', headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()

def get_blacklist(bin_iin=None):
    """Реестр недобросовестных поставщиков"""
    if bin_iin:
        r = requests.get(f'{BASE_URL}/rnu/{bin_iin}', headers=_headers(), timeout=15)
    else:
        r = requests.get(f'{BASE_URL}/rnu', headers=_headers(), params={'limit': 200}, timeout=30)
    r.raise_for_status()
    return r.json()

def get_plans(customer_bin):
    """Годовой план закупок заказчика"""
    r = requests.get(f'{BASE_URL}/plans/{customer_bin}', headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()

# GraphQL для сложных запросов
def graphql_query(query: str, variables: dict = None):
    payload = {'query': query}
    if variables:
        payload['variables'] = variables
    r = requests.post(f'{BASE_URL}/graphql', headers=_headers(),
                      json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

# Пример GraphQL: контракты по региону (КАТО код Алматинской области = 194)
CONTRACTS_BY_REGION_QUERY = """
query ContractsByRegion($kato: String!, $limit: Int!) {
  ContractQuery(filter: {kato: $kato}, limit: $limit) {
    id
    contractSum
    supplierBiin
    supplierNameRu
    customerBin
    customerNameRu
    signDate
    contractNo
    refContractStatus { nameRu }
    refSubjectType { nameRu }
  }
}
"""
