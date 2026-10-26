"""
Модуль слоя доступа к данным (Data Access Layer) на базе SQLite3.
Отвечает за инициализацию схемы БД, CRUD-операции с заявками, клиентами и инженерами,
а также за генерацию реалистичного набора синтетических данных для демонстрации проекта.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from services import calculate_sla_deadline

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sla_dispatch.db")


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Создает подключение к SQLite с возвратом строк в виде словарей (sqlite3.Row)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Создает таблицы базы данных, если они еще не существуют, и наполняет демо-данными при первом запуске."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tariff TEXT NOT NULL,
            penalty_rub INTEGER NOT NULL DEFAULT 0,
            contact_person TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS engineers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            grade TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            engineer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            sla_minutes INTEGER NOT NULL,
            sla_deadline TEXT NOT NULL,
            resolved_at TEXT,
            resolution_note TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id),
            FOREIGN KEY (engineer_id) REFERENCES engineers(id)
        )
    """)

    conn.commit()

    # Проверяем, пуста ли таблица клиентов; если да — загружаем синтетические демо-данные
    cursor.execute("SELECT COUNT(*) AS cnt FROM clients")
    row = cursor.fetchone()
    conn.close()

    if row and row["cnt"] == 0:
        seed_demo_data(db_path)


def seed_demo_data(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Очищает базу и заполняет её сбалансированным набором синтетических данных
    для наглядной демонстрации на защите проекта (5 клиентов, 5 инженеров, 24 заявки).
    Время всех заявок рассчитывается относительно текущего момента запуска!
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tickets")
    cursor.execute("DELETE FROM clients")
    cursor.execute("DELETE FROM engineers")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('tickets', 'clients', 'engineers')")

    # 1. Справочник корпоративных клиентов (Синтетические данные)
    clients_data = [
        ("Сеть супермаркетов «ФрешМаркет» (45 касс)", "VIP", 3000, "Ирина Викторовна (ИТ-директор)"),
        ("Аптечная сеть «ВитаПлюс» (30 точек)", "VIP", 3000, "Андрей Смирнов (Нач. ОЭ)"),
        ("Сеть пекарен «Хлеб и Кофе» (18 точек)", "Standard", 1000, "Елена Козлова (Управляющая)"),
        ("Магазины у дома «УютТорг» (12 точек)", "Standard", 1000, "Максим Петров (Владелец)"),
        ("Стройбаза «МастерДом» (4 кассы)", "Basic", 0, "Олег Сидоров (Администратор)"),
    ]
    cursor.executemany(
        "INSERT INTO clients (name, tariff, penalty_rub, contact_person) VALUES (?, ?, ?, ?)",
        clients_data,
    )

    # 2. Справочник инженеров технической поддержки (Синтетические данные)
    engineers_data = [
        ("Соколов Алексей", "Кассовое ПО", "Senior L2", 1),
        ("Морозов Дмитрий", "Оборудование / POS", "Middle L2", 1),
        ("Волкова Екатерина", "Сеть и Фискализация (ОФД)", "Senior L2", 1),
        ("Лебедев Артём", "Консультация и Отчетность", "Junior L1", 1),
        ("Кузнецов Павел", "Универсал", "Middle L2", 1),
    ]
    cursor.executemany(
        "INSERT INTO engineers (full_name, specialty, grade, is_active) VALUES (?, ?, ?, ?)",
        engineers_data,
    )

    now = datetime.now().replace(second=0, microsecond=0)

    # Соответствие тарифов по client_id (1..5)
    client_tariffs = {1: "VIP", 2: "VIP", 3: "Standard", 4: "Standard", 5: "Basic"}

    # 3. Набор демонстрационных заявок:
    # Включает активные тикеты (В норме, В зоне риска <25%, Просроченные) и исторические закрытые тикеты
    raw_tickets = [
        # --- АКТИВНЫЕ ЗАЯВКИ (Очередь в реальном времени) ---
        # 1. В зоне риска (VIP, Critical, SLA 60 мин, создана 50 мин назад -> осталось 10 мин!)
        (
            1,
            "Остановились все кассы на центральной точке ФрешМаркет",
            "После утреннего обновления базы не пробиваются чеки, все кассы зависли, очередь покупателей.",
            "Кассовое ПО",
            "Critical",
            "В работе",
            1,
            now - timedelta(minutes=50),
            None,
            "",
        ),
        # 2. Уже просрочена (VIP, High, SLA 120 мин, создана 145 мин назад -> просрочка 25 мин!)
        (
            2,
            "Ошибка ФН и блокировка отправки чеков в ОФД",
            "В аптеке на Ленина 14 касса выдает ошибку фискального накопителя, чеки не уходят в ОФД более суток.",
            "Сеть и Фискализация (ОФД)",
            "High",
            "В работе",
            3,
            now - timedelta(minutes=145),
            None,
            "",
        ),
        # 3. В зоне риска (Standard, High, SLA 240 мин, создана 205 мин назад -> осталось 35 мин!)
        (
            3,
            "Не включается сенсорный POS-терминал на кассе №2",
            "После скачка напряжения погас экран основного POS-терминала, блок питания горячий.",
            "Оборудование / POS",
            "High",
            "В работе",
            2,
            now - timedelta(minutes=205),
            None,
            "",
        ),
        # 4. В норме (VIP, High, SLA 120 мин, создана 25 мин назад -> в запасе 95 мин)
        (
            2,
            "Сбой проверки маркировки Честный Знак при продаже лекарств",
            "При сканировании кода DataMatrix на упаковках возникает ошибка таймаута соединения с сервером маркировки.",
            "Сеть и Фискализация (ОФД)",
            "High",
            "Новая",
            3,
            now - timedelta(minutes=25),
            None,
            "",
        ),
        # 5. В норме (Standard, Medium, SLA 480 мин, создана 90 мин назад -> в запасе 390 мин)
        (
            4,
            "Некорректно считается скидка по бонусной карте в чеке",
            "Для акционных товаров система применяет двойную скидку при списании баллов.",
            "Кассовое ПО",
            "Medium",
            "В работе",
            5,
            now - timedelta(minutes=90),
            None,
            "",
        ),
        # 6. В норме (Standard, Medium, SLA 480 мин, создана 40 мин назад)
        (
            3,
            "Заедает автоотрезчик чековой ленты на принтере АТОЛ",
            "Принтер чеков зажевывает бумагу на каждом пятом чеке, приходится открывать крышку вручную.",
            "Оборудование / POS",
            "Medium",
            "Новая",
            2,
            now - timedelta(minutes=40),
            None,
            "",
        ),
        # 7. В норме (Basic, Low, SLA 2880 мин, создана 180 мин назад)
        (
            5,
            "Подскажите, как выгрузить отчет по возвратам за квартал",
            "Просьба прислать инструкцию или помочь настроить выгрузку отчета по возвратам в Excel.",
            "Консультация и Отчетность",
            "Low",
            "Ожидает ответа",
            4,
            now - timedelta(minutes=180),
            None,
            "",
        ),
        # 8. Просрочена в работе (Standard, Critical, SLA 120 мин, создана 160 мин назад)
        (
            4,
            "Полный простой магазина: база 1С не открывается по сети",
            "Ни одна касса не видит сервер магазина, торговля встала, просим срочно подключиться.",
            "Сеть и Фискализация (ОФД)",
            "Critical",
            "В работе",
            5,
            now - timedelta(minutes=160),
            None,
            "",
        ),

        # --- ЗАКРЫТЫЕ ЗАЯВКИ (Историческая выборка для аналитики KPI) ---
        # Выполненные в рамках SLA:
        (
            1,
            "Авария кассового узла: зависла закрытая смена",
            "Остановилась касса №1 при гашении Z-отчета, очередь на кассе.",
            "Кассовое ПО",
            "Critical",
            "Решена",
            1,
            now - timedelta(hours=26),
            now - timedelta(hours=25, minutes=18),  # Решена за 42 мин при SLA 60 мин
            "Перезапущена служба драйвера ККТ, Z-отчет успешно закрыт.",
        ),
        (
            1,
            "Не работает 2D-сканер штрихкодов Honeywell",
            "Сканер не считывает акцизные марки, пикает три раза и гаснет.",
            "Оборудование / POS",
            "High",
            "Решена",
            2,
            now - timedelta(hours=24),
            now - timedelta(hours=22, minutes=30),  # Решена за 90 мин при SLA 120 мин
            "Сброшены настройки сканера по управляющему штрихкоду, переведен в режим USB-COM.",
        ),
        (
            2,
            "Нет связи с роутером резервного канала связи в аптеке №7",
            "Отвалился основной интернет, резервный 4G-модем не поднимает соединение с ОФД.",
            "Сеть и Фискализация (ОФД)",
            "High",
            "Решена",
            3,
            now - timedelta(hours=22),
            now - timedelta(hours=20, minutes=20),  # Решена за 100 мин при SLA 120 мин
            "Прописаны корректные маршруты DNS и перезапущен интерфейс резервного канала.",
        ),
        (
            3,
            "Зависание кассовой программы Фронтол при оплате по СБП",
            "При выводе QR-кода на экран покупателя касса зависает на 2 минуты.",
            "Кассовое ПО",
            "High",
            "Решена",
            1,
            now - timedelta(hours=20),
            now - timedelta(hours=17, minutes=10),  # Решена за 170 мин при SLA 240 мин
            "Обновлен плагин безналичной оплаты до версии 4.12, кэш очищен.",
        ),
        (
            4,
            "Сбилась калибровка прикассовых весов Штрих-Слим",
            "Весы показывают +45 грамм при пустой платформе.",
            "Оборудование / POS",
            "Medium",
            "Решена",
            2,
            now - timedelta(hours=19),
            now - timedelta(hours=14, minutes=30),  # Решена за 270 мин при SLA 480 мин
            "Проведена аппаратная тарировка и обнуление датчика веса.",
        ),
        (
            2,
            "Добавить нового фармацевта-кассира в базу и настроить права",
            "Просьба завести профиль для нового сотрудника смены и выдать права на возврат.",
            "Консультация и Отчетность",
            "Low",
            "Решена",
            4,
            now - timedelta(hours=18),
            now - timedelta(hours=13),  # Решена за 300 мин при SLA 480 мин
            "Учетная запись создана, шаблон ролей «Старший кассир» назначен.",
        ),
        (
            5,
            "Не выгружаются накладные из товароучетной системы на кассу",
            "Новые цены на стройматериалы не пришли в кассовый терминал.",
            "Кассовое ПО",
            "Medium",
            "Решена",
            5,
            now - timedelta(hours=30),
            now - timedelta(hours=22),  # Решена за 480 мин при SLA 1440 мин
            "Очищена очередь обмена в каталоге синхронизации, справочник товаров загружен.",
        ),
        (
            3,
            "Консультация по сверке итогов по банковскому терминалу",
            "Подскажите, почему сумма в Z-отчете кассы отличается от сверки итогов эквайринга на 450 руб.",
            "Консультация и Отчетность",
            "Low",
            "Решена",
            4,
            now - timedelta(hours=28),
            now - timedelta(hours=18),  # Решена за 600 мин при SLA 1440 мин
            "Выявлен чек, закрытый в переходные сутки (23:59). Сформирована бухгалтерская справка.",
        ),
        (
            1,
            "Отказ банковского пин-пада Ingenico на кассе №4",
            "Терминал оплаты картами пишет «Связь с хостом потеряна», клиенты не могут оплатить картой.",
            "Оборудование / POS",
            "High",
            "Решена",
            2,
            now - timedelta(hours=15),
            now - timedelta(hours=13, minutes=25),  # Решена за 95 мин при SLA 120 мин
            "Переобжат патч-корд и перезапущена служба DualConnector.",
        ),
        (
            4,
            "Ошибка отправки УПД в ЕГАИС при приемке партии",
            "Не проходит подтверждение накладной в УТМ ЕГАИС, ошибка подписи ГОСТ.",
            "Сеть и Фискализация (ОФД)",
            "High",
            "Решена",
            3,
            now - timedelta(hours=14),
            now - timedelta(hours=11, minutes=10),  # Решена за 170 мин при SLA 240 мин
            "Перезапущена служба УТМ, проверена цепочка сертификатов Рутокен.",
        ),
        (
            1,
            "Настройка автоматической отправки суточного отчета директору",
            "Вопрос: можно ли настроить рассылку отчета по выручке в 22:00 на почту управляющего?",
            "Консультация и Отчетность",
            "Low",
            "Решена",
            4,
            now - timedelta(hours=12),
            now - timedelta(hours=8),  # Решена за 240 мин при SLA 480 мин
            "Настроено регламентное задание планировщика с отправкой PDF-сводки.",
        ),
        (
            5,
            "Не печатает принтер этикеток Zebra на складе",
            "При отправке ценников на печать мигает красный индикатор ошибки.",
            "Оборудование / POS",
            "High",
            "Решена",
            5,
            now - timedelta(hours=16),
            now - timedelta(hours=11),  # Решена за 300 мин при SLA 480 мин
            "Выполнена калибровка датчика зазора этикетки в драйвере.",
        ),

        # Закрытые с нарушением SLA (для демонстрации штрафов и узких мест на дашборде):
        (
            1,
            "Простой гастронома: слетела лицензия кассового сервера",
            "Все кассы заблокированы после перезагрузки сервера, требуется активация лицензии.",
            "Кассовое ПО",
            "Critical",
            "Решена",
            1,
            now - timedelta(hours=36),
            now - timedelta(hours=34, minutes=30),  # Решена за 90 мин при SLA 60 мин (Нарушение VIP!)
            "Восстановлен аппаратный ключ защиты, резервная лицензия активирована.",
        ),
        (
            2,
            "Остановилась касса в круглосуточной аптеке из-за сбоя БД",
            "База данных кассы повреждена после отключения света, очередь клиентов.",
            "Кассовое ПО",
            "Critical",
            "Решена",
            1,
            now - timedelta(hours=32),
            now - timedelta(hours=30, minutes=15),  # Решена за 105 мин при SLA 60 мин (Нарушение VIP!)
            "Проведена индексация и восстановление таблиц БД из теневой копии.",
        ),
        (
            3,
            "Отсутствует связь с ОФД и сервером лояльности на 3 точках",
            "После смены настроек провайдера отвалился внешний обмен на трех пекарнях.",
            "Сеть и Фискализация (ОФД)",
            "High",
            "Решена",
            3,
            now - timedelta(hours=29),
            now - timedelta(hours=24, minutes=10),  # Решена за 290 мин при SLA 240 мин (Нарушение Standard!)
            "Обновлены настройки шлюза и проброс портов на микротиках.",
        ),
        (
            4,
            "Замена блока питания фискального регистратора АТОЛ 55Ф",
            "Сгорел блок питания ККТ, касса не включается.",
            "Оборудование / POS",
            "High",
            "Решена",
            2,
            now - timedelta(hours=27),
            now - timedelta(hours=22, minutes=15),  # Решена за 285 мин при SLA 240 мин (Нарушение Standard!)
            "Произведена выездная замена блока питания 24В.",
        ),
    ]

    for item in raw_tickets:
        (
            client_id,
            title,
            description,
            category,
            priority,
            status,
            engineer_id,
            created_dt,
            resolved_dt,
            res_note,
        ) = item
        tariff = client_tariffs[client_id]
        sla_min, deadline_dt = calculate_sla_deadline(tariff, priority, created_dt)

        cursor.execute(
            """
            INSERT INTO tickets (
                client_id, title, description, category, priority, status,
                engineer_id, created_at, sla_minutes, sla_deadline, resolved_at, resolution_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                title,
                description,
                category,
                priority,
                status,
                engineer_id,
                created_dt.isoformat(timespec="minutes"),
                sla_min,
                deadline_dt.isoformat(timespec="minutes"),
                resolved_dt.isoformat(timespec="minutes") if resolved_dt else None,
                res_note,
            ),
        )

    conn.commit()
    conn.close()


def fetch_clients(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Возвращает список всех корпоративных клиентов."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM clients ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_engineers(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Возвращает список всех инженеров поддержки."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM engineers ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_tickets_detailed(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Возвращает все заявки с присоединенными данными клиента и инженера."""
    conn = get_connection(db_path)
    query = """
        SELECT
            t.*,
            c.name AS client_name,
            c.tariff AS client_tariff,
            c.penalty_rub AS client_penalty_rub,
            c.contact_person AS client_contact,
            e.full_name AS engineer_name,
            e.specialty AS engineer_specialty,
            e.grade AS engineer_grade
        FROM tickets t
        JOIN clients c ON t.client_id = c.id
        JOIN engineers e ON t.engineer_id = e.id
        ORDER BY t.id DESC
    """
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_ticket(
    client_id: int,
    title: str,
    description: str,
    category: str,
    priority: str,
    engineer_id: int,
    sla_minutes: int,
    created_at_iso: str,
    sla_deadline_iso: str,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Создает новую заявку в БД и возвращает её ID."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO tickets (
            client_id, title, description, category, priority, status,
            engineer_id, created_at, sla_minutes, sla_deadline, resolved_at, resolution_note
        ) VALUES (?, ?, ?, ?, ?, 'Новая', ?, ?, ?, ?, NULL, '')
        """,
        (
            client_id,
            title.strip(),
            description.strip(),
            category,
            priority,
            engineer_id,
            created_at_iso,
            sla_minutes,
            sla_deadline_iso,
        ),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(new_id)


def update_ticket_status(
    ticket_id: int,
    new_status: str,
    engineer_id: int,
    priority: str,
    resolution_note: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Обновляет статус, приоритет, назначенного инженера и комментарий решения заявки."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    resolved_at_iso: Optional[str] = None
    if new_status == "Решена":
        # Если заявка уже была закрыта ранее — сохраняем прежнее время закрытия, иначе ставим текущее
        existing = cursor.execute(
            "SELECT resolved_at FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if existing and existing["resolved_at"]:
            resolved_at_iso = existing["resolved_at"]
        else:
            resolved_at_iso = datetime.now().replace(second=0, microsecond=0).isoformat(timespec="minutes")

    cursor.execute(
        """
        UPDATE tickets
        SET status = ?,
            engineer_id = ?,
            priority = ?,
            resolved_at = ?,
            resolution_note = ?
        WHERE id = ?
        """,
        (new_status, engineer_id, priority, resolved_at_iso, resolution_note.strip(), ticket_id),
    )
    conn.commit()
    conn.close()


def toggle_engineer_shift(engineer_id: int, is_active: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """Переключает статус инженера («На смене» / «Вне смены»)."""
    conn = get_connection(db_path)
    conn.execute("UPDATE engineers SET is_active = ? WHERE id = ?", (int(is_active), engineer_id))
    conn.commit()
    conn.close()
