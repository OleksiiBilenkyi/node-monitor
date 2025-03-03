import discord
from discord.ext import tasks
from datetime import datetime
import paramiko
import aiosqlite
from data_base import get_server_info, get_ignored_containers
import logging
import os

def setup_commands(bot):
    bot.monitor_state = {"messages": {}, "servers": [], "container_cache": {}}

    # Налаштування логування
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True) 
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "bot.log"), encoding="utf-8"),
            logging.StreamHandler()  # Логи в stdout для Docker
        ]
    )

    async def check_permissions(ctx):
        if not bot.allowed_users or ctx.author.id in bot.allowed_users:
            return True
        await ctx.reply("У тебе немає доступу до цієї команди!", delete_after=5)
        await ctx.message.delete()
        return False

    @bot.command(name="help")
    async def custom_help(ctx):
        text = (
            "**Допомога**\n"
            "```css\n"
            "!add_server <ip> <username> <password> [name] [port] - Додає сервер до моніторингу (порт за замовчуванням 22).\n"
            "!ignore_container <name> - Ігнорує контейнер у моніторингу.\n"
            "!unignore_container <name> - Прибирає контейнер зі списку ігнорованих.\n"
            "!start_monitor - Запускає моніторинг серверів.\n"
            "!force_update - Примусово оновлює дані.\n"
            "!help - Показує цей список команд.\n"
            "```"
        )
        await ctx.send(text)

    @bot.command()
    async def add_server(ctx, ip, username, password, name=None, port: int = 22):
        if not await check_permissions(ctx):
            return
        async with aiosqlite.connect("servers.db") as db:
            await db.execute("INSERT INTO servers (ip, port, username, password, name) VALUES (?, ?, ?, ?, ?)",
                             (ip, port, username, password, name))
            await db.commit()
        await ctx.reply(f"Сервер {ip} ({name or 'без імені'}) додано!", delete_after=5)
        await ctx.message.delete()

    @bot.command()
    async def ignore_container(ctx, container_name):
        if not await check_permissions(ctx):
            return
        try:
            async with aiosqlite.connect("servers.db") as db:
                await db.execute("INSERT INTO ignored_containers (name) VALUES (?)", (container_name,))
                await db.commit()
            await ctx.reply(f"Контейнер `{container_name}` додано до списку ігнорованих.", delete_after=5)
        except Exception:
            await ctx.reply(f"Контейнер `{container_name}` уже в списку ігнорованих!", delete_after=5)
        await ctx.message.delete()

    @bot.command()
    async def unignore_container(ctx, container_name):
        if not await check_permissions(ctx):
            return
        async with aiosqlite.connect("servers.db") as db:
            await db.execute("DELETE FROM ignored_containers WHERE name = ?", (container_name,))
            await db.commit()
        await ctx.reply(f"Контейнер `{container_name}` видалено зі списку ігнорованих.", delete_after=5)
        await ctx.message.delete()

    @bot.command()
    async def start_monitor(ctx):
        if not await check_permissions(ctx):
            return
        async with aiosqlite.connect("servers.db") as db:
            async with db.execute("SELECT * FROM servers") as cursor:
                servers = await cursor.fetchall()
        
        if not servers:
            await ctx.reply("Додай сервери в базу даних спочатку!", delete_after=5)
            await ctx.message.delete()
            return

        bot.monitor_state["servers"] = list(servers)
        bot.monitor_state["messages"] = {}
        bot.monitor_state["container_cache"] = {}
        for server in servers:
            server_id, ip, _, _, _, name = server
            message = await ctx.reply(f"**Сервер {name or 'без імені'} ({ip})**: Завантаження даних...")
            bot.monitor_state["messages"][ip] = message
            bot.monitor_state["container_cache"][ip] = []

        update_status.change_interval(seconds=1800)  # Оновлення кожні 30 хвилин
        update_status.start(ctx.channel, servers)
        await ctx.message.delete()

    @bot.command()
    async def force_update(ctx):
        if not await check_permissions(ctx):
            return
        if update_status.is_running():
            if bot.monitor_state["messages"] and bot.monitor_state["servers"]:
                await update_status.coro(ctx.channel, bot.monitor_state["servers"])
                await ctx.reply("Дані примусово оновлено!", delete_after=5)
            else:
                await ctx.reply("Помилка: стан моніторингу не знайдено!", delete_after=5)
        else:
            await ctx.reply("Моніторинг не запущено! Спочатку виконай !start_monitor.", delete_after=5)
        await ctx.message.delete()

    @tasks.loop()
    async def update_status(channel, servers):
        async with aiosqlite.connect("servers.db") as db:
            async with db.execute("SELECT * FROM servers") as cursor:
                current_servers = await cursor.fetchall()
        
        current_server_ips = {server[1] for server in current_servers}
        monitored_ips = {server[1] for server in bot.monitor_state["servers"]}
        
        for server in current_servers:
            server_id, ip, port, username, password, name = server
            if ip not in monitored_ips:
                logging.info(f"Виявлено новий сервер: {name or 'без імені'} ({ip})")
                bot.monitor_state["servers"].append(server)
                message = await channel.send(f"**Сервер {name or 'без імені'} ({ip})**: Завантаження даних...")
                bot.monitor_state["messages"][ip] = message
                bot.monitor_state["container_cache"][ip] = []

        for server in bot.monitor_state["servers"]:
            server_id, ip, port, username, password, name = server
            server_info = await get_server_info({"ip": ip, "port": port, "username": username, "password": password})
            logging.debug(f"Server info for {ip}: {server_info}")
            
            if isinstance(server_info, str):
                text = f"**Сервер {name or 'без імені'} ({ip})**: *{server_info}*\n*Останнє оновлення: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*"
            else:
                text = f"**Сервер {name or 'без імені'} ({ip})**\n"
                text += f"*Кількість контейнерів*: {len(server_info['containers'])}\n"
                text += f"*Навантаження*: CPU {server_info['cpu']}%, RAM {server_info['mem']}, Диск {server_info['disk']}\n"
                text += f"*Час роботи*: {server_info['uptime']}\n"
                text += "----------------------------------------\n"
                
                if server_info['containers']:
                    cached_names = {c['name'] for c in bot.monitor_state["container_cache"][ip]}
                    current_names = {c['name'] for c in server_info['containers']}
                    new_containers = current_names - cached_names
                    if new_containers:
                        logging.info(f"Нові контейнери на {ip}: {new_containers}")
                    
                    bot.monitor_state["container_cache"][ip] = server_info['containers']
                    
                    text += "```css\nСтатус Ім’я            Час роботи           CPU      RAM\n" + "-" * 50 + "\n"
                    for c in server_info['containers']:
                        status = "🟢" if c['status'] == "running" else "🔴"
                        text += f"{status} {c['name']:<15} {c['uptime']:<20} {c['cpu_load']:<8} {c['mem_load']:<8}\n"
                    text += "```\n"
                else:
                    text += "*Контейнери*: Немає\n"
                text += f"*Останнє оновлення: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*"
            
            logging.debug(f"Updating text for {ip}: {text}")
            message = bot.monitor_state["messages"].get(ip)
            if message:
                await message.edit(content=text.split('\n')[0] + '\n' + '\n'.join(text.split('\n')[1:]))
