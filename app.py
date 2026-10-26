"""
Главный модуль веб-интерфейса (Presentation Layer) на базе Streamlit.
Запуск приложения: streamlit run app.py
"""

from datetime import datetime
import pandas as pd
import plotly.express as px
import streamlit as st

from database import (
    create_ticket,
    fetch_clients,
    fetch_engineers,
    fetch_tickets_detailed,
    init_db,
    seed_demo_data,
    toggle_engineer_shift,
    update_ticket_status,
)
from services import (
    CATEGORIES,
    PRIORITY_ORDER,
    PRIORITY_WEIGHTS,
    SLA_MATRIX_MINUTES,
    calculate_engineer_workloads,
    calculate_sla_deadline,
    classify_ticket_text,
    evaluate_sla_status,
    select_best_engineer,
)

# Настройка страницы Streamlit
st.set_page_config(
    page_title="SLA Dispatch & Routing Desk | РитейлТехСервис",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Инициализация БД при старте
init_db()


def load_enriched_data():
    """Загружает данные из БД и обогащает каждую заявку актуальным расчетом SLA."""
    clients = fetch_clients()
    engineers = fetch_engineers()
    raw_tickets = fetch_tickets_detailed()

    now = datetime.now().replace(second=0, microsecond=0)
    enriched_tickets = []
    for t in raw_tickets:
        sla_info = evaluate_sla_status(
            status=t["status"],
            created_at_iso=t["created_at"],
            sla_deadline_iso=t["sla_deadline"],
            resolved_at_iso=t["resolved_at"],
            reference_time=now,
        )
        t_copy = dict(t)
        t_copy.update(sla_info)
        enriched_tickets.append(t_copy)

    active_tickets = [t for t in enriched_tickets if t["status"] != "Решена"]
    engineers_with_load = calculate_engineer_workloads(engineers, active_tickets)
    return clients, engineers_with_load, enriched_tickets


clients_list, engineers_list, tickets_list = load_enriched_data()

# Выделяем активные и закрытые заявки
active_tickets_list = [t for t in tickets_list if t["status"] != "Решена"]
resolved_tickets_list = [t for t in tickets_list if t["status"] == "Решена"]

active_breached_cnt = sum(1 for t in active_tickets_list if t["is_breached"])
active_risk_cnt = sum(1 for t in active_tickets_list if t["is_at_risk"])
active_ok_cnt = sum(1 for t in active_tickets_list if not t["is_breached"] and not t["is_at_risk"])

# ================= БОКОВАЯ ПАНЕЛЬ (SIDEBAR) =================
with st.sidebar:
    st.markdown("## 🛡️ SLA Dispatch Desk")
    st.caption("Сервисная компания **«РитейлТехСервис»**\n*(учебный проект, синтетические данные)*")
    st.divider()

    st.markdown("### 📡 Пульс текущей смены")
    col_s1, col_s2 = st.columns(2)
    col_s1.metric("В работе", len(active_tickets_list))
    col_s2.metric("🟢 В норме", active_ok_cnt)

    col_s3, col_s4 = st.columns(2)
    col_s3.metric("🟡 Риск (<25%)", active_risk_cnt)
    col_s4.metric("🔴 Просрочено", active_breached_cnt)

    st.divider()
    st.markdown("### ⚙️ Управление демо-стендом")
    if st.button("🔄 Сбросить и обновить демо-данные", use_container_width=True):
        seed_demo_data()
        st.toast("Демонстрационные данные успешно пересозданы с привязкой к текущему времени!", icon="✅")
        st.rerun()

    # Подготовка CSV для скачивания
    if tickets_list:
        export_df = pd.DataFrame(tickets_list)[
            [
                "id",
                "created_at",
                "client_name",
                "client_tariff",
                "title",
                "category",
                "priority",
                "status",
                "engineer_name",
                "sla_minutes",
                "sla_deadline",
                "resolved_at",
                "sla_badge",
                "time_comment",
            ]
        ]
        csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 Скачать реестр заявок (CSV)",
            data=csv_bytes,
            file_name="sla_tickets_report.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with st.expander("📖 Нормативы матрицы SLA"):
        sla_table_rows = []
        for t_name, prio_dict in SLA_MATRIX_MINUTES.items():
            sla_table_rows.append(
                {
                    "Тариф": t_name,
                    "Critical": f"{prio_dict['Critical']} м",
                    "High": f"{prio_dict['High']} м",
                    "Medium": f"{prio_dict['Medium']} м",
                    "Low": f"{prio_dict['Low']} м",
                }
            )
        st.dataframe(pd.DataFrame(sla_table_rows), hide_index=True, use_container_width=True)

# ================= ЗАГОЛОВОК СТРАНИЦЫ =================
st.title("Диспетчер клиентских обращений с контролем SLA и автомаршрутизацией")
st.markdown(
    "Автоматизированная система триажа (классификации), расчета контрактных дедлайнов SLA "
    "и взвешенной балансировки нагрузки инженеров технической поддержки."
)

tab_new, tab_queue, tab_team, tab_analytics = st.tabs(
    [
        "➕ 1. Новое обращение (Автотриаж)",
        "📋 2. Очередь заявок и SLA-монитор",
        "👥 3. Команда и баланс нагрузки",
        "📊 4. Аналитика и KPI руководителя",
    ]
)

# ==============================================================================
# ВКЛАДКА 1: РЕГИСТРАЦИЯ И АВТОМАТИЧЕСКАЯ ДИСПЕТЧЕРИЗАЦИЯ
# ==============================================================================
with tab_new:
    st.subheader("Прием и интеллектуальная маршрутизация нового обращения")
    st.info(
        "💡Выберите один из готовых бизнес-сценариев ниже или введите "
        "собственный текст обращения. Система автоматически определит категорию, критичность, "
        "рассчитает дедлайн по тарифу клиента и назначит наименее загруженного профильного инженера."
    )

    demo_presets = {
        "— Ввести текст вручную —": ("", ""),
        "🔥 Сценарий 1: Полная остановка касс в супермаркете (Critical / Кассовое ПО)": (
            "Остановились все кассы в магазине, очередь на входе!",
            "После утренней перезагрузки зависла кассовая программа Фронтол, ни одна касса не пробивает чеки, простой торговой точки.",
        ),
        "⚠️ Сценарий 2: Отказ сканера и принтера чеков (High / Оборудование POS)": (
            "Сломался сканер штрихкодов и не печатает принтер на кассе №3",
            "При нажатии на курок сканер не пикает, а фискальный принтер выдает пустую чековую ленту.",
        ),
        "🌐 Сценарий 3: Ошибка ФН и блокировка ОФД (High / Сеть и Фискализация)": (
            "Ошибка ФН 235: чеки не уходят в ОФД и не проходит обмен с ЕГАИС",
            "На кассе горит предупреждение о переполнении очереди ОФД, связь с роутером нестабильна.",
        ),
        "💬 Сценарий 4: Запрос инструкции по отчету (Low / Консультация)": (
            "Подскажите, как выгрузить отчет по продажам за прошлый месяц",
            "Плановый вопрос от бухгалтерии: нужна инструкция, как сделать сверку возвратов в Excel.",
        ),
    }

    selected_preset = st.selectbox("Быстрый выбор демонстрационного сценария:", list(demo_presets.keys()))
    preset_title, preset_desc = demo_presets[selected_preset]

    col_form, col_preview = st.columns([3, 2], gap="large")

    with col_form:
        client_options = {
            f"{c['name']} — Тариф: {c['tariff']} (Штраф SLA: {c['penalty_rub']} ₽)": c
            for c in clients_list
        }
        selected_client_label = st.selectbox("Контрагент (Клиент):", list(client_options.keys()))
        selected_client = client_options[selected_client_label]

        input_title = st.text_input(
            "Краткая тема обращения *",
            value=preset_title,
            placeholder="Например: Не закрывается кассовая смена на точке №5",
        )
        input_desc = st.text_area(
            "Подробное описание проблемы от клиента *",
            value=preset_desc,
            height=130,
            placeholder="Опишите симптомы сбоя, масштаб проблемы и затронутое оборудование или ПО...",
        )

        manual_override = st.checkbox("Разрешить диспетчеру скорректировать категорию/приоритет вручную перед записью")

        # Предварительный прогон алгоритма в реальном времени
        pred_cat, pred_prio, pred_reason = classify_ticket_text(input_title, input_desc)
        now_dt = datetime.now().replace(second=0, microsecond=0)

        if manual_override:
            ov_col1, ov_col2 = st.columns(2)
            final_cat = ov_col1.selectbox(
                "Категория обращения:",
                CATEGORIES,
                index=CATEGORIES.index(pred_cat) if pred_cat in CATEGORIES else 0,
            )
            prio_list = ["Critical", "High", "Medium", "Low"]
            final_prio = ov_col2.selectbox(
                "Уровень приоритета:",
                prio_list,
                index=prio_list.index(pred_prio),
            )
        else:
            final_cat, final_prio = pred_cat, pred_prio

        sla_min, deadline_dt = calculate_sla_deadline(selected_client["tariff"], final_prio, now_dt)
        best_eng, routing_explanation = select_best_engineer(final_cat, engineers_list, active_tickets_list)

        submit_btn = st.button("🚀 Зарегистрировать и маршрутизировать заявку", type="primary", use_container_width=True)

        if submit_btn:
            if len(input_title.strip()) < 5:
                st.error("Ошибка валидации: укажите содержательную тему обращения (не менее 5 символов).")
            elif len(input_desc.strip()) < 10:
                st.error("Ошибка валидации: укажите подробное описание проблемы (не менее 10 символов).")
            elif not best_eng:
                st.error("Ошибка маршрутизации: в системе нет доступных инженеров.")
            else:
                new_ticket_id = create_ticket(
                    client_id=selected_client["id"],
                    title=input_title,
                    description=input_desc,
                    category=final_cat,
                    priority=final_prio,
                    engineer_id=best_eng["id"],
                    sla_minutes=sla_min,
                    created_at_iso=now_dt.isoformat(timespec="minutes"),
                    sla_deadline_iso=deadline_dt.isoformat(timespec="minutes"),
                )
                st.success(
                    f"✅ Заявка **#{new_ticket_id}** успешно зарегистрирована! "
                    f"Исполнитель: **{best_eng['full_name']}**, дедлайн SLA: **{deadline_dt.strftime('%d.%m.%Y %H:%M')}**."
                )
                st.rerun()

    with col_preview:
        st.markdown("#### 🧠 Решение алгоритма диспетчеризации (Предпросмотр)")
        with st.container(border=True):
            st.markdown(f"**1. Клиент и контракт:** `{selected_client['name']}`")
            st.markdown(
                f"**Тариф SLA:** `{selected_client['tariff']}` | "
                f"**Риск штрафа при просрочке:** `{selected_client['penalty_rub']} ₽`"
            )
            st.divider()

            prio_badge_map = {
                "Critical": "🔴 Critical (Критический — 4 балла)",
                "High": "🟠 High (Высокий — 3 балла)",
                "Medium": "🔵 Medium (Средний — 2 балла)",
                "Low": "🟢 Low (Низкий — 1 балл)",
            }
            st.markdown(f"**2. Распознанная категория:** `{final_cat}`")
            st.markdown(f"**3. Расчетный приоритет:** {prio_badge_map.get(final_prio, final_prio)}")
            st.caption(f"🔎 *Обоснование NLP-анализатора:* {pred_reason}")
            st.divider()

            st.markdown(f"**4. Норматив решения по SLA:** `{sla_min} мин` ({sla_min / 60:.1f} ч)")
            st.markdown(f"**Крайний срок (SLA Deadline):** `{deadline_dt.strftime('%d.%m.%Y %H:%M')}`")
            st.divider()

            if best_eng:
                st.markdown(f"**5. Назначенный исполнитель:** 👤 **{best_eng['full_name']}** ({best_eng['grade']})")
                st.caption(f"⚙️ *Логика балансировщика:* {routing_explanation}")

# ==============================================================================
# ВКЛАДКА 2: ОЧЕРЕДЬ ЗАЯВОК И ОПЕРАТИВНЫЙ КОНТРОЛЬ SLA
# ==============================================================================
with tab_queue:
    st.subheader("Оперативный монитор очереди обращений и контроль дедлайнов SLA")

    # Панель фильтров
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    filter_mode = f_col1.selectbox(
        "Режим отображения:",
        [
            "Только активные (в очереди)",
            "Все заявки (включая закрытые)",
            "Только закрытые (Решена)",
        ],
    )
    filter_sla = f_col2.selectbox(
        "Фильтр по статусу SLA:",
        [
            "Все статусы SLA",
            "🔴 Просрочено / SLA нарушен",
            "🟡 Риск просрочки (<25% времени)",
            "🟢 В норме / SLA выполнен",
        ],
    )
    eng_names = ["Все инженеры"] + [e["full_name"] for e in engineers_list]
    filter_eng = f_col3.selectbox("Инженер-исполнитель:", eng_names)
    filter_prio = f_col4.selectbox("Приоритет:", ["Все приоритеты", "Critical", "High", "Medium", "Low"])

    # Применение фильтров
    filtered_tickets = []
    for t in tickets_list:
        if filter_mode == "Только активные (в очереди)" and t["status"] == "Решена":
            continue
        if filter_mode == "Только закрытые (Решена)" and t["status"] != "Решена":
            continue
        if filter_sla == "🔴 Просрочено / SLA нарушен" and t["sla_code"] != "BREACHED":
            continue
        if filter_sla == "🟡 Риск просрочки (<25% времени)" and t["sla_code"] != "AT_RISK":
            continue
        if filter_sla == "🟢 В норме / SLA выполнен" and t["sla_code"] != "OK":
            continue
        if filter_eng != "Все инженеры" and t["engineer_name"] != filter_eng:
            continue
        if filter_prio != "Все приоритеты" and t["priority"] != filter_prio:
            continue
        filtered_tickets.append(t)

    # Сортировка: сначала активные с наименьшим остатком времени SLA, затем по приоритету
    filtered_tickets.sort(
        key=lambda x: (
            1 if x["status"] == "Решена" else 0,
            x["remaining_min"],
            PRIORITY_ORDER.get(x["priority"], 3),
        )
    )

    if not filtered_tickets:
        st.warning("По выбранным фильтрам заявок не найдено.")
    else:
        table_rows = []
        for t in filtered_tickets:
            table_rows.append(
                {
                    "ID": f"#{t['id']}",
                    "Индикатор SLA": t["sla_badge"],
                    "Контрагент (Тариф)": f"{t['client_name']} [{t['client_tariff']}]",
                    "Тема обращения": t["title"],
                    "Категория": t["category"],
                    "Приоритет": t["priority"],
                    "Статус тикета": t["status"],
                    "Исполнитель": t["engineer_name"],
                    "Создана": t["created_at"].replace("T", " "),
                    "Дедлайн SLA": t["sla_deadline"].replace("T", " "),
                    "Запас / Просрочка": t["time_comment"],
                }
            )
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### 🛠️ Карточка управления заявкой (Рабочее место инженера / диспетчера)")

    ticket_map = {
        f"#{t['id']} | {t['sla_badge']} | [{t['priority']}] {t['title']} ({t['client_name']})": t
        for t in tickets_list
    }
    selected_ticket_label = st.selectbox("Выберите заявку для просмотра деталей или смены статуса:", list(ticket_map.keys()))
    sel_t = ticket_map[selected_ticket_label]

    det_col1, det_col2 = st.columns([3, 2], gap="large")
    with det_col1:
        with st.container(border=True):
            st.markdown(f"##### Заявка #{sel_t['id']}: {sel_t['title']}")
            st.markdown(
                f"**Клиент:** {sel_t['client_name']} (`{sel_t['client_tariff']}`) | "
                f"**Контакт:** {sel_t['client_contact']}"
            )
            st.markdown(f"**Описание проблемы:**\n> {sel_t['description']}")
            st.markdown(
                f"**Категория:** `{sel_t['category']}` | "
                f"**Норматив SLA:** `{sel_t['sla_minutes']} мин` | "
                f"**Текущий статус SLA:** {sel_t['sla_badge']} ({sel_t['time_comment']})"
            )
            if sel_t["resolved_at"]:
                st.markdown(f"**Время закрытия:** `{sel_t['resolved_at'].replace('T', ' ')}`")

    with det_col2:
        with st.form(key=f"update_ticket_form_{sel_t['id']}"):
            st.markdown("##### Изменить параметры / Закрыть тикет")
            statuses_list = ["Новая", "В работе", "Ожидает ответа", "Решена"]
            new_st = st.selectbox(
                "Статус заявки:",
                statuses_list,
                index=statuses_list.index(sel_t["status"]) if sel_t["status"] in statuses_list else 0,
            )

            prio_list = ["Critical", "High", "Medium", "Low"]
            new_pr = st.selectbox(
                "Приоритет:",
                prio_list,
                index=prio_list.index(sel_t["priority"]) if sel_t["priority"] in prio_list else 2,
            )

            eng_id_map = {f"{e['full_name']} ({e['specialty']})": e["id"] for e in engineers_list}
            current_eng_label = next(
                (k for k, v in eng_id_map.items() if v == sel_t["engineer_id"]),
                list(eng_id_map.keys())[0],
            )
            new_eng_label = st.selectbox(
                "Назначенный инженер:",
                list(eng_id_map.keys()),
                index=list(eng_id_map.keys()).index(current_eng_label),
            )

            new_note = st.text_area(
                "Комментарий инженера / Решение проблемы:",
                value=sel_t["resolution_note"] or "",
                placeholder="Укажите выполненные работы при переводе в статус «Решена»...",
            )

            save_changes = st.form_submit_button("💾 Сохранить изменения по заявке", use_container_width=True)
            if save_changes:
                if new_st == "Решена" and len(new_note.strip()) < 5:
                    st.error("При закрытии заявки («Решена») необходимо указать комментарий о выполненном решении.")
                else:
                    update_ticket_status(
                        ticket_id=sel_t["id"],
                        new_status=new_st,
                        engineer_id=eng_id_map[new_eng_label],
                        priority=new_pr,
                        resolution_note=new_note,
                    )
                    st.success(f"Изменения по заявке #{sel_t['id']} успешно сохранены!")
                    st.rerun()

# ==============================================================================
# ВКЛАДКА 3: КОМАНДА И БАЛАНСИРОВКА НАГРУЗКИ ИНЖЕНЕРОВ
# ==============================================================================
with tab_team:
    st.subheader("Мониторинг загрузки инженеров и управление сменой")
    st.markdown(
        "Алгоритм **Smart Routing** оценивает загрузку не просто по числу заявок, "
        "а по **взвешенному индексу сложности (Workload Score)**: "
        "`Critical = 4 балла`, `High = 3 балла`, `Medium = 2 балла`, `Low = 1 балл`."
    )

    eng_df_rows = []
    for e in engineers_list:
        load_level = "🟢 Оптимальная"
        if e["workload_score"] >= 8:
            load_level = "🔴 Перегрузка"
        elif e["workload_score"] >= 5:
            load_level = "🟡 Высокая"

        eng_df_rows.append(
            {
                "ID": e["id"],
                "ФИО инженера": e["full_name"],
                "Профиль специализации": e["specialty"],
                "Грейд": e["grade"],
                "Статус смены": "🟢 На смене" if e["is_active"] else "⚪ Вне смены",
                "Активных тикетов": e["active_count"],
                "Из них Critical": e["critical_count"],
                "Индекс загрузки (баллы)": e["workload_score"],
                "Уровень нагрузки": load_level,
            }
        )

    eng_df = pd.DataFrame(eng_df_rows)
    st.dataframe(eng_df, use_container_width=True, hide_index=True)

    col_chart_load, col_shift_ctrl = st.columns([3, 2], gap="large")
    with col_chart_load:
        fig_load = px.bar(
            eng_df,
            x="ФИО инженера",
            y="Индекс загрузки (баллы)",
            color="Профиль специализации",
            text="Активных тикетов",
            title="Взвешенный индекс текущей нагрузки по инженерам (баллы тяжести тикетов)",
        )
        fig_load.update_traces(texttemplate="Тикетов: %{text}", textposition="outside")
        fig_load.update_layout(yaxis_range=[0, max(eng_df["Индекс загрузки (баллы)"].max() + 3, 10)])
        st.plotly_chart(fig_load, use_container_width=True)

    with col_shift_ctrl:
        st.markdown("#### 🔄 Управление доступностью на смене")
        st.caption(
            "Если перевести специалиста в статус «Вне смены», автомаршрутизатор "
            "перестанет назначать на него новые заявки и перенаправит поток на коллег или «Универсала»."
        )
        for e in engineers_list:
            c1, c2 = st.columns([3, 2])
            status_icon = "🟢" if e["is_active"] else "⚪"
            c1.markdown(f"{status_icon} **{e['full_name']}**  \n*{e['specialty']}*")
            btn_label = "Вывести со смены" if e["is_active"] else "Вернуть на смену"
            if c2.button(btn_label, key=f"shift_btn_{e['id']}", use_container_width=True):
                toggle_engineer_shift(e["id"], 0 if e["is_active"] else 1)
                st.rerun()

# ==============================================================================
# ВКЛАДКА 4: АНАЛИТИЧЕСКИЙ ДАШБОРД И KPI РУКОВОДИТЕЛЯ
# ==============================================================================
with tab_analytics:
    st.subheader("Сводная аналитика выполнения SLA и операционных KPI")

    # Расчет KPI по закрытым и активным заявкам
    total_resolved = len(resolved_tickets_list)
    resolved_on_time = sum(1 for t in resolved_tickets_list if not t["is_breached"])
    sla_compliance_rate = (resolved_on_time / total_resolved * 100.0) if total_resolved > 0 else 100.0

    # Среднее время решения (MTTR) в минутах и часах по закрытым тикетам
    resolution_durations = []
    for t in resolved_tickets_list:
        if t["resolved_at"]:
            c_dt = datetime.fromisoformat(t["created_at"])
            r_dt = datetime.fromisoformat(t["resolved_at"])
            resolution_durations.append((r_dt - c_dt).total_seconds() / 60.0)

    avg_mttr_min = sum(resolution_durations) / len(resolution_durations) if resolution_durations else 0.0

    # Финансовая оценка штрафных рисков (по всем просроченным тикетам: и закрытым с опозданием, и текущим просроченным)
    all_breached_tickets = [t for t in tickets_list if t["is_breached"]]
    total_penalty_rub = sum(int(t["client_penalty_rub"]) for t in all_breached_tickets)

    # Коэффициент дисбаланса нагрузки среди активных инженеров
    active_eng_scores = [e["workload_score"] for e in engineers_list if e["is_active"]]
    if active_eng_scores and sum(active_eng_scores) > 0:
        avg_score = sum(active_eng_scores) / len(active_eng_scores)
        imbalance_ratio = max(active_eng_scores) / avg_score if avg_score > 0 else 1.0
    else:
        imbalance_ratio = 1.0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric(
        "SLA Compliance Rate (Закрытые)",
        f"{sla_compliance_rate:.1f}%",
        delta=f"{resolved_on_time} из {total_resolved} в срок",
    )
    kpi2.metric(
        "Среднее время решения (MTTR)",
        f"{avg_mttr_min:.0f} мин ({avg_mttr_min / 60:.1f} ч)",
        delta="Целевой порог < 180 мин",
    )
    kpi3.metric(
        "Штрафные потери из-за срывов SLA",
        f"{total_penalty_rub:,} ₽".replace(",", " "),
        delta=f"Просрочено тикетов: {len(all_breached_tickets)}",
        delta_color="inverse",
    )
    kpi4.metric(
        "Коэффициент баланса нагрузки",
        f"{imbalance_ratio:.2f}",
        delta="Норма: 1.00 – 1.35",
    )

    st.divider()

    g_col1, g_col2 = st.columns(2)

    with g_col1:
        # График 1: Распределение статусов SLA по категориям проблем
        cat_sla_df = pd.DataFrame(tickets_list)
        if not cat_sla_df.empty:
            fig_cat = px.histogram(
                cat_sla_df,
                x="category",
                color="sla_badge",
                barmode="group",
                title="Соблюдение SLA в разрезе категорий инцидентов",
                labels={"category": "Категория проблемы", "count": "Количество заявок", "sla_badge": "Статус SLA"},
                color_discrete_map={
                    "🟢 В норме": "#2ecc71",
                    "🟢 SLA выполнен": "#27ae60",
                    "🟡 Риск просрочки": "#f1c40f",
                    "🔴 Просрочено": "#e74c3c",
                    "🔴 SLA нарушен": "#c0392b",
                },
            )
            st.plotly_chart(fig_cat, use_container_width=True)

    with g_col2:
        # График 2: Структура обращений по тарифам клиентов и приоритетам
        if not cat_sla_df.empty:
            fig_tariff = px.sunburst(
                cat_sla_df,
                path=["client_tariff", "priority", "sla_code"],
                title="Иерархия обращений: Тариф клиента → Приоритет → Результат SLA",
            )
            st.plotly_chart(fig_tariff, use_container_width=True)

    st.markdown("#### 📋 Детализация нарушений SLA и зон риска (Контрольный список для руководителя)")
    problem_tickets = [t for t in tickets_list if t["is_breached"] or t["is_at_risk"]]
    if not problem_tickets:
        st.success("Отличная работа смены! Просроченных и находящихся под угрозой срыва заявок нет.")
    else:
        prob_rows = []
        for t in problem_tickets:
            prob_rows.append(
                {
                    "ID": f"#{t['id']}",
                    "Статус SLA": t["sla_badge"],
                    "Клиент": t["client_name"],
                    "Тариф": t["client_tariff"],
                    "Приоритет": t["priority"],
                    "Категория": t["category"],
                    "Инженер": t["engineer_name"],
                    "Статус работы": t["status"],
                    "Отклонение времени": t["time_comment"],
                    "Штраф по договору (₽)": t["client_penalty_rub"] if t["is_breached"] else 0,
                }
            )
        st.dataframe(pd.DataFrame(prob_rows), use_container_width=True, hide_index=True)
