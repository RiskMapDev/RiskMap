import os, sys, django, random, decimal
from datetime import date, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth.hashers import make_password
from accounts.models import User
from regions.models import District, Official
from budget.models import BudgetProgram
from procurement.models import ProcurementContract
from construction.models import ConstructionObject
from risks.models import RiskMaterial
from entities.models import LegalEntity
from agro.models import SubsidyRecipient

def d(v): return decimal.Decimal(str(v))

# ── Users ─────────────────────────────────────────────────────────────────────
User.objects.all().delete()
users = [
    dict(username='admin',    password='admin123',   is_superuser=True, is_staff=True, role='superadmin', full_name='Администратор Системы'),
    dict(username='analyst1', password='analyst123', role='analyst',  full_name='Айгерим Бекова'),
    dict(username='manager1', password='manager123', role='manager',  full_name='Серик Жумабеков'),
    dict(username='viewer1',  password='viewer123',  role='viewer',   full_name='Нуржан Алиев'),
]
for u in users:
    pw = u.pop('password')
    obj = User(**u)
    obj.set_password(pw)
    obj.save()
    print(f"Created {obj.username}")

analyst = User.objects.get(username='analyst1')

# ── Districts — реальные данные Алматинской области ───────────────────────────
District.objects.all().delete()

DISTRICTS = [
    # code, name, name_kz, center, pop, area_km2, risk, lat, lng
    ('ALK', 'Алакөл ауданы',          'Алакөл ауданы',          'с. Үшарал',       91200,  39993, 'medium',  45.7,  80.9),
    ('BLK', 'Балхашский район',        'Балқаш ауданы',          'с. Баканас',       27257, 178264, 'medium',  44.8,  74.9),
    ('ENB', 'Енбекшиказахский район',  'Еңбекшіқазақ ауданы',   'г. Есик',         283681,   8300, 'high',   43.35,  77.47),
    ('ZHM', 'Жамбылский район',        'Жамбыл ауданы',          'с. Узынагаш',     134000,   8100, 'low',    43.73,  76.28),
    ('ILE', 'Илийский район',          'Іле ауданы',             'с. Отеген-Батыр', 287000,  12200, 'high',   43.64,  77.13),
    ('KEG', 'Кегенский район',         'Қеген ауданы',           'с. Кеген',         82000,  17500, 'low',    42.99,  79.18),
    ('KAR', 'Карасайский район',       'Қарасай ауданы',         'г. Каскелен',     241000,   3400, 'high',   43.20,  76.62),
    ('RAY', 'Райымбекский район',      'Райымбек ауданы',        'с. Нарынкол',      58000,  33100, 'low',    42.72,  79.98),
    ('TAL', 'Талгарский район',        'Талғар ауданы',          'г. Талгар',       196000,   7200, 'medium', 43.30,  77.25),
    ('UYG', 'Уйгурский район',         'Ұйғыр ауданы',           'с. Чунджа',        74000,  13900, 'medium', 43.56,  79.93),
]

dist_objs = {}
for code, name, name_kz, center, pop, area, risk, lat, lng in DISTRICTS:
    obj = District.objects.create(
        code=code, name=name, name_kz=name_kz, center=center,
        population=pop, area_km2=area, risk_level=risk, lat=lat, lng=lng
    )
    dist_objs[code] = obj
print(f"Districts: {District.objects.count()}")

# ── Officials ─────────────────────────────────────────────────────────────────
Official.objects.all().delete()
AKIMS = {
    'ENB': ('Байедилов Талғат Ескендірұлы',    '+7 727 234-56-78', 'akim.enb@almaty.gov.kz'),
    'ILE': ('Мусаев Бауыржан Серікұлы',         '+7 727 244-11-22', 'akim.ile@almaty.gov.kz'),
    'KAR': ('Қалиев Нұрлан Бекзатұлы',          '+7 727 255-33-44', 'akim.kar@almaty.gov.kz'),
    'TAL': ('Сейітов Ержан Қасымбекұлы',        '+7 727 266-55-66', 'akim.tal@almaty.gov.kz'),
    'ZHM': ('Ахметов Серік Жақсыбекұлы',        '+7 727 277-77-88', 'akim.zhm@almaty.gov.kz'),
    'BLK': ('Бейсенов Қайрат Нұрланұлы',        '+7 727 288-99-00', 'akim.blk@almaty.gov.kz'),
    'ALK': ('Дауренов Асқар Маратұлы',           '+7 727 299-11-22', 'akim.alk@almaty.gov.kz'),
    'KEG': ('Жаңабеков Тимур Бақытбекұлы',      '+7 727 211-33-44', 'akim.keg@almaty.gov.kz'),
    'RAY': ('Мамытбеков Рустем Қайратұлы',       '+7 727 222-55-66', 'akim.ray@almaty.gov.kz'),
    'UYG': ('Абдуллаев Шамиль Тоқтарұлы',       '+7 727 233-77-88', 'akim.uyg@almaty.gov.kz'),
}
for code, (name, phone, email) in AKIMS.items():
    Official.objects.create(
        district=dist_objs[code], full_name=name,
        position='akim', position_name='Аким района',
        phone=phone, email=email
    )
print("Officials created")

# ── Infrastructure / Construction Objects (реальные категории) ─────────────────
ConstructionObject.objects.all().delete()

# Реальная инфраструктура по районам
INFRA = {
    'ENB': [
        ('Школа №5 г. Есик',              'school',   'г. Есик',      'ГУ Отдел образования ЕКР',    'd(780000000)',   78, 'low'),
        ('Больница г. Есик (реконструкция)','hospital','г. Есик',      'ГУ Отдел здравоохранения ЕКР','d(1200000000)',  45, 'medium'),
        ('ФАП с. Шелек',                   'fap',      'с. Шелек',     'ГУ Отдел здравоохранения ЕКР','d(85000000)',    90, 'low'),
        ('ФАП с. Тургень',                 'fap',      'с. Тургень',   'ГУ Отдел здравоохранения ЕКР','d(82000000)',    60, 'low'),
        ('Дом культуры с. Шелек',          'culture',  'с. Шелек',     'ГУ Отдел культуры ЕКР',       'd(320000000)',   30, 'medium'),
        ('Водопровод с. Каракемер',        'water',    'с. Каракемер', 'ГУ ЖКХ ЕКР',                  'd(145000000)',   65, 'low'),
        ('Газоснабжение с. Тескенсу',      'gas',      'с. Тескенсу',  'ГУ ЖКХ ЕКР',                  'd(98000000)',    20, 'high'),
        ('Школа с. Рахат (строительство)', 'school',   'с. Рахат',     'ГУ Отдел образования ЕКР',    'd(920000000)',   15, 'high'),
    ],
    'ILE': [
        ('Школа с. Отеген-Батыр №3',       'school',   'с. Отеген-Батыр','ГУ Отдел образования ИР',   'd(850000000)',   55, 'medium'),
        ('Поликлиника с. Отеген-Батыр',    'hospital', 'с. Отеген-Батыр','ГУ Отдел здравоохранения ИР','d(1800000000)', 40, 'high'),
        ('Водопровод с. Боралдай',         'water',    'с. Боралдай',   'ГУ ЖКХ ИР',                  'd(220000000)',   80, 'low'),
        ('Газоснабжение с. Жетыген',       'gas',      'с. Жетыген',   'ГУ ЖКХ ИР',                   'd(310000000)',   35, 'high'),
        ('ФАП с. Ынтымак',                 'fap',      'с. Ынтымак',   'ГУ Отдел здравоохранения ИР', 'd(88000000)',    70, 'low'),
        ('Дорога Отеген-Батыр — Боралдай', 'road',     'ИР',           'ГУ Отдел дорог ИР',           'd(980000000)',   50, 'medium'),
        ('Электроснабжение с. Акдала',     'electricity','с. Акдала',  'ГУ ЖКХ ИР',                   'd(175000000)',   90, 'low'),
    ],
    'KAR': [
        ('Школа №8 г. Каскелен',           'school',   'г. Каскелен',  'ГУ Отдел образования КР',     'd(760000000)',   70, 'low'),
        ('Больница г. Каскелен',           'hospital', 'г. Каскелен',  'ГУ Отдел здравоохранения КР', 'd(2100000000)', 30, 'high'),
        ('Водопровод с. Фабричное',        'water',    'с. Фабричное', 'ГУ ЖКХ КР',                   'd(190000000)',   45, 'medium'),
        ('Газоснабжение с. Шамалган',      'gas',      'с. Шамалган',  'ГУ ЖКХ КР',                   'd(250000000)',   60, 'medium'),
        ('Дорога Каскелен — Узынагаш',     'road',     'КР',           'ГУ Отдел дорог КР',           'd(1200000000)', 25, 'high'),
        ('ФАП с. Туздыбастау',             'fap',      'с. Туздыбастау','ГУ Отдел здравоохранения КР','d(79000000)',    85, 'low'),
    ],
    'TAL': [
        ('Школа №2 г. Талгар',             'school',   'г. Талгар',    'ГУ Отдел образования ТР',     'd(680000000)',   85, 'low'),
        ('ФАП с. Панфилов',                'fap',      'с. Панфилов',  'ГУ Отдел здравоохранения ТР', 'd(76000000)',    90, 'low'),
        ('Водопровод с. Гвардейский',      'water',    'с. Гвардейский','ГУ ЖКХ ТР',                  'd(165000000)',   75, 'low'),
        ('Электроснабжение с. Байтерек',   'electricity','с. Байтерек','ГУ ЖКХ ТР',                   'd(120000000)',   80, 'low'),
        ('Газоснабжение с. Ынтымак',       'gas',      'с. Ынтымак',   'ГУ ЖКХ ТР',                   'd(198000000)',   40, 'medium'),
    ],
    'ZHM': [
        ('Школа с. Узынагаш №1',           'school',   'с. Узынагаш',  'ГУ Отдел образования ЖР',     'd(590000000)',   75, 'low'),
        ('Больница с. Узынагаш',           'hospital', 'с. Узынагаш',  'ГУ Отдел здравоохранения ЖР', 'd(950000000)',   55, 'medium'),
        ('Водопровод с. Тулебиево',        'water',    'с. Тулебиево', 'ГУ ЖКХ ЖР',                   'd(142000000)',   80, 'low'),
        ('ФАП с. Акши',                    'fap',      'с. Акши',      'ГУ Отдел здравоохранения ЖР', 'd(75000000)',    90, 'low'),
    ],
    'BLK': [
        ('Школа с. Баканас №2',            'school',   'с. Баканас',   'ГУ Отдел образования БалкР',  'd(450000000)',   60, 'medium'),
        ('ФАП с. Акдала',                  'fap',      'с. Акдала',    'ГУ Отдел здравоохранения БалкР','d(71000000)',  80, 'low'),
        ('Водопровод с. Баканас',          'water',    'с. Баканас',   'ГУ ЖКХ БалкР',                'd(280000000)',   35, 'high'),
        ('Газоснабжение с. Акколь',        'gas',      'с. Акколь',    'ГУ ЖКХ БалкР',                'd(195000000)',   20, 'high'),
    ],
    'ALK': [
        ('Школа с. Үшарал №1',             'school',   'с. Үшарал',    'ГУ Отдел образования АлкР',   'd(520000000)',   65, 'medium'),
        ('Больница с. Үшарал',             'hospital', 'с. Үшарал',    'ГУ Отдел здравоохранения АлкР','d(780000000)', 45, 'medium'),
        ('Водопровод с. Достык',           'water',    'с. Достык',    'ГУ ЖКХ АлкР',                 'd(160000000)',   70, 'low'),
    ],
    'KEG': [
        ('Школа с. Кеген №1',              'school',   'с. Кеген',     'ГУ Отдел образования КегР',   'd(380000000)',   70, 'low'),
        ('ФАП с. Жалаңаш',                 'fap',      'с. Жалаңаш',   'ГУ Отдел здравоохранения КегР','d(68000000)',   85, 'low'),
        ('Дорога Кеген — Нарынкол',        'road',     'КегР',         'ГУ Отдел дорог КегР',         'd(1500000000)', 15, 'high'),
    ],
    'RAY': [
        ('Школа с. Нарынкол №1',           'school',   'с. Нарынкол',  'ГУ Отдел образования РайР',   'd(410000000)',   75, 'low'),
        ('Больница с. Нарынкол',           'hospital', 'с. Нарынкол',  'ГУ Отдел здравоохранения РайР','d(620000000)', 50, 'medium'),
        ('Дорога Нарынкол — Кеген',        'road',     'РайР',         'ГУ Отдел дорог РайР',         'd(1800000000)', 10, 'high'),
        ('ФАП с. Бурхан',                  'fap',      'с. Бурхан',    'ГУ Отдел здравоохранения РайР','d(65000000)',   90, 'low'),
    ],
    'UYG': [
        ('Школа с. Чунджа №2',             'school',   'с. Чунджа',    'ГУ Отдел образования УйгР',   'd(490000000)',   60, 'medium'),
        ('Больница с. Чунджа',             'hospital', 'с. Чунджа',    'ГУ Отдел здравоохранения УйгР','d(730000000)', 40, 'medium'),
        ('Водопровод с. Чунджа',           'water',    'с. Чунджа',    'ГУ ЖКХ УйгР',                 'd(185000000)',   55, 'medium'),
    ],
}

# Координаты объектов (примерные для каждого района)
COORDS = {
    'ENB': [(43.35,77.47),(43.30,77.50),(43.42,77.65),(43.38,77.70),(43.25,77.40),(43.32,77.38),(43.28,77.55),(43.20,77.30)],
    'ILE': [(43.64,77.13),(43.60,77.05),(43.70,77.20),(43.58,77.08),(43.66,77.18),(43.72,77.25),(43.62,77.00)],
    'KAR': [(43.20,76.62),(43.22,76.65),(43.18,76.58),(43.25,76.70),(43.15,76.55),(43.28,76.75)],
    'TAL': [(43.30,77.25),(43.28,77.30),(43.32,77.22),(43.26,77.28),(43.34,77.32)],
    'ZHM': [(43.73,76.28),(43.70,76.22),(43.75,76.35),(43.68,76.18)],
    'BLK': [(44.80,74.90),(44.85,74.95),(44.75,74.85),(44.90,75.00)],
    'ALK': [(45.70,80.90),(45.75,80.95),(45.65,80.85)],
    'KEG': [(42.99,79.18),(42.95,79.12),(43.02,79.25)],
    'RAY': [(42.72,79.98),(42.68,79.92),(42.75,80.05),(42.70,80.00)],
    'UYG': [(43.56,79.93),(43.52,79.88),(43.60,79.98)],
}

statuses = ['in_progress','in_progress','delayed','completed','planned']
financing = ['local','republican','local','mixed']
risk_levels_map = {'low':'low','medium':'medium','high':'high'}

for code, objects in INFRA.items():
    dist = dist_objs[code]
    coords = COORDS.get(code, [(dist.lat, dist.lng)] * 10)
    for i, (name, cat, locality, customer, amount_str, readiness, risk) in enumerate(objects):
        lat, lng = coords[i % len(coords)]
        amount = eval(amount_str.replace('d(','decimal.Decimal('))
        ConstructionObject.objects.create(
            district=dist, name=name, category=cat, locality=locality,
            customer_name=customer, contractor_name=f'ТОО «СтройРегион-{i+1}»',
            contract_amount=amount, financing_source=financing[i % len(financing)],
            start_date=date(2022 + i % 3, (i % 12) + 1, 1),
            end_date=date(2024 + i % 2, (i % 12) + 1, 28),
            actual_status=statuses[i % len(statuses)],
            readiness_pct=readiness, risk_level=risk,
            lat=round(lat + random.uniform(-0.05, 0.05), 4),
            lng=round(lng + random.uniform(-0.05, 0.05), 4),
        )

print(f"Construction objects: {ConstructionObject.objects.count()}")

# ── Budget Programs ────────────────────────────────────────────────────────────
BudgetProgram.objects.all().delete()
SPHERES = ['construction','housing','roads','education','healthcare','agriculture','social','digitalization']
ALLOC_BASE = {'ENB':38e9,'ILE':42e9,'KAR':35e9,'TAL':31e9,'ZHM':21e9,'BLK':17e9,'ALK':16e9,'KEG':14e9,'RAY':11e9,'UYG':13e9,'ALK':16e9}

for code, dist in dist_objs.items():
    base = ALLOC_BASE.get(code, 15e9)
    for year in [2021,2022,2023,2024,2025,2026]:
        for sphere in SPHERES:
            alloc = base * random.uniform(0.08, 0.18)
            exec_pct = random.uniform(55, 98)
            spent = alloc * exec_pct / 100
            BudgetProgram.objects.create(
                district=dist, year=year, sphere=sphere,
                program_name=f'Программа развития ({sphere})',
                allocated=d(round(alloc)), spent=d(round(spent)),
                remainder=d(round(alloc - spent)),
                execution_pct=round(exec_pct, 1),
            )
print(f"BudgetPrograms: {BudgetProgram.objects.count()}")

# ── Procurement Contracts ──────────────────────────────────────────────────────
ProcurementContract.objects.all().delete()
SUPPLIERS = [
    ('ТОО «АлматыСтройГрупп»',  '123456789012'),
    ('ТОО «КазАгроСтрой»',      '234567890123'),
    ('ТОО «БілімСервис»',        '345678901234'),
    ('ТОО «МедПроектКаз»',       '456789012345'),
    ('АО «ДорСтрой Казахстан»',  '567890123456'),
    ('ТОО «ЖамбылСтрой»',        '678901234567'),
    ('ТОО «АлатауКурылыс»',      '789012345678'),
    ('ТОО «РегионСервис»',       '890123456789'),
]
METHODS = ['tender','one_source','price_request','auction']
SUBJECTS = ['Строительство школы','Реконструкция больницы','Асфальтирование дороги',
            'Водоснабжение населённого пункта','Газоснабжение сёл','Оборудование для ФАП',
            'Ремонт дома культуры','Поставка учебников','Цифровизация услуг','Строительство ФАП']

n = 0
for code, dist in dist_objs.items():
    for year in [2022,2023,2024,2025]:
        num_contracts = random.randint(15, 35)
        for i in range(num_contracts):
            sup_name, sup_bin = random.choice(SUPPLIERS)
            amt = random.uniform(5e6, 500e6)
            rs = random.random() < 0.15
            ro = random.random() < 0.12
            rsp = random.random() < 0.08
            ra = random.random() < 0.10
            n += 1
            ProcurementContract.objects.create(
                district=dist,
                contract_number=f'КЗ-{code}-{year}-{i+1:03d}',
                customer_name=f'ГУ «Отдел {random.choice(["образования","здравоохранения","ЖКХ","дорог"])} {dist.name[:10]}»',
                supplier_name=sup_name, supplier_bin=sup_bin,
                subject=random.choice(SUBJECTS),
                method=random.choice(METHODS),
                amount=d(round(amt)),
                year=year,
                contract_date=date(year, random.randint(1,6), random.randint(1,28)),
                deadline_date=date(year, random.randint(7,12), random.randint(1,28)),
                status=random.choice(['active','completed','delayed']),
                risk_single=rs, risk_overpriced=ro, risk_splitting=rsp, risk_affiliation=ra,
            )
print(f"Contracts: {n}")

# ── Risk Materials ─────────────────────────────────────────────────────────────
RiskMaterial.objects.all().delete()
RISK_SPHERES = ['procurement','construction','agro','osms','budget']
RISK_LEVELS  = ['medium','high','critical','medium','high']
RISK_STATUS  = ['analysis','prevention','erdr','in_progress','completed']
RISK_DESCS = [
    'Завышение стоимости строительных работ по контракту',
    'Нецелевое использование бюджетных средств',
    'Фиктивные субсидии на поддержку животноводства',
    'Неуплата взносов ОСМС работодателем',
    'Дробление закупок с целью обхода порога конкурса',
    'Аффилированность участников тендера с заказчиком',
    'Завышение объёмов выполненных работ',
    'Задержка сдачи объекта с применением штрафных санкций',
]
rm_n = 0
for code, dist in dist_objs.items():
    for year in [2022,2023,2024,2025]:
        for i in range(random.randint(5,12)):
            RiskMaterial.objects.create(
                district=dist,
                sphere=random.choice(RISK_SPHERES),
                subject_name=random.choice(SUPPLIERS)[0],
                amount=d(round(random.uniform(1e6, 80e6))),
                description=random.choice(RISK_DESCS),
                status=random.choice(RISK_STATUS),
                level=random.choice(RISK_LEVELS),
                source=random.choice(['internal','external','citizen']),
                detected_at=date(year, random.randint(1,12), random.randint(1,28)),
                year=year,
                analyst=analyst,
            )
            rm_n += 1
print(f"Risk materials: {rm_n}")

# ── Legal Entities ─────────────────────────────────────────────────────────────
LegalEntity.objects.all().delete()
for i, (name, bin_) in enumerate(SUPPLIERS):
    LegalEntity.objects.create(
        name=name, bin_iin=bin_,
        director=f'Директор {i+1}',
        registration_date=date(2010 + i, 1, 1),
        risk_transit=i % 5 == 0, risk_fictitious=i % 7 == 0,
        risk_nominal=i % 6 == 0, risk_affiliated=i % 4 == 0,
    )
print(f"Legal entities: {LegalEntity.objects.count()}")

# ── Subsidy Recipients ─────────────────────────────────────────────────────────
SubsidyRecipient.objects.all().delete()
SUBSIDY_TYPES = ['plant','animal','equipment','irrigation']
PROGRAMS = ['Программа субсидирования растениеводства','Поддержка животноводства','Льготное кредитование АПК','Орошение сельхозугодий']
sr_n = 0
for code in ['ENB','ILE','KAR','TAL','ZHM','BLK','KEG','RAY','UYG','ALK']:
    dist = dist_objs[code]
    for year in [2022,2023,2024,2025]:
        for i in range(random.randint(5,12)):
            sr_n += 1
            SubsidyRecipient.objects.create(
                district=dist,
                name=f'КХ «{random.choice(["Береке","Нұр","Алтын","Жер-Ана","Болашақ"])}» {i+1}',
                bin_iin=f'{random.randint(100000000000,999999999999)}',
                program=random.choice(PROGRAMS),
                subsidy_type=random.choice(SUBSIDY_TYPES),
                amount=d(round(random.uniform(500000, 15000000))),
                year=year,
                risk_concentration=random.random()<0.1,
                risk_affiliation=random.random()<0.08,
            )
print(f"Subsidy recipients: {sr_n}")

print("\nSeed complete.")
