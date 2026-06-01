import subprocess
import psycopg2
import time
from datetime import datetime

# Database connection — points to Windows PostgreSQL host
DB_CONFIG = {
    "host": "192.168.56.1",
    "database": "network_incidents",
    "user": "postgres",
    "password": "postgres",
    "port": 5432
}

# All monitored devices with their GNS3 VM-reachable IPs
DEVICES = [
    {"ip": "192.168.42.253", "name": "Edge-RTR-01"},
    {"ip": "192.168.42.2",   "name": "Core-SW-01"},
    {"ip": "192.168.42.3",   "name": "Core-SW-02"},
    {"ip": "192.168.42.4",   "name": "Dist-HQ"},
    {"ip": "192.168.42.5",   "name": "Dist-Branch"},
]

POLL_INTERVAL = 30  # seconds

def snmp_get(ip, oid):
    """Use CLI snmpget to poll a device OID. Returns raw output or None."""
    try:
        result = subprocess.run(
            ["snmpget", "-v2c", "-c", "public", "-t", "3", "-r", "1", ip, oid],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None

def poll_device(device):
    """Poll a single device via SNMP and write result to PostgreSQL."""
    ip   = device["ip"]
    name = device["name"]

    # Use sysDescr OID as a reachability check
    response = snmp_get(ip, "1.3.6.1.2.1.1.1.0")
    status = "up" if response else "unreachable"

    ts = datetime.now()
    print(f"[{ts}] {name:15} status={status}")

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO snmp_metrics
                (device_ip, device_name, interface_name, if_status)
            VALUES (%s, %s, %s, %s)
        """, (ip, name, "main", status))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  DB error: {e}")

def run_poller():
    print(f"[{datetime.now()}] SNMP poller started — polling every {POLL_INTERVAL}s")
    while True:
        for device in DEVICES:
            poll_device(device)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    run_poller()