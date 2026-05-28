import time
import socket
import psycopg2
from datetime import datetime
 
DB_CONFIG = {
    "host": "localhost",
    "database": "network_incidents",
    "user": "postgres",
    "password": "postgres",
    "port": 5432
}
 
DEVICES = [
    {"ip": "10.0.0.1",    "name": "Edge-RTR-01"},
    {"ip": "10.0.0.2",    "name": "Core-SW-01"},
    {"ip": "10.0.0.6",    "name": "Core-SW-02"},
    {"ip": "10.0.0.10",   "name": "Dist-HQ"},
    {"ip": "10.0.0.14",   "name": "Dist-Branch"},
    {"ip": "203.0.113.1", "name": "ISP-RTR-A"},
]
 
COMMUNITY     = "public"
POLL_INTERVAL = 30
 
IF_STATUS_MAP = {"1": "up", "2": "down", "3": "testing",
                 "4": "unknown", "5": "dormant"}
 
OID_IF_STATUS = "1.3.6.1.2.1.2.2.1.8.1"
OID_CPU       = "1.3.6.1.4.1.9.2.1.58.0"
OID_IF_IN     = "1.3.6.1.2.1.2.2.1.10.1"
OID_IF_OUT    = "1.3.6.1.2.1.2.2.1.16.1"
 
def snmp_get(host, community, oid_str):
    try:
        from pysnmp.proto import api
        from pyasn1.codec.ber import encoder, decoder
 
        pMod = api.PROTOCOL_MODULES[api.protoVersion2c]
        reqPDU = pMod.GetRequestPDU()
        pMod.apiPDU.setDefaults(reqPDU)
        pMod.apiPDU.setVarBinds(reqPDU, [(oid_str, pMod.Null(''))])
 
        reqMsg = pMod.Message()
        pMod.apiMessage.setDefaults(reqMsg)
        pMod.apiMessage.setCommunity(reqMsg, community)
        pMod.apiMessage.setPDU(reqMsg, reqPDU)
 
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        try:
            sock.sendto(encoder.encode(reqMsg), (host, 161))
            data, _ = sock.recvfrom(65535)
            rspMsg, _ = decoder.decode(data, asn1Spec=pMod.Message())
            rspPDU = pMod.apiMessage.getPDU(rspMsg)
            for oid, val in pMod.apiPDU.getVarBinds(rspPDU):
                return str(val)
        finally:
            sock.close()
    except Exception:
        return None
 
def poll_device(device):
    ip   = device["ip"]
    name = device["name"]
 
    if_status = snmp_get(ip, COMMUNITY, OID_IF_STATUS)
    cpu_raw   = snmp_get(ip, COMMUNITY, OID_CPU)
    bytes_in  = snmp_get(ip, COMMUNITY, OID_IF_IN)
    bytes_out = snmp_get(ip, COMMUNITY, OID_IF_OUT)
 
    status  = IF_STATUS_MAP.get(if_status, "unreachable") if if_status else "unreachable"
    cpu_val = float(cpu_raw) if cpu_raw and cpu_raw.replace('.','').isdigit() else None
    b_in    = int(bytes_in)  if bytes_in  and bytes_in.isdigit()  else None
    b_out   = int(bytes_out) if bytes_out and bytes_out.isdigit() else None
 
    return {
        "device_ip":      ip,
        "device_name":    name,
        "interface_name": "primary",
        "if_status":      status,
        "cpu_percent":    cpu_val,
        "bytes_in":       b_in,
        "bytes_out":      b_out
    }
 
def save_metric(metric):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO snmp_metrics
            (device_ip, device_name, interface_name, if_status,
             cpu_percent, bytes_in, bytes_out)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            metric["device_ip"], metric["device_name"],
            metric["interface_name"], metric["if_status"],
            metric["cpu_percent"], metric["bytes_in"], metric["bytes_out"]
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")
 
def run_poller():
    print(f"[{datetime.now()}] SNMP poller started — polling every {POLL_INTERVAL}s")
    while True:
        for device in DEVICES:
            try:
                metric = poll_device(device)
                save_metric(metric)
                print(f"[{datetime.now()}] {metric['device_name']:15} "
                      f"status={metric['if_status']:12} "
                      f"cpu={metric['cpu_percent']}% "
                      f"in={metric['bytes_in']} out={metric['bytes_out']}")
            except Exception as e:
                print(f"Error polling {device['name']}: {e}")
        time.sleep(POLL_INTERVAL)
 
if __name__ == "__main__":
    run_poller()
