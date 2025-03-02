import aiosqlite
import paramiko
import asyncio
import logging

async def init_db():
    async with aiosqlite.connect("servers.db") as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                port INTEGER,
                username TEXT,
                password TEXT,
                name TEXT
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS containers (
                server_id INTEGER,
                container_id TEXT,
                name TEXT,
                status TEXT,
                uptime TEXT,
                cpu_load TEXT,
                mem_load TEXT,
                created TEXT,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            )"""
        )
        await db.execute(
            """CREATE TABLE IF NOT EXISTS ignored_containers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )"""
        )
        await db.commit()

async def get_ignored_containers(db):
    async with db.execute("SELECT name FROM ignored_containers") as cursor:
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def get_server_info(server):
    def ssh_exec(ssh_client, command):
        stdin, stdout, stderr = ssh_client.exec_command(command)
        return stdout.read().decode().strip(), stderr.read().decode().strip()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        port = server.get("port", 22)
        logging.debug(f"Connecting to {server['ip']}:{port} with username {server['username']}")
        await asyncio.to_thread(ssh.connect, server["ip"], port=port, username=server["username"], password=server["password"])

        commands = {
            "cpu": "top -bn1 | grep 'Cpu(s)'",
            "mem": "free -m | grep 'Mem:'",
            "disk": "df -h / | tail -n1",
            "uptime": "uptime -p",
            "containers": "docker ps -a --format '{{.ID}}|{{.Names}}|{{.State}}|{{.CreatedAt}}|{{.Status}}'"
        }
        
        results = {}
        for key, cmd in commands.items():
            output, error = await asyncio.to_thread(ssh_exec, ssh, cmd)
            logging.debug(f"Command '{cmd}' output: {output}")
            if error:
                logging.error(f"Error executing {cmd}: {error}")
                return f"Error executing {cmd}: {error}"
            results[key] = output

        cpu = results["cpu"].split()[1]
        mem = results["mem"].split()
        mem_usage = f"{mem[2]}/{mem[1]} MB"
        disk = results["disk"].split()[2:4]
        uptime_raw = results["uptime"]
        # Скорочуємо час роботи
        uptime_parts = uptime_raw.replace("up ", "").split(", ")
        uptime = ""
        for part in uptime_parts:
            if "week" in part:
                weeks = part.split()[0]
                uptime += f"{weeks} тиж{'нів' if int(weeks) > 1 else 'ень'}, "
            elif "hour" in part:
                hours = part.split()[0]
                uptime += f"{hours} год"
            elif "minute" in part:
                minutes = part.split()[0]
                uptime += f"{minutes} хв"
        uptime = uptime.strip(", ")

        containers_raw = results["containers"].splitlines()
        logging.debug(f"Raw containers data: {containers_raw}")
        
        async with aiosqlite.connect("servers.db") as db:
            ignored_containers = await get_ignored_containers(db)
            logging.debug(f"Ignored containers: {ignored_containers}")
        
        containers = []
        for container in containers_raw:
            if not container:
                continue
            try:
                c_id, c_name, c_state, c_created, c_status = container.split("|", 4)
                if c_name in ignored_containers:
                    logging.debug(f"Skipping ignored container: {c_name}")
                    continue

                stats_output, stats_error = await asyncio.to_thread(ssh_exec, ssh, f"docker stats --no-stream {c_id}")
                if stats_error:
                    logging.error(f"Stats error for {c_id}: {stats_error}")
                    stats_cpu, stats_mem = "N/A", "N/A"
                else:
                    stats = stats_output.splitlines()[1].split()
                    stats_cpu, stats_mem = stats[2], stats[6]

                containers.append({
                    "name": c_name,
                    "status": c_state,
                    "cpu_load": stats_cpu,
                    "mem_load": stats_mem,
                    "created": c_created,
                    "uptime": c_status
                })
                logging.debug(f"Added container: {c_name}")
            except ValueError as e:
                logging.error(f"Failed to parse container data: {container}, error: {e}")
                continue
        
        logging.debug(f"Processed containers: {containers}")
        return {
            "cpu": cpu,
            "mem": mem_usage,
            "disk": f"{disk[0]}/{disk[1]}",
            "uptime": uptime,
            "containers": containers
        }
    except Exception as e:
        logging.error(f"General error in get_server_info: {str(e)}")
        return f"Error: {str(e)}"
    finally:
        ssh.close()