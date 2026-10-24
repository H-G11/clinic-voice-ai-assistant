"""UI scope text derived from the actually loaded local schedule."""


def schedule_presentation(store, clinic_mode: bool) -> dict[str, str]:
    with store.connect() as database:
        doctors = database.execute('SELECT COUNT(*) FROM doctors').fetchone()[0]
        slots = database.execute('SELECT COUNT(*) FROM slots').fetchone()[0]
    greeting = ('Здравствуйте! Чем помочь: записаться, перенести приём, отменить запись или узнать её статус?'
                if clinic_mode else 'Здравствуйте! Это синтетическое демо новой записи. К какому специалисту вас записать?')
    policy = ('Расписание GMT+4: ближайшие 14 календарных дней, на сегодня минимум за 30 минут.'
              if clinic_mode else 'Синтетический пример: локальное системное время, только новая запись. Перенос и отмена доступны в отдельном service demo.')
    return {'greeting': greeting, 'policy': policy,
            'schedule': f"Расписание: врачи — {doctors}; слоты — {slots}. Источник: {'case Excel' if clinic_mode else 'синтетический шаблон'}."}
