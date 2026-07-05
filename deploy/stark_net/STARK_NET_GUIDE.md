# STARK-NET Setup Guide

## What This Is
Your own private encrypted network. All your devices communicate through
your server via WireGuard. No third party sits in the middle.

This requires a server you control with root access (e.g. an Oracle Cloud
free-tier instance, a home server, a VPS) — it does **not** work on Render,
which doesn't expose raw networking access to the container.

## IP Assignments
```
10.13.37.1  — JARVIS SERVER (hub)
10.13.37.2  — MacBook
10.13.37.3  — iPhone
10.13.37.4  — iPad
10.13.37.5  — Ray-Bans (via iPhone)
10.13.37.10 — FRIDAY
```

## Setup on the server
```bash
sudo bash deploy/stark_net/setup.sh
export SERVER_IP=<your server's public IP>
sudo -E bash deploy/stark_net/add_device.sh macbook
```

## Setup on iPhone / iPad
1. Install WireGuard from the App Store (free).
2. Scan the QR code printed by `add_device.sh`, or import the generated
   `<device>_stark_net.conf` file.
3. Enable the tunnel.

## Setup on Mac
1. Install WireGuard from the App Store.
2. Import `macbook_stark_net.conf`.
3. Connect.

## After setup
All devices can reach each other directly through the encrypted tunnel.
Reach JARVIS at `http://10.13.37.1:8000` from any connected device — that
address isn't reachable from outside the tunnel.
