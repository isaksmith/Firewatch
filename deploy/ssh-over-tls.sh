#!/bin/bash
# Lightsail launch script for networks that block SSH by protocol: stunnel takes TLS on port 443 and hands it to sshd,
# so SSH looks like any HTTPS connection. Caddy then serves the API on FW_HTTPS_PORT (8443) instead.
# Client side, in ~/.ssh/config:
#   Host <server ip>
#     ProxyCommand openssl s_client -quiet -connect %h:443 -servername firewatch-ssh 2>/dev/null
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -q && apt-get install -yq stunnel4
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj /CN=firewatch-ssh \
  -keyout /etc/stunnel/ssh.pem -out /etc/stunnel/ssh.pem
chmod 600 /etc/stunnel/ssh.pem
cat > /etc/stunnel/ssh.conf <<'EOF'
foreground = yes
[ssh]
accept = 443
connect = 127.0.0.1:22
cert = /etc/stunnel/ssh.pem
EOF
cat > /etc/systemd/system/ssh-over-tls.service <<'EOF'
[Unit]
Description=SSH over TLS on port 443
After=network-online.target
[Service]
ExecStart=/usr/bin/stunnel4 /etc/stunnel/ssh.conf
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now ssh-over-tls
