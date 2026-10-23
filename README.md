# Homecam

Multi-camera RTSP wall for your home network. Add cameras in the browser, reorder them, and scroll through single, quad, or nine-up grid pages. Streams are converted for the browser by [go2rtc](https://github.com/AlexxIT/go2rtc) inside Docker.

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS, or Linux)
- IP cameras or NVRs that expose **RTSP** or **RTSP over TLS** (`rtsp://` / `rtsps://`)

## Quick start

From this directory:

```bash
docker compose up --build -d
```

Homecam defaults to host port **8081** so it does not fight with other dev tools that use **8080**. Copy or edit `.env` to change it:

```bash
cp .env.example .env   # optional; repo includes .env with 8081 for local use
docker compose up --build -d
```

One-off port override:

```bash
HOMECAM_PORT=8888 docker compose up --build -d
```

Open the UI on the host machine:

- http://localhost:8081 (or your `HOMECAM_PORT`)

If you see another app’s UI, you are on the wrong port—check Docker Desktop for the **homecam-app** container’s published port. Homecam responses include the header `X-Homecam: 1` (visible in browser devtools → Network).

Other computers on the same LAN (not `localhost`, not a `172.x` WSL address):

- http://`<your-pc-lan-ip>`:`<HOMECAM_PORT>` (example: `http://10.0.0.2:8081`)

### Other devices cannot open the page

1. **Port** — Homecam defaults to **8081**, not 8080. In Docker Desktop, **homecam-app** should show `8081:8080`.
2. **IP** — Use the PC’s address on your home network (Windows: `ipconfig`, look at Ethernet/Wi‑Fi). Phones/laptops must be on the same LAN (not guest Wi‑Fi with client isolation).
3. **Windows Firewall** — Ethernet/Wi‑Fi is often **Private**. Docker Desktop’s built-in allow rules may only apply to the **Public** profile, so inbound TCP on your port can still be blocked. Run **PowerShell as Administrator**:

```powershell
New-NetFirewallRule -DisplayName "Homecam TCP 8081" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8081 -Profile Private
```

Change `8081` if you use another `HOMECAM_PORT`. Then retry from another device: `http://<lan-ip>:8081` (you should see the Homecam title; responses include header `X-Homecam: 1`).

## Usage

1. Enter a **name** and **RTSP URL** (include credentials in the URL if required).
2. Drag cameras in the list to change order (shared for all viewers).
3. Choose **Single**, **Quad**, or **Nine** grid layout (saved per browser).
4. Scroll vertically to move between pages when you have more cameras than fit on one screen.

Video tiles only connect when they are visible on screen, to limit load.

## How it works

- Only **HOMECAM_PORT** (default **8081**) is published to the network; go2rtc stays internal.
- The `app` container stores camera metadata in a Docker volume and registers each stream with `go2rtc` over the internal network.
- The browser plays video via **MSE** through a same-origin `/rtc/` proxy (no WebRTC UDP setup on the host).

The `go2rtc` container must be able to reach your camera IPs on the LAN. If a feed fails, check that the RTSP URL works from the Docker host (e.g. with VLC) and that the camera allows connections from the Docker network.

## Data

Camera list: Docker volume `homecam-data` at `/data/cameras.json` inside the `app` container.

To reset cameras:

```bash
docker compose down
docker volume rm homecam_homecam-data
docker compose up -d
```

(Volume name may be prefixed with your project folder name; run `docker volume ls` to confirm.)

## Stop

```bash
docker compose down
```
