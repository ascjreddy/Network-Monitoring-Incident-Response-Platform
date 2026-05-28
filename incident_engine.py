import time
import psycopg2
from datetime import datetime, timedelta

DB_CONFIG = {
    "host": "localhost",
    "database": "network_incidents",
    "user": "postgres",
    "password": "postgres",
    "port": 5432
}

# Topology: which devices depend on which
TOPOLOGY = {
    "Core-SW-01":  {"upstream": "Edge-RTR-01",  "downstream": ["Dist-HQ"]},
    "Core-SW-02":  {"upstream": "Edge-RTR-01",  "downstream": ["Dist-Branch"]},
    "Dist-HQ":     {"upstream": "Core-SW-01",   "downstream": ["Acc-SW1", "Acc-SW2"]},
    "Dist-Branch": {"upstream": "Core-SW-02",   "downstream": ["Acc-SW3"]},
    "Acc-SW1":     {"upstream": "Dist-HQ",      "downstream": ["IT-PC1", "IT-PC2"]},
    "Acc-SW2":     {"upstream": "Dist-HQ",      "downstream": ["ENG-PC1", "ENG-PC2"]},
    "Acc-SW3":     {"upstream": "Dist-Branch",  "downstream": ["SALES-PC1", "SALES-PC2"]},
}

REMEDIATION = {
    "interface_down": "Check physical cable and interface configuration. Run: show interface {interface}",
    "ospf_neighbor_lost": "Verify OSPF config on both sides. Run: show ip ospf neighbor. Check interface status.",
    "device_unreachable": "Check device power and management connectivity. Try pinging from upstream device.",
    "link_flapping": "Interface is unstable. Check cable quality and duplex settings. Consider: shutdown/no shutdown.",
    "ospf_flap": "OSPF adjacency is flapping. Check hello/dead timers and MTU mismatch.",
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def get_recent_events(seconds=60):
    conn = get_conn()
    cur  = conn.cursor()
    since = datetime.now() - timedelta(seconds=seconds)
    cur.execute("""
        SELECT timestamp, device_name, severity, message
        FROM syslog_events
        WHERE timestamp > %s
        ORDER BY timestamp ASC
    """, (since,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_unreachable_devices():
    conn = get_conn()
    cur  = conn.cursor()
    since = datetime.now() - timedelta(seconds=90)
    cur.execute("""
        SELECT DISTINCT device_name
        FROM snmp_metrics
        WHERE timestamp > %s AND if_status = 'unreachable'
    """, (since,))
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows

def detect_incidents(events, unreachable):
    incidents = []

    # Pattern 1: Interface down
    for ts, device, sev, msg in events:
        if "LINEPROTO-5-UPDOWN" in msg and "down" in msg.lower():
            iface = "unknown"
            parts = msg.split("Interface ")
            if len(parts) > 1:
                iface = parts[1].split(",")[0]

            affected = get_downstream(device)
            incidents.append({
                "type": "interface_down",
                "root_cause_device": device,
                "root_cause_event": f"Interface {iface} went down at {ts}",
                "affected_devices": ", ".join(affected),
                "timeline": build_timeline(events, device, ts),
                "remediation": REMEDIATION["interface_down"].format(interface=iface)
            })

    # Pattern 2: OSPF neighbor lost
    for ts, device, sev, msg in events:
        if "OSPF" in msg and ("down" in msg.lower() or "ADJCHG" in msg):
            if "FULL" not in msg:
                affected = get_downstream(device)
                incidents.append({
                    "type": "ospf_neighbor_lost",
                    "root_cause_device": device,
                    "root_cause_event": f"OSPF adjacency lost at {ts}: {msg[:100]}",
                    "affected_devices": ", ".join(affected),
                    "timeline": build_timeline(events, device, ts),
                    "remediation": REMEDIATION["ospf_neighbor_lost"]
                })

    # Pattern 3: Device unreachable
    for device in unreachable:
        affected = get_downstream(device)
        incidents.append({
            "type": "device_unreachable",
            "root_cause_device": device,
            "root_cause_event": f"Device {device} not responding to SNMP at {datetime.now()}",
            "affected_devices": ", ".join(affected),
            "timeline": f"{datetime.now()} - {device} unreachable via SNMP",
            "remediation": REMEDIATION["device_unreachable"]
        })

    # Pattern 4: Link flapping (5+ interface events in 10 min)
    flap_counts = {}
    for ts, device, sev, msg in events:
        if "LINEPROTO-5-UPDOWN" in msg or "LINK-3-UPDOWN" in msg:
            key = device
            flap_counts[key] = flap_counts.get(key, 0) + 1

    for device, count in flap_counts.items():
        if count >= 5:
            incidents.append({
                "type": "link_flapping",
                "root_cause_device": device,
                "root_cause_event": f"Interface flapped {count} times in last 10 minutes",
                "affected_devices": ", ".join(get_downstream(device)),
                "timeline": build_timeline(events, device, datetime.now()),
                "remediation": REMEDIATION["link_flapping"]
            })

    return deduplicate(incidents)

def get_downstream(device):
    affected = []
    if device in TOPOLOGY:
        for d in TOPOLOGY[device].get("downstream", []):
            affected.append(d)
            affected.extend(get_downstream(d))
    return affected

def build_timeline(events, device, start_ts):
    lines = []
    for ts, dev, sev, msg in events:
        if abs((ts - start_ts).total_seconds()) < 120:
            lines.append(f"{ts} | {dev} | {msg[:80]}")
    return "\n".join(lines[:10])

def deduplicate(incidents):
    seen = set()
    unique = []
    for inc in incidents:
        key = (inc["type"], inc["root_cause_device"])
        if key not in seen:
            seen.add(key)
            unique.append(inc)
    return unique

def save_incident(inc):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        # Check if same incident already open in last 5 minutes
        cur.execute("""
            SELECT id FROM incidents
            WHERE root_cause_device = %s
            AND incident_type = %s
            AND detected_at > NOW() - INTERVAL '5 minutes'
            AND resolved = FALSE
        """, (inc["root_cause_device"], inc["type"]))
        if cur.fetchone():
            cur.close()
            conn.close()
            return

        cur.execute("""
            INSERT INTO incidents
            (root_cause_device, root_cause_event, affected_devices,
             incident_type, timeline, remediation)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            inc["root_cause_device"],
            inc["root_cause_event"],
            inc["affected_devices"],
            inc["type"],
            inc["timeline"],
            inc["remediation"]
        ))
        conn.commit()
        cur.close()
        conn.close()
        print_incident_report(inc)
    except Exception as e:
        print(f"DB error saving incident: {e}")

def print_incident_report(inc):
    print("\n" + "="*60)
    print(f"  INCIDENT DETECTED — {datetime.now()}")
    print("="*60)
    print(f"  Type:        {inc['type'].upper()}")
    print(f"  Root Cause:  {inc['root_cause_device']}")
    print(f"  Event:       {inc['root_cause_event']}")
    print(f"  Affected:    {inc['affected_devices']}")
    print(f"  Remediation: {inc['remediation']}")
    print("-"*60)
    print("  Timeline:")
    for line in inc["timeline"].split("\n")[:5]:
        print(f"    {line}")
    print("="*60 + "\n")

def run_engine():
    print(f"[{datetime.now()}] Correlation engine started — checking every 30s")
    while True:
        try:
            events      = get_recent_events(seconds=600)
            unreachable = get_unreachable_devices()
            incidents   = detect_incidents(events, unreachable)

            if incidents:
                for inc in incidents:
                    save_incident(inc)
            else:
                print(f"[{datetime.now()}] No incidents detected")

        except Exception as e:
            print(f"Engine error: {e}")

        time.sleep(30)

if __name__ == "__main__":
    run_engine()
