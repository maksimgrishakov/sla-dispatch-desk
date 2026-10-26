"""
Модульные тесты (Unit Tests) для проверки ключевой бизнес-логики приложения.
Совместимы как со встроенным модулем `unittest` (без доп. установки), так и с `pytest`.

Запуск встроенным средством Python:
    python -m unittest test_services.py -v
или через pytest:
    pytest test_services.py -v
"""

import unittest
from datetime import datetime
from services import (
    calculate_sla_deadline,
    classify_ticket_text,
    evaluate_sla_status,
    select_best_engineer,
)


class TestSLADispatchServices(unittest.TestCase):
    """Набор тест-кейсов TC-01 .. TC-08 для проверки бизнес-логики."""

    def test_tc01_classify_critical_pos_software(self):
        """TC-01: Распознавание критической аварии кассового ПО."""
        title = "Остановились все кассы на точке"
        desc = "После обновления не пробиваются чеки, очередь покупателей, простой магазина!"
        category, priority, _ = classify_ticket_text(title, desc)
        self.assertEqual(category, "Кассовое ПО")
        self.assertEqual(priority, "Critical")

    def test_tc02_classify_high_hardware(self):
        """TC-02: Распознавание сбоя торгового оборудования (POS-периферия)."""
        title = "Сломался беспроводной сканер штрихкодов"
        desc = "Сканер не пикает при нажатии, принтер чеков не печатает ленту."
        category, priority, _ = classify_ticket_text(title, desc)
        self.assertEqual(category, "Оборудование / POS")
        self.assertEqual(priority, "High")

    def test_tc03_classify_low_consultation(self):
        """TC-03: Распознавание планового консультационного запроса по отчетам."""
        title = "Вопрос по отчетности"
        desc = "Подскажите, как выгрузить отчет по продажам за месяц в Excel?"
        category, priority, _ = classify_ticket_text(title, desc)
        self.assertEqual(category, "Консультация и Отчетность")
        self.assertEqual(priority, "Low")

    def test_tc04_calculate_sla_deadline_vip_critical(self):
        """TC-04: Расчет дедлайна SLA для тарифа VIP и приоритета Critical (60 минут)."""
        created = datetime(2026, 10, 26, 10, 0)
        sla_minutes, deadline = calculate_sla_deadline("VIP", "Critical", created)
        self.assertEqual(sla_minutes, 60)
        self.assertEqual(deadline, datetime(2026, 10, 26, 11, 0))

    def test_tc05_evaluate_sla_at_risk_yellow_zone(self):
        """TC-05: Проверка попадания активной заявки в «желтую зону риска» (осталось <= 25% времени)."""
        created_iso = "2026-10-26T10:00"
        deadline_iso = "2026-10-26T11:40"  # Норматив 100 минут
        now_dt = datetime(2026, 10, 26, 11, 25)  # Осталось 15 минут (15% <= 25%)

        res = evaluate_sla_status(
            status="В работе",
            created_at_iso=created_iso,
            sla_deadline_iso=deadline_iso,
            resolved_at_iso=None,
            reference_time=now_dt,
        )
        self.assertEqual(res["sla_code"], "AT_RISK")
        self.assertTrue(res["is_at_risk"])
        self.assertFalse(res["is_breached"])
        self.assertEqual(res["remaining_min"], 15)

    def test_tc06_evaluate_sla_breached_red_zone(self):
        """TC-06: Проверка фиксации нарушения SLA при закрытии после дедлайна."""
        created_iso = "2026-10-26T10:00"
        deadline_iso = "2026-10-26T12:00"
        resolved_iso = "2026-10-26T12:40"  # Опоздание на 40 минут

        res = evaluate_sla_status(
            status="Решена",
            created_at_iso=created_iso,
            sla_deadline_iso=deadline_iso,
            resolved_at_iso=resolved_iso,
        )
        self.assertEqual(res["sla_code"], "BREACHED")
        self.assertTrue(res["is_breached"])
        self.assertEqual(res["remaining_min"], -40)

    def test_tc07_smart_routing_least_loaded_specialist(self):
        """TC-07: Выбор наименее загруженного профильного инженера по баллам тяжести тикетов."""
        engineers = [
            {"id": 1, "full_name": "Инженер А (Перегружен)", "specialty": "Кассовое ПО", "grade": "L2", "is_active": 1},
            {"id": 2, "full_name": "Инженер Б (Свободнее)", "specialty": "Кассовое ПО", "grade": "L2", "is_active": 1},
        ]
        active_tickets = [
            {"engineer_id": 1, "priority": "Critical", "status": "В работе"},  # 4 балла
            {"engineer_id": 1, "priority": "Medium", "status": "В работе"},    # 2 балла (Итого: 6)
            {"engineer_id": 2, "priority": "Medium", "status": "В работе"},    # 2 балла (Итого: 2)
        ]

        chosen, _ = select_best_engineer("Кассовое ПО", engineers, active_tickets)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["id"], 2)
        self.assertEqual(chosen["workload_score"], 2)

    def test_tc08_smart_routing_universal_fallback(self):
        """TC-08: Назначение инженера-универсала, если профильный специалист вне смены."""
        engineers = [
            {"id": 1, "full_name": "Профильный (Выходной)", "specialty": "Оборудование / POS", "grade": "L2", "is_active": 0},
            {"id": 2, "full_name": "Инженер Универсал", "specialty": "Универсал", "grade": "L2", "is_active": 1},
        ]
        chosen, _ = select_best_engineer("Оборудование / POS", engineers, [])
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["id"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
