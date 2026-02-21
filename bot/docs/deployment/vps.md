# VPS (DigitalOcean) Dağıtımı

DigitalOcean Droplet üzerinde Elyan kurulum rehberi. Diğer VPS sağlayıcılarında (Hetzner, Linode, Vultr) benzer adımlar geçerlidir.

## Gereksinimler

- Ubuntu 22.04 LTS Droplet (minimum: 1 vCPU, 1 GB RAM)
- Alan adı (isteğe bağlı, HTTPS için)
- SSH erişimi

## 1. Sunucu Hazırlama

```bash
# Sunucuya bağlan
ssh root@YOUR_SERVER_IP

# Güncellemeleri yükle
apt update && apt upgrade -y

# Gerekli paketler
apt install -y python3.12 python3.12-venv git nginx certbot python3-certbot-nginx ufw

# Güvenlik duvarı
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

## 2. Elyan Kurulumu

```bash
# Uygulama kullanıcısı oluştur
adduser --disabled-password --gecos "" elyan

# Kodu indir
git clone https://github.com/your-org/elyan.git /home/elyan/app
chown -R elyan:elyan /home/elyan/app

# Python ortamı
sudo -u elyan bash -c "
cd /home/elyan/app
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
"
```

## 3. Yapılandırma

```bash
# Yapılandırma dosyasını oluştur
sudo -u elyan mkdir -p /home/elyan/.elyan
sudo -u elyan nano /home/elyan/.elyan/config.json5
```

Minimum yapılandırma:

```json5
{
  "gateway": {
    "host": "127.0.0.1",
    "port": 8765
  },
  "models": {
    "default": "groq",
    "groq_api_key": "gsk_xxx"
  },
  "channels": [
    {
      "type": "telegram",
      "token": "YOUR_BOT_TOKEN",
      "enabled": true
    }
  ]
}
```

## 4. Systemd Servisi

```bash
cat > /etc/systemd/system/elyan.service << 'EOF'
[Unit]
Description=Elyan AI Gateway
After=network-online.target

[Service]
Type=simple
User=elyan
WorkingDirectory=/home/elyan/app
ExecStart=/home/elyan/app/.venv/bin/python main.py --cli
Restart=always
RestartSec=5
Environment="ELYAN_ENV=production"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable elyan
systemctl start elyan
```

## 5. nginx Ters Proxy

```bash
cat > /etc/nginx/sites-available/elyan << 'EOF'
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -s /etc/nginx/sites-available/elyan /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## 6. SSL (HTTPS)

```bash
certbot --nginx -d yourdomain.com
# Yönlendirme: Yes seçin
```

## 7. Telegram Webhook

HTTPS hazır olduğunda polling yerine webhook kullanabilirsiniz:

```bash
# Webhook kur
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourdomain.com/telegram/webhook"
```

## Doğrulama

```bash
# Servis çalışıyor mu?
systemctl status elyan

# API yanıt veriyor mu?
curl https://yourdomain.com/api/health

# Günlükler
journalctl -u elyan -f
```

## Güncelleme Scripti

```bash
cat > /usr/local/bin/elyan-update << 'EOF'
#!/bin/bash
cd /home/elyan/app
sudo -u elyan git pull
sudo -u elyan .venv/bin/pip install -r requirements.txt
systemctl restart elyan
echo "Elyan güncellendi ve yeniden başlatıldı"
EOF
chmod +x /usr/local/bin/elyan-update
```

## Maliyetler

| Droplet | vCPU | RAM | Fiyat | Kapasite |
|---------|------|-----|-------|----------|
| Basic | 1 | 1 GB | ~$6/ay | Küçük kullanım |
| Basic | 1 | 2 GB | ~$12/ay | Orta kullanım |
| General | 2 | 4 GB | ~$24/ay | Yüksek kullanım |
