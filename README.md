# Node Monitor Bot

Цей проєкт — бот для Discord, який моніторить сервери та їхні Docker-контейнери через SSH, відображаючи статус, навантаження CPU/RAM і час роботи. Бот автоматично виявляє нові сервери та контейнери без перезапуску.

## Основні функції
- Моніторинг серверів і контейнерів із періодичним оновленням (кожні 30 хвилин).
- Автоматичне виявлення нових серверів, доданих до бази після запуску.
- Автоматичне виявлення нових контейнерів на серверах.
- Гарно форматований текстовий вивід із емодзі статусу (🟢 для працюючих, 🔴 для зупинених).
- Збереження стану між перезапусками через Docker-томи.

## Вимоги
- Docker і Docker Compose
- Python 3.12 (встановлюється в контейнері)
- Залежності: `discord.py`, `paramiko`, `aiosqlite` (вказані в `requirements.txt`)

## Структура проєкту

- `node-monitor/`
  - `Dockerfile` — Опис побудови Docker-образу
  - `docker-compose.yml` — Конфігурація запуску контейнера
  - `.dockerignore` — Виключення непотрібних файлів із копіювання
  - `main.py` — Точка входу
  - `bot.py` — Налаштування бота
  - `bot_commands.py` — Команди бота
  - `data_base.py` — Логіка роботи з базою та SSH
  - `log_setting.py` — Налаштування логування
  - `requirements.txt` — Залежності Python
  - `.env` — Змінні середовища (токен, користувачі)
  - `data/` — Том для бази даних (`servers.db`)
  - `logs/` — Том для логів (`bot.log`)

## Встановлення та запуск

### 1. Клонування репозиторію
```bash
git clone <repository_url>
cd node-monitor
```

### 2. Налаштування .env
Створіть файл `.env` у корені проєкту та додайте:
```
DISCORD_TOKEN=твій_токен_бота
ALLOWED_USERS=твій_discord_id,інший_id
```

### 3. Створення директорій для томів
```bash
mkdir -p data logs
```

### 4. Побудова та запуск через Docker Compose
```bash
docker-compose up --build
```
- Бот запуститься в контейнері `node-monitor`.
- Логи виводяться в термінал і зберігаються в `logs/bot.log`.

### 5. Зупинка
```bash
docker-compose down
```

### 6. Перегляд логів
- У терміналі: `docker logs node-monitor`
- У файлі: `cat logs/bot.log`

## Використання команд
- `!add_server <ip> <username> <password> [name] [port]` — Додає сервер до моніторингу.
- `!ignore_container <name>` — Ігнорує контейнер у моніторингу.
- `!unignore_container <name>` — Прибирає контейнер зі списку ігнорованих.
- `!start_monitor` — Запускає моніторинг серверів.
- `!force_update` — Примусово оновлює дані.
- `!help` — Показує список команд.

