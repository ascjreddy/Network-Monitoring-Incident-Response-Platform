import socket
import re
import psycopg2
from datetime import datetime

# Database connection — points to Windows PostgreSQL, not localhost
DB_CONFIG = {
    "host": "192.168.56.1",
    "database": "network_incidents",
    "user": "postgres",
    "password": "postgres",
    "port": 5432
}

# Device IP to name mapping — all 9 devices included
DEVICE_MAP = {
    "10.0.0.1": "Edge-RTR-01",
    "10.0.0.2": "Core-SW-01",
    "10.0.0.6": "Core-SW-02",
    "10.0.0.10": "Dist-HQ",
    "10.0.0.14": "Dist-Branch",
    "203.0.113.1": "ISP-RTR-A",
    "10.99.0.31": "Acc-SW1",
    "10.99.0.32": "Acc-SW2",
    "10.99.0.33": "Acc-SW3",
}

SEVERITY_MAP = {
    "0": "emergency",
    "1": "alert",
    "2": "critical",
    "3": "error",
    "4": "warning",
    "5": "notice",
    "6": "informational",
    "7": "debug"
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def parse_syslog(data, addr):
    raw = data.decode("utf-8", errors="replace").strip()
    device_ip = addr[0]
    device_name = DEVICE_MAP.get(device_ip, device_ip)

    # Parse severity from syslog priority
    severity = "informational"
    facility = "local"
    message = raw

    pri_match = re.match(r"<(\d+)>(.*)", raw)
    if pri_match:
        pri = int(pri_match.group(1))
        severity_code = str(pri % 8)
        severity = SEVERITY_MAP.get(severity_code, "informational")
        message = pri_match.group(2).strip()

    return {
        "device_ip": device_ip,
        "device_name": device_name,
        "severity": severity,
        "facility": facility,
        "message": message,
        "raw_message": raw
    }

def save_event(event):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO syslog_events 
            (device_ip, device_name, severity, facility, message, raw_message)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            event["device_ip"],
            event["device_name"],
            event["severity"],
            event["facility"],
            event["message"],
            event["raw_message"]
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")

def start_collector():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 514))
    print(f"[{datetime.now()}] Syslog collector listening on UDP 514...")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            event = parse_syslog(data, addr)
            save_event(event)
            print(f"[{datetime.now()}] {event['device_name']} ({event['device_ip']}) "
                  f"[{event['severity'].upper()}] {event['message'][:100]}")
        except KeyboardInterrupt:
            print("\nCollector stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    start_collector()