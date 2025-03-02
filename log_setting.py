import logging
import sys

def setup_logging():
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    
    logging.basicConfig(
        level=logging.DEBUG,  # Змінюємо на DEBUG для детальнішого виведення
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.info("Логування налаштовано.")