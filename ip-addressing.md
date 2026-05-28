# IP Addressing Scheme

## Summary

| Subnet | Purpose | VLAN |
|--------|---------|------|
| 10.10.10.0/24 | Employee hosts | VLAN 10 |
| 10.10.20.0/24 | Guest hosts | VLAN 20 |
| 10.10.30.0/24 | DMZ servers | VLAN 30 |
| 10.10.99.0/24 | Management | VLAN 99 |
| 10.100.252.0/30 | Core-Dist link 1 | point-to-point |
| 10.100.253.0/30 | Core-Dist link 2 | point-to-point |
| 10.100.254.0/30 | Edge-Core uplink | point-to-point |
| 192.168.1.0/30 | ISP-facing (Edge-Router-01) | WAN |
| 192.168.2.0/30 | ISP-facing (Edge-Router-02) | WAN |

---

## Device management IPs (VLAN 99)

| Device | Hostname | Mgmt IP |
|--------|----------|---------|
| Edge Router 1 | Edge-RTR-01 | 10.10.99.1 |
| Edge Router 2 | Edge-RTR-02 | 10.10.99.2 |
| Firewall 1 | FW-01 | 10.10.99.3 |
| Firewall 2 | FW-02 | 10.10.99.4 |
| Core Switch 1 | Core-SW-01 | 10.10.99.5 |
| Core Switch 2 | Core-SW-02 | 10.10.99.6 |
| Distribution Switch 1 | Dist-SW-01 | 10.10.99.7 |
| Distribution Switch 2 | Dist-SW-02 | 10.10.99.8 |
| Access Switch 1 | Access-SW-01 | 10.10.99.9 |
| Access Switch 2 | Access-SW-02 | 10.10.99.10 |
| Access Switch 3 | Access-SW-03 | 10.10.99.11 |
| Access Switch 4 | Access-SW-04 | 10.10.99.12 |

---

## OSPF configuration

- All routers/L3 switches run OSPF Area 0
- Router IDs assigned as loopback addresses (10.0.0.X/32)
- Hello interval: 10s, Dead interval: 40s
- Authentication: MD5 on all adjacencies

## HSRP (Core layer)

| VIP | Active | Standby |
|-----|--------|---------|
| 10.10.10.1 | Core-SW-01 | Core-SW-02 |
| 10.10.20.1 | Core-SW-01 | Core-SW-02 |
| 10.10.30.1 | Core-SW-02 | Core-SW-01 |

## BGP

- Edge-RTR-01 and Edge-RTR-02 peer with simulated upstream ISP
- AS number: 65001 (internal), 65000 (simulated ISP)
- VRRP on WAN-facing interfaces for redundancy
