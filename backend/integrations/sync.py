"""
Синхронизация данных из goszakup.gov.kz в локальную БД
"""
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

# КАТО коды районов Алматинской области
DISTRICT_KATO = {
    'ENB': '194211000',  # Енбекшиказахский
    'ILE': '194411000',  # Илийский
    'KAR': '194611000',  # Карасайский
    'TAL': '194811000',  # Талгарский
    'ZHM': '194311000',  # Жамбылский
    'BLK': '194111000',  # Балхашский
    'ALK': '194011000',  # Алакөл
    'KEG': '194511000',  # Кегенский
    'RAY': '194711000',  # Райымбекский
    'UYG': '194911000',  # Уйгурский
}

def sync_contracts_from_goszakup(district_code: str = None, year: int = None):
    """
    Синхронизировать контракты из goszakup в локальную таблицу procurement_contract
    Вызывается вручную из Django admin или через Celery задачу
    """
    from integrations.goszakup import get_contracts, is_connected
    from procurement.models import ProcurementContract
    from regions.models import District

    if not is_connected():
        logger.warning('goszakup API недоступен — токен не задан')
        return {'status': 'error', 'message': 'API токен не задан. Добавьте GOSZAKUP_TOKEN в .env'}

    codes = [district_code] if district_code else list(DISTRICT_KATO.keys())
    synced = 0
    errors = 0

    for code in codes:
        try:
            district = District.objects.get(code=code)
        except District.DoesNotExist:
            continue

        try:
            data = get_contracts(limit=500)
            items = data.get('items', data) if isinstance(data, dict) else data

            for item in items:
                try:
                    contract_year = year or (
                        int(item.get('signDate', '')[:4]) if item.get('signDate') else 2024
                    )
                    ProcurementContract.objects.update_or_create(
                        contract_number=item.get('contractNo', f'GZ-{item.get("id")}'),
                        defaults={
                            'district': district,
                            'customer_name': item.get('customerNameRu', ''),
                            'customer_bin':  item.get('customerBin', ''),
                            'supplier_name': item.get('supplierNameRu', ''),
                            'supplier_bin':  item.get('supplierBiin', ''),
                            'subject':       item.get('refSubjectType', {}).get('nameRu', '') if isinstance(item.get('refSubjectType'), dict) else '',
                            'amount':        Decimal(str(item.get('contractSum', 0) or 0)),
                            'year':          contract_year,
                            'status':        'active' if item.get('refContractStatus', {}).get('nameRu') == 'Исполнен' else 'completed',
                        }
                    )
                    synced += 1
                except Exception as e:
                    logger.error(f'Ошибка записи контракта: {e}')
                    errors += 1

        except Exception as e:
            logger.error(f'Ошибка получения контрактов для {code}: {e}')

    return {'status': 'ok', 'synced': synced, 'errors': errors}


def check_blacklist(supplier_bin: str) -> bool:
    """Проверить поставщика в реестре недобросовестных"""
    try:
        from integrations.goszakup import get_blacklist
        result = get_blacklist(supplier_bin)
        return bool(result)
    except Exception:
        return False
