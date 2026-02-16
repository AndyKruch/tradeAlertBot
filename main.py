# main.py
import asyncio
from alerting import AlertSystem
from instruments import instruments_for_analize
import config


async def main():
    # Создаем систему алертов
    alert_system = AlertSystem(config.TOKEN, app_name=config.APP_NAME)

    # Инициализируем инструменты
    alert_system.initialize(instruments_for_analize)

    try:
        # Запускаем мониторинг на заданное количество часов
        await alert_system.start_monitoring(hours=config.DEFAULT_MONITOR_HOURS)
    except KeyboardInterrupt:
        print("\n\n🛑 Мониторинг остановлен пользователем")
        alert_system.running = False
    except Exception as e:
        print(f"\n❌ Ошибка в работе системы: {e}")
        import traceback
        traceback.print_exc()
    finally:
        alert_system.running = False
        alert_system.print_stats()
        print("\n✅ Мониторинг завершен")


if __name__ == "__main__":
    asyncio.run(main())