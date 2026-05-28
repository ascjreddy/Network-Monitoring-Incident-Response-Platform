# System Architecture

## Overview

The platform has five main components that work together in a pipeline: telemetry collection → normalization → correlation → storage → visualization.

---

## Component breakdown

### 1. Telemetry collection

Two separate collectors run in parallel:

**Syslog collector** (`syslog_collector.py`)
- Listens on UDP port 514
- Receives events from all 12 network devices
- Parses raw syslog messages into structured fields (timestamp, hostname, severity, message)
- Writes to the `raw_events` table in PostgreSQL

**SNMP poller** (`snmp_poller.py`)
- Polls all devices every 30 seconds using PySNMP
- Collects: interface status, interface errors, CPU utilization, memory usage
- OIDs targeted: ifOperStatus, ifInErrors, ifOutErrors, sysDescr, hrProcessorLoad
- Writes to the `device_metrics` table

---

### 2. Event normalization

Before events hit the correlation engine, they get cleaned up:

- **Timestamp normalization** — all device timestamps converted to UTC epoch. Handles devices in different time zones and minor clock skew (±5 seconds tolerance built in).
- **Deduplication** — identical events within a 10-second window from the same device get collapsed to one. This typically reduces event volume by ~40% during flapping scenarios.
- **Severity classification** — events tagged as critical / warning / informational based on syslog facility + severity codes.

---

### 3. Correlation engine

The core of the system. Uses two inputs:

1. **The event stream** from PostgreSQL
2. **The topology graph** — a NetworkX directed graph built from the known network topology (which devices are OSPF neighbors, which are connected by which interfaces)

**Correlation rules** (see `correlation-rules.md` for full list):

| Rule | Logic |
|------|-------|
| Temporal | Event B on Device B occurred within 30 seconds of Event A on Device A |
| Topology | Device A and Device B are direct OSPF neighbors in the graph |
| Protocol causality | Interface down always precedes OSPF neighbor loss |
| Threshold | 5+ identical events in 10 minutes = instability flag |

**Root cause identification:**
The engine walks the event chain backward in time. The earliest event that has no preceding cause in the graph is designated the root cause. Everything that followed is labeled a downstream symptom.

---

### 4. Database schema

Three main tables:

```sql
raw_events (
  id SERIAL PRIMARY KEY,
  received_at TIMESTAMPTZ,
  device_hostname VARCHAR,
  severity INTEGER,
  message TEXT,
  parsed_event_type VARCHAR
)

device_metrics (
  id SERIAL PRIMARY KEY,
  polled_at TIMESTAMPTZ,
  device_hostname VARCHAR,
  interface_name VARCHAR,
  oper_status INTEGER,
  in_errors BIGINT,
  out_errors BIGINT,
  cpu_pct FLOAT
)

incidents (
  id SERIAL PRIMARY KEY,
  detected_at TIMESTAMPTZ,
  root_cause_device VARCHAR,
  root_cause_event TEXT,
  affected_devices TEXT[],
  cascade_json JSONB,
  report_text TEXT,
  mttd_seconds INTEGER
)
```

---

### 5. Grafana dashboards

Four panels:

1. **Device health heatmap** — 12-device grid, color-coded green/yellow/red
2. **Active incidents timeline** — scrolling feed of detected incidents with root cause highlighted
3. **MTTD tracker** — running average mean time to detection per incident type
4. **Interface metrics** — per-interface utilization, error rates, and status over time

Data source: PostgreSQL direct connection

---

## Data flow diagram

```
[Arista vEOS / pfSense devices]
         |               |
    syslog UDP 514    SNMP v2c
         |               |
    syslog_collector  snmp_poller
         |               |
         +-------+-------+
                 |
           normalization
                 |
            PostgreSQL
                 |
         correlation engine
          (+ NetworkX graph)
                 |
         +-------+-------+
         |               |
    Grafana          incident
   dashboards          reports
```

---

## Design decisions

**Why rule-based correlation instead of ML?**
The failure patterns in network protocols are deterministic — interface down always causes OSPF neighbor loss if they're adjacent. Rules are transparent, debuggable, and don't need training data. ML would be overkill here and harder to explain.

**Why PostgreSQL instead of a time-series DB like InfluxDB?**
PostgreSQL with timestamptz columns is sufficient for this scale (12 devices, 30s poll interval). It also makes the correlation queries simpler — standard SQL joins work well for correlating events across devices. A real production deployment at thousands of devices would warrant InfluxDB or TimescaleDB.

**Why NetworkX for topology modeling?**
NetworkX makes it easy to represent the network as a directed graph and run shortest-path queries to check if two devices are adjacent. The topology graph gets loaded at startup from a JSON config file and can be updated without restarting the engine.
