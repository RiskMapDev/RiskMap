from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from django.conf import settings

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integration_status(request):
    """Статус подключения ко всем источникам данных"""
    token = getattr(settings, 'GOSZAKUP_TOKEN', None)

    sources = [
        {
            'id':          'goszakup',
            'name':        'goszakup.gov.kz',
            'description': 'Единый реестр госзакупок',
            'status':      'connected' if token else 'no_token',
            'url':         'https://www.goszakup.gov.kz',
            'data':        ['Контракты', 'Поставщики', 'Планы закупок', 'Недобросовестные поставщики'],
        },
        {
            'id':          'stat',
            'name':        'taldau.stat.gov.kz',
            'description': 'Бюро национальной статистики',
            'status':      'manual',
            'url':         'https://taldau.stat.gov.kz',
            'data':        ['Население по сёлам', 'Промышленные предприятия', 'АПК статистика'],
        },
        {
            'id':          'egov',
            'name':        'data.egov.kz',
            'description': 'Портал открытых данных',
            'status':      'manual',
            'url':         'https://data.egov.kz',
            'data':        ['Объекты строительства', 'Субсидии МСХ', 'ЖКХ объекты'],
        },
        {
            'id':          'osms',
            'name':        'ОСМС (ФМС)',
            'description': 'Фонд медицинского страхования',
            'status':      'pending',
            'url':         'https://fms.kz',
            'data':        ['Застрахованные', 'Работодатели', 'Долги по взносам'],
        },
        {
            'id':          'gbd_ul',
            'name':        'ГБД ЮЛ',
            'description': 'Гос. база данных юридических лиц',
            'status':      'pending',
            'url':         'https://egov.kz',
            'data':        ['Реестр предприятий', 'Заводы и фабрики', 'Владельцы'],
        },
        {
            'id':          'moa',
            'name':        'МСХ (Субсидии)',
            'description': 'Министерство сельского хозяйства',
            'status':      'pending',
            'url':         'https://moa.gov.kz',
            'data':        ['Субсидии по технике', 'Субсидии на воду', 'Получатели субсидий'],
        },
    ]
    return Response({'sources': sources})


@api_view(['POST'])
@permission_classes([IsAdminUser])
def sync_goszakup(request):
    """Запустить синхронизацию данных из goszakup"""
    from integrations.sync import sync_contracts_from_goszakup
    district = request.data.get('district')
    year     = request.data.get('year')
    result   = sync_contracts_from_goszakup(district_code=district, year=year)
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def set_token(request):
    """Сохранить API токен в .env (только для разработки)"""
    token = request.data.get('token', '').strip()
    if not token:
        return Response({'error': 'Токен не указан'}, status=400)
    # Write to .env file
    import os, re
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', '.env')
    env_path = os.path.normpath(env_path)
    try:
        with open(env_path, 'r') as f:
            content = f.read()
        if 'GOSZAKUP_TOKEN' in content:
            content = re.sub(r'GOSZAKUP_TOKEN=.*', f'GOSZAKUP_TOKEN={token}', content)
        else:
            content += f'\nGOSZAKUP_TOKEN={token}\n'
        with open(env_path, 'w') as f:
            f.write(content)
        return Response({'status': 'ok', 'message': 'Токен сохранён. Перезапустите сервер.'})
    except Exception as e:
        return Response({'error': str(e)}, status=500)
