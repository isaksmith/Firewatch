# Hosting

Vercel serves the pages from its CDN and asks for the console login. One small always-on server runs the FastAPI
backend, which holds the scorer and the other models in memory. Vercel forwards `/api` and `/lite` to it.

| Path | What | Served by | Login |
|---|---|---|---|
| `/`, `/alerts/:id`, `/alerts/:id/3d`, `/planner` | Console (React build) | Vercel | Yes |
| `/board` | Community board | Vercel | No |
| `/nodes/` | FireNode Explorer (sensor viewer) | Vercel | No |
| `/api/*`, `/lite` | Backend | Server, through Vercel | Yes, except the public board routes, `/api/m/*` (mobile app) and `/api/sms/inbound` (Twilio) |

`frontend/middleware.ts` checks the login, then forwards to the server with three headers no browser ever sees:
the backend's `API_TOKEN` (only after the login passes), the visitor's IP, and a proxy secret. Caddy on the server
refuses anything without the secret, which is why the backend can trust the IP header.

The backend runs as one process: its feed pollers, replay clock and sensor simulator live inside it, so a second
worker would run them twice. SQLite and the tile cache stay on the server's disk between deploys.

Vercel's free plan includes 1 million middleware runs a month. An open console makes about 2,000 to 4,500 API
calls an hour, so that is a few hundred hours of an open console a month. Past the limit Vercel pauses the site
until the month resets; it does not bill.

## First time

The server is an AWS Lightsail `micro_3_0`: $7 a month for 2 vCPUs and 1 GB, plus the 2 GB of swap `setup.sh`
adds. The backend uses about 450 MB, and some of it sits in swap; `FW_BUNDLE=small_3_0` ($12, 2 GB) gives headroom.

```bash
deploy/vercel-deploy.sh                                   # creates the Vercel project; note the address it prints
aws login
FW_SITE=https://<the vercel address> deploy/provision.sh  # server, static IP, firewall, then setup.sh
export FW_SSH_KEY=~/.ssh/firewatch_lightsail
deploy/deploy.sh ubuntu@<ip>
FW_PASSWORD='choose-one' deploy/vercel-env.sh ubuntu@<ip>
deploy/vercel-deploy.sh                                   # again, so the site picks up the settings
```

Some networks (campus ones, for example) drop SSH to anywhere but GitHub. The sign is that `ssh` connects and then
fails with "Connection timed out during banner exchange". Add `FW_SSH_OVER_TLS=1` to `provision.sh`. The server
then answers SSH inside TLS on port 443, which looks like any HTTPS connection, and serves the API on port 8443,
which only Vercel needs to reach. `provision.sh` adds the matching `~/.ssh/config` entry, so `ssh`, `rsync` and
every script here work unchanged. Caddy's first certificate attempt over port 443 then fails and it falls back to
port 80, which is expected.

Any other Ubuntu 24.04 server works too: `FW_SITE=... deploy/setup.sh ubuntu@<ip>` does the same setup, and
`setup.sh`, `deploy.sh` and `vercel-env.sh` don't care where the server runs. `oracle.sh` tries Oracle Cloud's
free Arm machines, which were out of capacity every time we tried.

The login user is `firewatch` unless `FW_USER` was set.
The server's backend settings are in `/srv/firewatch/.env` (sample mode, simulated sensors, no radio).

## Every deploy

```bash
deploy/vercel-deploy.sh                                             # pages
FW_SSH_KEY=~/.ssh/firewatch_lightsail deploy/deploy.sh ubuntu@<ip>  # backend
```

`deploy.sh` copies the backend and the tile cache, installs Python packages and restarts the backend and Caddy.
The first copy of the tile cache is about 700 MB; later deploys send only what changed.

## Looking around on the server

```bash
ssh -i ~/.ssh/firewatch_lightsail ubuntu@<ip>
sudo journalctl -u firewatch -f      # backend log
sudo journalctl -u caddy -f          # web server log
```
