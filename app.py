from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify
import sqlite3
import socket
import ssl
import time
import threading
import requests
import os
import psutil
from urllib.parse import urlparse
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bulut-operasyon-yonetim-anahtari"

# Kalici veri tabani yolu (Volume)
DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "envanter.db")

ADMIN_USER = "admin"
ADMIN_PASS = "bulut123"

# TELEGRAM BILDIRIM AYARLARI
TELEGRAM_BOT_TOKEN = "BURAYA_BOT_TOKENINI_YAPISTIR"
TELEGRAM_CHAT_ID = "BURAYA_CHAT_ID_YAPISTIR"

def telegram_bildir(mesaj):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=5.0)
    except Exception as e:
        print(f"Telegram gonderim hatasi: {e}")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sunucular (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sunucu_adi TEXT NOT NULL,
            ip_adresi TEXT NOT NULL,
            port INTEGER DEFAULT 80,
            durum TEXT DEFAULT 'Bilinmiyor',
            gecikme INTEGER DEFAULT 0,
            son_kontrol TEXT,
            toplam_kontrol INTEGER DEFAULT 0,
            basarili_kontrol INTEGER DEFAULT 0,
            ssl_gun INTEGER DEFAULT -1
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS loglar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            islem TEXT NOT NULL,
            tarih TEXT NOT NULL
        )
    ''')
    
    try:
        c.execute("ALTER TABLE sunucular ADD COLUMN toplam_kontrol INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE sunucular ADD COLUMN basarili_kontrol INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE sunucular ADD COLUMN ssl_gun INTEGER DEFAULT -1")
    except Exception:
        pass

    conn.commit()
    conn.close()

def log_ekle(mesaj):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    simdi = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO loglar (islem, tarih) VALUES (?, ?)", (mesaj, simdi))
    conn.commit()
    conn.close()

def hedefi_temizle(hedef):
    hedef = hedef.strip()
    if hedef.startswith("http://") or hedef.startswith("https://"):
        parsed = urlparse(hedef)
        return parsed.netloc.split(':')[0]
    return hedef.split('/')[0]

def ssl_kalan_gun_hesapla(hedef, port=443):
    if port != 443:
        return -1
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hedef, port), timeout=3.0) as sock:
            with context.wrap_socket(sock, server_hostname=hedef) as ssock:
                cert = ssock.getpeercert()
                bitis_str = cert['notAfter']
                bitis_tarihi = datetime.strptime(bitis_str, '%b %d %H:%M:%S %Y %Z')
                kalan_gun = (bitis_tarihi - datetime.utcnow()).days
                return max(0, kalan_gun)
    except Exception:
        return -1

def ping_server(hedef, port):
    hedef = hedefi_temizle(hedef)
    port = int(port)
    basla = time.time()

    try:
        ip = socket.gethostbyname(hedef)
    except socket.gaierror:
        return "Erisilemiyor (DNS Hatasi)", 0, -1

    ssl_
