# IP Addressing

Device IPs as configured in the GNS3 topology.

## Monitored devices

| Device | Role | IP |
|---|---|---|
| ISP-RTR-A | ISP router | 203.0.113.1 |
| Edge-RTR-01 | Edge router | 10.0.0.1 |
| Core-SW-01 | Core switch | 10.0.0.2 |
| Core-SW-02 | Core switch | 10.0.0.6 |
| Dist-HQ | Distribution (HQ) | 10.0.0.10 |
| Dist-Branch | Distribution (Branch) | 10.0.0.14 |
| Acc-SW1 | Access switch | 10.99.0.31 |
| Acc-SW2 | Access switch | 10.99.0.32 |
| Acc-SW3 | Access switch | 10.99.0.33 |

## Routing protocol

OSPF runs across all routers and L3 switches. All devices are in Area 0.

## Syslog and SNMP

All devices send syslog to the GNS3 VM on UDP 514. SNMP community string is `public`. The SNMP poller reaches devices via the GNS3 internal network (`192.168.42.x`).
