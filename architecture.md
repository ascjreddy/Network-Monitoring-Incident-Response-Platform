# System Architecture

## Overview

The platform has four main components: telemetry collection → storage → correlation → visualization.

There is no separate normalization layer. Parsing happens inside the collector on receipt, and deduplication happens inside the correlation engine before writing to the database.

---

## Component breakdown

### 1. Telemetry collection

Two separate collectors run in parallel:

**Syslog collector (`syslog_collector.py`) — runs on GNS3 VM**

- Listens on UDP port 514
- Receives syslog messages from all 12 network devices
- On receipt, parses the syslog priority byte to extract severity: `severity = priority % 8`, mapped to emergency / alert / critical / error / warning / notice / informational / debug
- Maps source IP to device name using a hardcoded `DEVICE_MAP` dict
- Timestamps are NOT taken from the device — PostgreSQL stamps each row with `NOW()` at insert time, which is the arrival time at the collector
- Writes structured fields (device_ip, device_name, severity, message, raw_message) to `syslog_events` in PostgreSQL on the Windows host

**SNMP poller (`snmp_poller2.py`) — runs on GNS3 VM**

- Polls 5 monitored devices every 30 seconds
- Uses `snmpget` via subprocess — not PySNMP (switched due to PySNMP 7.x removing the `hlapi` API)
- Polls only `sysDescr` OID (`1.3.6.1.2.1.1.1.0`) as a reachability check — no interface stats, no CPU, no errors
- Records status as `up` or `unreachable`
- Writes to `snmp_metrics` in PostgreSQL on the Windows host

---

### 2. Correlation engine

**`incident_engine.py` — runs on Windows**

Reads the last 10 minutes of events from PostgreSQL every 30 seconds and applies pattern matching rules.

**Deduplication happens here in two places:**
- `deduplicate()` removes duplicate incident types within a single engine run (same type + same device = one incident)
- `save_incident()` checks the database before inserting — if an open unresolved incident of the same type on the same device already exists within the last 10 minutes, it skips the insert

The topology is modeled as a plain Python dict in the engine:

```python
TOPOLOGY = {
    "Core-SW-01":  {"upstream": "Edge-RTR-01",  "downstream": ["Dist-HQ"]},
    "Core-SW-02":  {"upstream": "Edge-RTR-01",  "downstream": ["Dist-Branch"]},
    "Dist-HQ":     {"upstream": "Core-SW-01",   "downstream": ["Acc-SW1", "Acc-SW2"]},
    "Dist-Branch": {"upstream": "Core-SW-02",   "downstream": ["Acc-SW3"]},
    ...
}
```

Correlation rules:

| Rule | Logic |
|------|-------|
| Interface down | Syslog contains `LINEPROTO-5-UPDOWN` and `down` |
| OSPF neighbor lost | Syslog contains `OSPF`, `ADJCHG`, and `DOWN` |
| Device unreachable | SNMP poller records `if_status = unreachable` for 90+ seconds |
| Link flapping | 5+ `LINEPROTO` or `LINK-3-UPDOWN` events from same device in 10 minutes |

**Root cause identification:** the engine finds the earliest matching event and walks downstream using the topology dict to identify affected devices. The first event with no upstream cause in the chain is the root cause. Everything below it is a symptom.

**Resolution detection:** runs in the same loop. Marks incidents resolved when:
- Interface comes back up (`LINEPROTO-5-UPDOWN` + `up`)
- OSPF adjacency restores (`OSPF` + `ADJCHG` + `FULL`)
- Device starts responding to SNMP again

---

### 3. Database schema

Three tables in PostgreSQL:

```sql
syslog_events (
  id          SERIAL PRIMARY KEY,
  timestamp   TIMESTAMPTZ DEFAULT NOW(),
  device_ip   VARCHAR,
  device_name VARCHAR,
  severity    VARCHAR,
  facility    VARCHAR,
  message     TEXT,
  raw_message TEXT
)

snmp_metrics (
  id             SERIAL PRIMARY KEY,
  timestamp      TIMESTAMPTZ DEFAULT NOW(),
  device_ip      VARCHAR,
  device_name    VARCHAR,
  interface_name VARCHAR,
  if_status      VARCHAR    -- 'up' or 'unreachable'
)

incidents (
  id                 SERIAL PRIMARY KEY,
  detected_at        TIMESTAMPTZ DEFAULT NOW(),
  root_cause_device  VARCHAR,
  root_cause_event   TEXT,
  affected_devices   TEXT,
  incident_type      VARCHAR,
  timeline           TEXT,
  remediation        TEXT,
  resolved           BOOLEAN DEFAULT FALSE,
  resolved_at        TIMESTAMPTZ
)
```

---

### 4. Grafana dashboards

Six panels on a single dashboard, auto-refreshing every 30 seconds:

- **Live incident status** — active incident count, events in last 5 min, total incidents, avg MTTD in seconds, SNMP unreachable devices, total syslog events
- **Device health heatmap** — per-device status from `snmp_metrics`, last seen timestamp
- **Syslog events by device** — donut chart showing event distribution across devices
- **Incidents by type** — donut chart of incident type breakdown
- **Event timeline** — syslog events over time per device (line chart)
- **Incident log** — table showing every incident: detected_at, type, root cause, affected devices, description, resolved_at
- **Live syslog stream** — raw table of recent syslog events with severity color coding
- **SNMP polling history** — reachable device count over time

Data source: PostgreSQL direct connection.

---

## Data flow

```
Cisco IOU devices (12x in GNS3)
        |                  |
   syslog UDP 514      snmpget subprocess
        |                  |
syslog_collector.py   snmp_poller2.py
  (GNS3 VM)             (GNS3 VM)
        |                  |
        +--------+---------+
                 |
           PostgreSQL
         (Windows host)
                 |
        incident_engine.py
          (Windows host)
                 |
         +-------+-------+
         |               |
      Grafana        printed incident
    dashboard           reports
  (localhost:3000)   (terminal output)
```

---

## Design decisions

**Why rule-based correlation instead of ML?**
Network protocol failures are deterministic — interface down always causes OSPF neighbor loss on adjacent devices. Rules are transparent, debuggable, and don't need training data. ML would be harder to explain and wouldn't add anything here.

**Why a Python dict for topology instead of NetworkX?**
The topology is small and static (12 devices). A plain dict with upstream/downstream keys is enough to trace cascades without adding a graph library dependency. If this scaled to hundreds of devices, a proper graph structure would make sense.

**Why PostgreSQL instead of a time-series DB like InfluxDB?**
At this scale (12 devices, 30s poll interval) PostgreSQL with `TIMESTAMPTZ` columns handles the load fine. Standard SQL joins make cross-device correlation queries straightforward. A production deployment at thousands of devices would warrant TimescaleDB or InfluxDB.

**Why snmpget subprocess instead of PySNMP?**
PySNMP 7.x removed the `hlapi` API that the original poller was written against. Rather than rewrite for the new API, switching to subprocess calls against the system `snmpget` binary was simpler and more reliable for this use case.
