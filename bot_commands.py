import discord
from discord.ext import tasks
from datetime import datetime
import paramiko
import aiosqlite
from data_base import get_server_info, get_ignored_containers
import logging
import os
import asyncio

class PaginationView(discord.ui.View):
    def __init__(self, server_ip, server_info, containers, page=0, timeout=None):
        super().__init__(timeout=timeout)
        self.server_ip = server_ip
        self.server_info = server_info
        self.containers = containers
        self.page = page
        self.per_page = 20
        self.total_pages = (len(containers) + self.per_page - 1) // self.per_page

    @discord.ui.button(label="Попередня", style=discord.ButtonStyle.grey, disabled=True)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await self.update_message(interaction)
        button.disabled = self.page == 0
        self.next.disabled = self.page == self.total_pages - 1
        await interaction.response.edit_message(content=self.get_message_text(), view=self)

    @discord.ui.button(label="Наступна", style=discord.ButtonStyle.grey)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
            await self.update_message(interaction)
        button.disabled = self.page == self.total_pages - 1
        self.previous.disabled = self.page == 0
        await interaction.response.edit_message(content=self.get_message_text(), view=self)

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=self.get_message_text(), view=self)

    def get_message_text(self):
        start = self.page * self.per_page
        end = min(start + self.per_page, len(self.containers))
        text = f"**Сервер {self.server_ip}**\n"
        text += f"*Кількість контейнерів*: {len(self.containers)}\n"
        text += f"*Навантаження*: CPU {self.server_info['cpu']}%, RAM {self.server_info['mem']}, Диск {self.server_info['disk']}\n"
        text += f"*Час роботи*: {self.server_info['uptime']}\n"
        text += "----------------------------------------\n"
        if self.total_pages > 1:
            text += f"Сторінка {self.page + 1}/{self.total_pages}\n"
        text += "```css\nСтатус Ім’я            Час роботи           CPU      RAM\n" + "-" * 50 + "\n"
        for c in self.containers[start:end]:
            status = "🟢" if c['status'] == "running" else "🔴"
            text += f"{status} {c['name']:<15} {c['uptime'][:20]:<20} {c['cpu_load']:<8} {c['mem_load']:<8}\n"
        text += "```\n"
        text += f"*Останнє оновлення: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*"
        return text

def setup_commands(bot):
    bot.monitor_state = {"messages": {}, "servers": [], "container_cache": {}}
    bot.allowed_users = set(map(int, os.getenv("ALLOWED_USERS", "313381427586531340").split(",")))

    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "bot.log"), encoding="utf-8"),
            logging.StreamHandler()
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
            "!add_server <ip> <username> <password> [name] [port] - Додає сервер.\n"
            "!ignore_container <name> - Ігнорує контейнер.\n"
            "!unignore_container <name> - Прибирає зі списку ігнорованих.\n"
            "!start_monitor - Запускає моніторинг.\n"
            "!force_update - Оновлює дані.\n"
            "!sh <ip> <command> - Виконує команду на сервері (тільки для дозволених).\n"
            "!help - Показує команди.\n"
            "```"
        )
        await ctx.send(text)

    @bot.command()
    async def add_server(ctx, ip, username, password, name=None, port: int = 22):
        if not await check_permissions(ctx):
            return
        async with aiosqlite.connect("servers.db") as db:  # Змінено шлях
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
            async with aiosqlite.connect("servers.db") as db:  # Змінено шлях
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
        async with aiosqlite.connect("servers.db") as db:  # Змінено шлях
            await db.execute("DELETE FROM ignored_containers WHERE name = ?", (container_name,))
            await db.commit()
        await ctx.reply(f"Контейнер `{container_name}` видалено зі списку ігнорованих.", delete_after=5)
        await ctx.message.delete()

    @bot.command()
    async def start_monitor(ctx):
        if not await check_permissions(ctx):
            return
        async with aiosqlite.connect("servers.db") as db:  # Змінено шлях
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
            text = f"**Сервер {name or 'без імені'} ({ip})**\n*Завантаження даних...*"
            message = await ctx.send(text)
            bot.monitor_state["messages"][ip] = message
            bot.monitor_state["container_cache"][ip] = []

        update_status.change_interval(seconds=1800)
        update_status.start(ctx.channel, servers)
        # await ctx.message.delete()  # Залишаємо команду в чаті

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
        # await ctx.message.delete()  # Залишаємо команду в чаті

    @bot.command()
    async def sh(ctx, ip: str, *, command: str):
        if ctx.author.id not in bot.allowed_users:
            await ctx.reply("У тебе немає доступу до цієї команди!", delete_after=5)
            await ctx.message.delete()
            return

        async with aiosqlite.connect("servers.db") as db:  # Змінено шлях
            async with db.execute("SELECT * FROM servers WHERE ip = ?", (ip,)) as cursor:
                server = await cursor.fetchone()
        
        if not server:
            await ctx.reply(f"Сервер з IP {ip} не знайдено в базі!", delete_after=5)
            return

        server_id, ip, port, username, password, name = server
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            await asyncio.to_thread(ssh.connect, ip, port=port or 22, username=username, password=password)
            stdin, stdout, stderr = await asyncio.to_thread(ssh.exec_command, command)
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            
            response = f"**Виконання команди на {name or 'без імені'} ({ip})**\n"
            response += f"*Команда*: `{command}`\n"
            if output:
                response += f"*Вивід*:\n```\n{output[:1000]}\n```\n"
            if error:
                response += f"*Помилка*:\n```\n{error[:1000]}\n```\n"
            if not output and not error:
                response += "*Виводу немає*\n"
            await ctx.reply(response)
        except Exception as e:
            await ctx.reply(f"Помилка виконання команди: {str(e)}", delete_after=10)
        finally:
            ssh.close()

    @tasks.loop()
    async def update_status(channel, servers):
        async with aiosqlite.connect("servers.db") as db:  # Змінено шлях
            async with db.execute("SELECT * FROM servers") as cursor:
                current_servers = await cursor.fetchall()
        
        current_server_ips = {server[1] for server in current_servers}
        monitored_ips = {server[1] for server in bot.monitor_state["servers"]}
        
        for server in current_servers:
            server_id, ip, port, username, password, name = server
            if ip not in monitored_ips:
                logging.info(f"Виявлено новий сервер: {name or 'без імені'} ({ip})")
                bot.monitor_state["servers"].append(server)
                text = f"**Сервер {name or 'без імені'} ({ip})**\n*Завантаження даних...*"
                message = await channel.send(text)
                bot.monitor_state["messages"][ip] = message
                bot.monitor_state["container_cache"][ip] = []

        for server in bot.monitor_state["servers"]:
            server_id, ip, port, username, password, name = server
            server_info = await get_server_info({"ip": ip, "port": port, "username": username, "password": password})
            logging.debug(f"Server info for {ip}: {server_info}")
            
            if isinstance(server_info, str):
                text = f"**Сервер {name or 'без імені'} ({ip})**\n*{server_info}*\n*Останнє оновлення: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*"
            else:
                text = f"**Сервер {name or 'без імені'} ({ip})**\n"
                text += f"*Кількість контейнерів*: {len(server_info['containers'])}\n"
                text += f"*Навантаження*: CPU {server_info['cpu']}%, RAM {server_info['mem']}, Диск {server_info['disk']}\n"
                text += f"*Час роботи*: {server_info['uptime']}\n"
                text += "----------------------------------------\n"
                
                cached_names = {c['name'] for c in bot.monitor_state["container_cache"][ip]}
                current_names = {c['name'] for c in server_info['containers']}
                new_containers = current_names - cached_names
                if new_containers:
                    logging.info(f"Нові контейнери на {ip}: {new_containers}")
                
                bot.monitor_state["container_cache"][ip] = server_info['containers']
                
                if server_info['containers']:
                    start = 0
                    per_page = 20
                    end = min(per_page, len(server_info['containers']))
                    total_pages = (len(server_info['containers']) + per_page - 1) // per_page
                    if total_pages > 1:
                        text += f"Сторінка 1/{total_pages}\n"
                    text += "```css\nСтатус Ім’я            Час роботи           CPU      RAM\n" + "-" * 50 + "\n"
                    for c in server_info['containers'][start:end]:
                        status = "🟢" if c['status'] == "running" else "🔴"
                        text += f"{status} {c['name']:<15} {c['uptime'][:20]:<20} {c['cpu_load']:<8} {c['mem_load']:<8}\n"
                    text += "```\n"
                else:
                    text += "*Контейнери*: Немає\n"
                text += f"*Останнє оновлення: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*"
            
            message = bot.monitor_state["messages"].get(ip)
            if message:
                view = PaginationView(ip, server_info, server_info['containers']) if server_info['containers'] and total_pages > 1 else None
                await message.edit(content=text, view=view)
