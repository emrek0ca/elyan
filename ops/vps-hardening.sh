#!/bin/bash
set -euo pipefail
umask 077

DEPLOY_ROOT="${ELYAN_DEPLOY_ROOT:-/srv/elyan}"
ENV_FILE="${ELYAN_ENV_FILE:-${DEPLOY_ROOT}/.env}"
SERVICE_NAME="${ELYAN_SERVICE_NAME:-elyan}"
POSTGRES_CLUSTER="${ELYAN_POSTGRES_CLUSTER:-16/main}"
POSTGRES_HBA_FILE="${ELYAN_POSTGRES_HBA_FILE:-/etc/postgresql/16/main/pg_hba.conf}"
BACKUP_ROOT="${ELYAN_SECURITY_BACKUP_ROOT:-/root}"
ROTATE_LOCAL_SECRETS="${ELYAN_ROTATE_LOCAL_SECRETS:-1}"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="${BACKUP_ROOT}/elyan-security-backup-${timestamp}"

backup_file() {
    local source_path="$1"
    if [ -e "$source_path" ]; then
        cp -a "$source_path" "${backup_dir}/$(echo "$source_path" | sed 's#/#_#g')"
    fi
}

require_file() {
    local file_path="$1"
    if [ ! -f "$file_path" ]; then
        echo "Missing required file: $file_path" >&2
        exit 1
    fi
}

require_file "$ENV_FILE"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"

backup_file "$ENV_FILE"
backup_file "$POSTGRES_HBA_FILE"
backup_file "/etc/postgresql/16/main/postgresql.conf"
backup_file "/etc/ssh/sshd_config"
backup_file "/etc/systemd/system/${SERVICE_NAME}.service"

if [ "$ROTATE_LOCAL_SECRETS" = "1" ]; then
    python3 - "$ENV_FILE" <<'PY'
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

env_path = Path(sys.argv[1])
lines = env_path.read_text().splitlines()
values = {}
for line in lines:
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        values[key] = value

database_url = values.get("DATABASE_URL")
if not database_url:
    raise SystemExit("DATABASE_URL is missing")

parsed = urlparse(database_url)
if parsed.username != "elyan":
    raise SystemExit("DATABASE_URL user is not elyan; refusing automatic DB password rotation")

new_db_password = secrets.token_urlsafe(36)
new_nextauth_secret = secrets.token_urlsafe(48)
netloc = f"{parsed.username}:{quote(new_db_password)}@{parsed.hostname}"
if parsed.port:
    netloc = f"{netloc}:{parsed.port}"
next_database_url = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))

next_lines = []
seen_nextauth = False
for line in lines:
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, _ = line.split("=", 1)
        if key == "DATABASE_URL":
            next_lines.append(f"DATABASE_URL={next_database_url}")
            continue
        if key == "NEXTAUTH_SECRET":
            next_lines.append(f"NEXTAUTH_SECRET={new_nextauth_secret}")
            seen_nextauth = True
            continue
    next_lines.append(line)

if not seen_nextauth:
    next_lines.append(f"NEXTAUTH_SECRET={new_nextauth_secret}")

env_path.write_text("\n".join(next_lines) + "\n")
Path("/root/.elyan-new-db-password").write_text(new_db_password + "\n")
PY

    chmod 600 "$ENV_FILE" /root/.elyan-new-db-password
    chown elyan:elyan "$ENV_FILE"

    db_password="$(cat /root/.elyan-new-db-password)"
    escaped_password="${db_password//\'/\'\'}"
    sudo -u postgres psql -v ON_ERROR_STOP=1 >/dev/null <<SQL
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
ALTER ROLE elyan WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '${escaped_password}';
SQL
    rm -f /root/.elyan-new-db-password
fi

python3 - "$POSTGRES_HBA_FILE" <<'PY'
import sys
from pathlib import Path

hba = Path(sys.argv[1])
replacements = {
    "local   all             all                                     trust": "local   all             all                                     peer",
    "host    all             all             127.0.0.1/32            trust": "host    all             all             127.0.0.1/32            scram-sha-256",
    "host    all             all             ::1/128                 trust": "host    all             all             ::1/128                 scram-sha-256",
    "host    replication     all             127.0.0.1/32            trust": "host    replication     all             127.0.0.1/32            scram-sha-256",
    "host    replication     all             ::1/128                 md5": "host    replication     all             ::1/128                 scram-sha-256",
}
lines = hba.read_text().splitlines()
next_lines = [replacements.get(line.strip(), line) for line in lines]
hba.write_text("\n".join(next_lines) + "\n")
PY

sudo -u postgres psql -Atqc "select pg_reload_conf();" >/dev/null
systemctl restart "postgresql@${POSTGRES_CLUSTER//\//-}" 2>/dev/null || systemctl restart postgresql

install -d -m 755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-elyan-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 3
X11Forwarding no
AllowTcpForwarding no
EOF
sshd -t
systemctl reload ssh

if command -v fail2ban-server >/dev/null 2>&1; then
    install -d -m 755 /etc/fail2ban/jail.d
    cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = %(sshd_log)s
maxretry = 4
findtime = 10m
bantime = 1h
EOF
    systemctl enable --now fail2ban >/dev/null || true
    systemctl restart fail2ban || true
fi

ufw --force delete allow 3010/tcp >/dev/null 2>&1 || true
ufw --force delete allow 3010 >/dev/null 2>&1 || true
ufw limit OpenSSH >/dev/null 2>&1 || true

default_if="$(ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')"
if [ -n "$default_if" ] && command -v iptables >/dev/null 2>&1; then
    cat > /usr/local/sbin/elyan-docker-db-firewall.sh <<'EOF'
#!/bin/bash
set -euo pipefail
DEFAULT_IF="${1:-$(ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')}"
iptables -N DOCKER-USER 2>/dev/null || true
iptables -C DOCKER-USER -i "$DEFAULT_IF" -p tcp --dport 5432 -j DROP 2>/dev/null || iptables -I DOCKER-USER 1 -i "$DEFAULT_IF" -p tcp --dport 5432 -j DROP
if command -v ip6tables >/dev/null 2>&1; then
    ip6tables -N DOCKER-USER 2>/dev/null || true
    ip6tables -C DOCKER-USER -i "$DEFAULT_IF" -p tcp --dport 5432 -j DROP 2>/dev/null || ip6tables -I DOCKER-USER 1 -i "$DEFAULT_IF" -p tcp --dport 5432 -j DROP
fi
EOF
    chmod 700 /usr/local/sbin/elyan-docker-db-firewall.sh
    /usr/local/sbin/elyan-docker-db-firewall.sh "$default_if"
    cat > /etc/systemd/system/elyan-docker-db-firewall.service <<EOF
[Unit]
Description=Block public Docker PostgreSQL exposure
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/elyan-docker-db-firewall.sh ${default_if}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now elyan-docker-db-firewall >/dev/null || true
fi

chmod 750 "$DEPLOY_ROOT" "${DEPLOY_ROOT}/storage" "${DEPLOY_ROOT}/releases" 2>/dev/null || true
chmod 600 "$ENV_FILE"
chown elyan:elyan "$ENV_FILE" 2>/dev/null || true
chown -R elyan:elyan "${DEPLOY_ROOT}/storage" 2>/dev/null || true

install -d -m 755 "/etc/systemd/system/${SERVICE_NAME}.service.d"
cat > "/etc/systemd/system/${SERVICE_NAME}.service.d/10-security.conf" <<EOF
[Service]
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=${DEPLOY_ROOT}
RestrictSUIDSGID=true
LockPersonality=true
EOF
systemctl daemon-reload

sudo -u elyan bash -c "set -a; . '$ENV_FILE'; set +a; psql \"\$DATABASE_URL\" -Atqc 'select 1'" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 3
systemctl is-active --quiet "$SERVICE_NAME"
curl -fsS "http://127.0.0.1:${PORT:-3010}/api/healthz" >/dev/null

echo "Elyan VPS hardening completed. Backup: ${backup_dir}"
