import aiosqlite
import paramiko
import logging
import asyncio

async def init_db():
    async with aiosqlite.connect("servers.db") as db:  # Змінено шлях на корінь проекту
        await db.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                port INTEGER,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                name TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ignored_containers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)
        await db.commit()

async def get_server_info(server):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        await asyncio.to_thread(ssh.connect, server["ip"], port=server.get("port", 22), 
                                username=server["username"], password=server["password"])
        stdin, stdout, stderr = await asyncio.to_thread(ssh.exec_command, 
            "uptime -p && free -m | grep Mem: && df -h / | tail -n 1 && docker ps -a --format '{{.Names}} {{.Status}} {{.CreatedAt}} {{.ID}}'")
        
        uptime = stdout.readline().strip().replace("up ", "")
        mem = stdout.readline().strip().split()
        disk = stdout.readline().strip().split()
        containers_raw = stdout.read().decode().strip().splitlines()
        
        mem_total = int(mem[1])
        mem_used = int(mem[2])
        disk_used = disk[2]
        disk_total = disk[1]
        
        containers = []
        async with aiosqlite.connect("servers.db") as db:  # Змінено шлях на корінь проекту
            async with db.execute("SELECT name FROM ignored_containers") as cursor:
                ignored = {row[0] for row in await cursor.fetchall()}
        
        for line in containers_raw:
            parts = line.split()
            name = parts[0]
            if name in ignored:
                continue
            status = " ".join(parts[1:parts.index("2025") if "2025" in parts else len(parts)])
            created_at = " ".join(parts[parts.index("2025") if "2025" in parts else -2:-1])
            stdin, stdout, stderr = await asyncio.to_thread(ssh.exec_command, 
                f"docker inspect {name} | jq -r '.[0].State.Status' && docker stats --no-stream {name} --format '{{.CPUPerc}} {{.MemPerc}}'")
            state = stdout.readline().strip()
            stats = stdout.readline().strip().split()
            cpu_load = stats[0] if stats else "0.00%"
            mem_load = stats[1] if len(stats) > 1 else "0.00%"
            
            containers.append({
                "name": name,
                "status": state,
                "cpu_load": cpu_load,
                "mem_load": mem_load,
                "created": created_at,
                "uptime": status if "Up" in status else "Down"
            })
        
        return {
            "cpu": cpu_load,  # Останній контейнер, можна змінити логіку
            "mem": f"{mem_used}/{mem_total} MB",
            "disk": f"{disk_used}/{disk_total}",
            "uptime": uptime,
            "containers": containers
        }
    except Exception as e:
        logging.error(f"Error connecting to {server['ip']}: {str(e)}")
        return f"Помилка підключення: {str(e)}"
    finally:
        ssh.close()

if __name__ == "__main__":
    asyncio.run(init_db())