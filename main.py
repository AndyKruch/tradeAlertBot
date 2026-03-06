# main.py
import asyncio
from alerting import AlertSystem
from instruments import instruments_for_analize
from trading.trade_logger import TradeLogger
import config


async def main():
    logger = TradeLogger()
    alert_system = AlertSystem(config.TOKEN, app_name=config.APP_NAME, logger=logger)
    alert_system.initialize(instruments_for_analize)

    try:
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
        await logger.stop()  # ждём завершения записи всех сделок
        print("\n✅ Мониторинг завершен, все сделки сохранены в trades.csv")


if __name__ == "__main__":
    asyncio.run(main())
