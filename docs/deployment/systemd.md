# Systemd ile Dağıtım

Linux sistemlerde Elyan'ı systemd servisi olarak çalıştırın.

## Otomatik Kurulum

```bash
# Elyan CLI ile kur
elyan service install
```

Bu komut systemd unit dosyasını oluşturur ve servisi etkinleştirir.

## Manuel Kurulum

### 1. Sistem Kullanıcısı

```bash
sudo useradd -r -s /bin/false -d /opt/elyan elyan
sudo mkdir -p /opt/elyan
sudo chown elyan:elyan /opt/elyan
```

### 2. Elyan'ı Yükle

```bash
git clone https://github.com/your-org/elyan.git /opt/elyan/app
cd /opt/elyan/app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Yapılandırma

```bash
sudo mkdir -p /etc/elyan
sudo cp config/config.example.json5 /etc/elyan/config.json5
sudo nano /etc/elyan/config.json5  # API anahtarlarını girin
sudo chown elyan:elyan /etc/elyan/config.json5
sudo chmod 600 /etc/elyan/config.json5
```

### 4. Systemd Unit Dosyası

`/etc/systemd/system/elyan.service`:

```ini
[Unit]
Description=Elyan AI Operator Gateway
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=elyan
Group=elyan
WorkingDirectory=/opt/elyan/app
Environment="PYTHONPATH=/opt/elyan/app"
Environment="ELYAN_CONFIG=/etc/elyan/config.json5"
ExecStart=/opt/elyan/app/.venv/bin/python main.py --cli
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=elyan

# Güvenlik sınırları
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/elyan /tmp

[Install]
WantedBy=multi-user.target
```

### 5. Servisi Etkinleştir

```bash
sudo systemctl daemon-reload
sudo systemctl enable elyan
sudo systemctl start elyan
```

## Servis Yönetimi

```bash
# Durum
sudo systemctl status elyan

# Başlat / Durdur / Yeniden başlat
sudo systemctl start elyan
sudo systemctl stop elyan
sudo systemctl restart elyan

# Günlükler
sudo journalctl -u elyan -f          # Canlı
sudo journalctl -u elyan -n 100      # Son 100 satır
sudo journalctl -u elyan --since "1 hour ago"
```

## Güncelleme

```bash
cd /opt/elyan/app
sudo -u elyan git pull
sudo -u elyan .venv/bin/pip install -r requirements.txt
sudo systemctl restart elyan
```

## Otomatik Başlatma Doğrulama

```bash
sudo reboot
# Yeniden başlangıçtan sonra:
sudo systemctl status elyan
```

## Sorun Giderme

```bash
# Son hataları görüntüle
sudo journalctl -u elyan -p err -n 50

# Bağımlılık eksik mi?
sudo -u elyan /opt/elyan/app/.venv/bin/python -c "import elyan; print('OK')"
```
