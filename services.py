"""
Модуль бизнес-логики (Business Logic Layer) для системы диспетчеризации заявок и контроля SLA.
Содержит функции автоматической классификации текста, расчета матрицы SLA,
динамического контроля дедлайнов («светофор») и балансировки нагрузки инженеров.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

# Категории обращений
CATEGORIES = [
    "Кассовое ПО",
    "Оборудование / POS",
    "Сеть и Фискализация (ОФД)",
    "Консультация и Отчетность",
]

# Уровни приоритета и их балльный вес для расчета индекса нагрузки инженера
PRIORITY_WEIGHTS: Dict[str, int] = {
    "Critical": 4,
    "High": 3,
    "Medium": 2,
    "Low": 1,
}

# Порядок срочности приоритетов (для сортировки)
PRIORITY_ORDER: Dict[str, int] = {
    "Critical": 1,
    "High": 2,
    "Medium": 3,
    "Low": 4,
}

# Матрица нормативов SLA в минутах: Тариф клиента -> Приоритет -> Минуты на решение
SLA_MATRIX_MINUTES: Dict[str, Dict[str, int]] = {
    "VIP": {
        "Critical": 60,     # 1 час
        "High": 120,        # 2 часа
        "Medium": 240,      # 4 часа
        "Low": 480,         # 8 часов
    },
    "Standard": {
        "Critical": 120,    # 2 часа
        "High": 240,        # 4 часа
        "Medium": 480,      # 8 часов
        "Low": 1440,        # 24 часа
    },
    "Basic": {
        "Critical": 240,    # 4 часа
        "High": 480,        # 8 часов
        "Medium": 1440,     # 24 часа
        "Low": 2880,        # 48 часов
    },
}

# Словари ключевых маркеров для определения категории обращения
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "Кассовое ПО": [
        "касс", "чек", "смен", "пробит", "пробив", "завис", "фронтол",
        "1с", "розниц", "возврат", "скидк", "штрихкод", "обновлен", "ошибка по"
    ],
    "Оборудование / POS": [
        "сканер", "принтер", "терминал", "весы", "экран", "монитор",
        "питани", "включает", "пикает", "лент", "отрезчик", "кнопк", "денежн"
    ],
    "Сеть и Фискализация (ОФД)": [
        "интернет", "сеть", "офд", "фискальн", "накопител", "фн",
        "связ", "роутер", "егаис", "честный знак", "маркировк", "обмен", "сервер"
    ],
    "Консультация и Отчетность": [
        "отчет", "как ", "подскаж", "инструкц", "выгруз", "сверк",
        "прав", "доступ", "добавить пользовател", "консультац", "обучен"
    ],
}

# Словари маркеров для определения приоритета (критичности) обращения
PRIORITY_KEYWORDS: Dict[str, List[str]] = {
    "Critical": [
        "остановил", "все кассы", "простой", "не работает магазин",
        "очередь", "парализован", "авария", "совсем не пробивает",
        "торговля встала", "закрыт магазин", "ни одна касса"
    ],
    "High": [
        "ошибка фн", "не уходят чеки", "сломался", "не печатает",
        "отказ", "сбой", "не включается", "блокировк", "срочно", "егаис не"
    ],
    "Low": [
        "вопрос", "как выгрузить", "подскажите", "консультац",
        "планов", "когда сможете", "просьба", "инструкц", "не срочно"
    ],
}


def classify_ticket_text(title: str, description: str) -> Tuple[str, str, str]:
    """
    Автоматически определяет категорию и приоритет заявки по заголовку и описанию.
    Возвращает кортеж: (категория, приоритет, текстовое обоснование решения).
    """
    full_text = f"{title} {description}".lower().strip()

    # 1. Определение категории по наибольшему числу совпадений маркеров
    category_scores: Dict[str, int] = {cat: 0 for cat in CATEGORIES}
    matched_cat_words: Dict[str, List[str]] = {cat: [] for cat in CATEGORIES}

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in full_text:
                category_scores[category] += 1
                matched_cat_words[category].append(kw)

    best_category = max(category_scores, key=lambda k: category_scores[k])
    if category_scores[best_category] == 0:
        best_category = "Консультация и Отчетность"
        cat_reason = "узкие технические маркеры не найдены (назначена базовая категория)"
    else:
        words_str = ", ".join(matched_cat_words[best_category][:3])
        cat_reason = f"найдены маркеры категории ({words_str})"

    # 2. Определение приоритета по иерархии критичности
    detected_priority = "Medium"
    prio_reason = "стандартное обращение без маркеров полной остановки точки"

    for kw in PRIORITY_KEYWORDS["Critical"]:
        if kw in full_text:
            detected_priority = "Critical"
            prio_reason = f"обнаружен маркер критической аварии («{kw}»)"
            break

    if detected_priority == "Medium":
        for kw in PRIORITY_KEYWORDS["High"]:
            if kw in full_text:
                detected_priority = "High"
                prio_reason = f"обнаружен маркер серьезного сбоя («{kw}»)"
                break

    if detected_priority == "Medium":
        for kw in PRIORITY_KEYWORDS["Low"]:
            if kw in full_text:
                detected_priority = "Low"
                prio_reason = f"обнаружен маркер информационного запроса («{kw}»)"
                break

    explanation = f"Категория «{best_category}» ({cat_reason}); Приоритет «{detected_priority}» ({prio_reason})."
    return best_category, detected_priority, explanation


def calculate_sla_deadline(tariff: str, priority: str, created_at: datetime) -> Tuple[int, datetime]:
    """
    Вычисляет норматив времени SLA (в минутах) и точный дедлайн (datetime)
    на основании тарифа клиента и приоритета заявки.
    """
    tariff_clean = tariff if tariff in SLA_MATRIX_MINUTES else "Standard"
    priority_clean = priority if priority in SLA_MATRIX_MINUTES[tariff_clean] else "Medium"

    sla_minutes = SLA_MATRIX_MINUTES[tariff_clean][priority_clean]
    deadline = created_at + timedelta(minutes=sla_minutes)
    return sla_minutes, deadline


def evaluate_sla_status(
    status: str,
    created_at_iso: str,
    sla_deadline_iso: str,
    resolved_at_iso: Optional[str] = None,
    reference_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Оценивает статус соблюдения SLA («светофор») для активной или закрытой заявки.
    Возвращает словарь с кодом статуса, меткой для интерфейса, остатком/превышением в минутах и флагом просрочки.
    """
    now = reference_time or datetime.now()
    created_dt = datetime.fromisoformat(created_at_iso)
    deadline_dt = datetime.fromisoformat(sla_deadline_iso)
    total_sla_minutes = max((deadline_dt - created_dt).total_seconds() / 60.0, 1.0)

    if status == "Решена" and resolved_at_iso:
        resolved_dt = datetime.fromisoformat(resolved_at_iso)
        diff_minutes = int(round((deadline_dt - resolved_dt).total_seconds() / 60.0))
        actual_duration_min = int(round((resolved_dt - created_dt).total_seconds() / 60.0))
        if resolved_dt <= deadline_dt:
            return {
                "sla_code": "OK",
                "sla_badge": "🟢 SLA выполнен",
                "remaining_min": diff_minutes,
                "is_breached": False,
                "is_at_risk": False,
                "time_comment": f"Решена за {actual_duration_min} мин (запас {diff_minutes} мин)",
            }
        else:
            over_min = abs(diff_minutes)
            return {
                "sla_code": "BREACHED",
                "sla_badge": "🔴 SLA нарушен",
                "remaining_min": diff_minutes,
                "is_breached": True,
                "is_at_risk": False,
                "time_comment": f"Решена за {actual_duration_min} мин (просрочка {over_min} мин)",
            }

    # Для активных заявок (Новая, В работе, Ожидает ответа)
    remaining_seconds = (deadline_dt - now).total_seconds()
    remaining_min = int(round(remaining_seconds / 60.0))
    remaining_ratio = (remaining_seconds / 60.0) / total_sla_minutes

    if remaining_seconds < 0:
        return {
            "sla_code": "BREACHED",
            "sla_badge": "🔴 Просрочено",
            "remaining_min": remaining_min,
            "is_breached": True,
            "is_at_risk": False,
            "time_comment": f"Просрочка {abs(remaining_min)} мин",
        }
    elif remaining_ratio <= 0.25:
        return {
            "sla_code": "AT_RISK",
            "sla_badge": "🟡 Риск просрочки",
            "remaining_min": remaining_min,
            "is_breached": False,
            "is_at_risk": True,
            "time_comment": f"Осталось {remaining_min} мин (<25% времени)",
        }
    else:
        return {
            "sla_code": "OK",
            "sla_badge": "🟢 В норме",
            "remaining_min": remaining_min,
            "is_breached": False,
            "is_at_risk": False,
            "time_comment": f"В запасе {remaining_min} мин",
        }


def calculate_engineer_workloads(
    engineers: List[Dict[str, Any]],
    active_tickets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Рассчитывает текущую загрузку каждого инженера:
    - количество открытых заявок (active_count)
    - взвешенный индекс нагрузки в баллах (workload_score) по приоритетам активных тикетов.
    """
    stats_by_eng: Dict[int, Dict[str, int]] = {
        int(eng["id"]): {"active_count": 0, "workload_score": 0, "critical_count": 0}
        for eng in engineers
    }

    for ticket in active_tickets:
        if ticket.get("status") == "Решена":
            continue
        eng_id = ticket.get("engineer_id")
        if eng_id in stats_by_eng:
            prio = ticket.get("priority", "Medium")
            weight = PRIORITY_WEIGHTS.get(prio, 2)
            stats_by_eng[eng_id]["active_count"] += 1
            stats_by_eng[eng_id]["workload_score"] += weight
            if prio == "Critical":
                stats_by_eng[eng_id]["critical_count"] += 1

    enriched_engineers: List[Dict[str, Any]] = []
    for eng in engineers:
        eng_copy = dict(eng)
        st = stats_by_eng.get(int(eng["id"]), {"active_count": 0, "workload_score": 0, "critical_count": 0})
        eng_copy["active_count"] = st["active_count"]
        eng_copy["workload_score"] = st["workload_score"]
        eng_copy["critical_count"] = st["critical_count"]
        enriched_engineers.append(eng_copy)

    return enriched_engineers


def select_best_engineer(
    category: str,
    engineers: List[Dict[str, Any]],
    active_tickets: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Алгоритм автомаршрутизации (Smart Routing):
    1. Ищет активных инженеров на смене (is_active == 1) с профильной специализацией.
    2. Если профильных нет на смене — ищет активных инженеров со специализацией «Универсал».
    3. Если и таких нет — выбирает из всех активных инженеров смены.
    4. Внутри выбранного пула назначает специалиста с минимальным индексом нагрузки (workload_score).
    """
    with_workload = calculate_engineer_workloads(engineers, active_tickets)
    active_shift = [e for e in with_workload if int(e.get("is_active", 0)) == 1]

    if not active_shift:
        # Если все отмечены вне смены, берем вообще всех инженеров как резерв
        active_shift = with_workload
        fallback_note = "Внимание: нет инженеров со статусом «На смене», выбран дежурный из общего списка."
    else:
        fallback_note = ""

    if not active_shift:
        return None, "В базе данных нет зарегистрированных инженеров."

    # Шаг 1: Точное совпадение специализации
    exact_match = [e for e in active_shift if e.get("specialty") == category]
    if exact_match:
        pool = exact_match
        pool_type = f"профильный специалист по направлению «{category}»"
    else:
        # Шаг 2: Инженер-универсал
        universal_match = [e for e in active_shift if e.get("specialty") == "Универсал"]
        if universal_match:
            pool = universal_match
            pool_type = "инженер широкого профиля («Универсал»), т.к. узкие специалисты вне смены"
        else:
            # Шаг 3: Любой свободный инженер смены
            pool = active_shift
            pool_type = "свободный инженер смены (резервное перераспределение)"

    # Сортируем кандидатов по: 1) минимальному индексу нагрузки, 2) минимальному числу тикетов, 3) ID
    pool_sorted = sorted(
        pool,
        key=lambda x: (x["workload_score"], x["active_count"], x["id"])
    )
    chosen = pool_sorted[0]

    routing_reason = (
        f"Назначен {chosen['full_name']} ({pool_type}, "
        f"текущий индекс загрузки: {chosen['workload_score']} балл., "
        f"активных заявок: {chosen['active_count']}). {fallback_note}".strip()
    )
    return chosen, routing_reason
