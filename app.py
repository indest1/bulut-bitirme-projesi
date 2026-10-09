from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify
import sqlite3
import socket
import time
import threading
import requests
import os
from urllib.parse import urlparse
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bulut-operasyon-yonetim-anahtari"

# Veritabanı için kalıcı disk dizini
DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "envanter.db")

ADMIN_USER = "admin"
ADMIN_PASS = "bulut123"

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
            son_kontrol TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS loglar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            islem TEXT NOT NULL,
            tarih TEXT NOT NULL
        )
    ''')
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

def ping_server(hedef, port):
    hedef = hedefi_temizle(hedef)
    port = int(port)
    basla = time.time()

    # DNS Çözümleme Kontrolü
    try:
        ip = socket.gethostbyname(hedef)
    except socket.gaierror:
        return "Erişilemiyor (DNS Hatası)", 0

    # Web Siteleri (Port 80 ve 443)
    if port in [80, 443]:
        sema = "https" if port == 443 else "http"
        url = f"{sema}://{hedef}"
        try:
            resp = requests.get(
                url, 
                timeout=2.0, 
                allow_redirects=True, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            gecikme = int((time.time() - basla) * 1000)
            if resp.status_code < 400:
                return "Çalışıyor", gecikme
            else:
                return f"Hata ({resp.status_code})", gecikme
        except requests.RequestException:
            return "Erişilemiyor", 0

    # Özel Servisler (Minecraft, SSH, DNS, SQL vb.)
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        try:
            s.connect((ip, port))
            gecikme = int((time.time() - basla) * 1000)
            s.close()
            return "Çalışıyor", gecikme
        except (socket.timeout, ConnectionRefusedError, OSError):
            return "Erişilemiyor", 0

def otomatik_kontrol_dongusu():
    while True:
        try:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT id, ip_adresi, port, sunucu_adi, durum FROM sunucular")
            sunucular = c.fetchall()

            simdi = datetime.now().strftime("%H:%M:%S")
            for s_id, hedef, port, ad, eski_durum in sunucular:
                yeni_durum, gecikme = ping_server(hedef, port)
                c.execute("UPDATE sunucular SET durum = ?, gecikme = ?, son_kontrol = ? WHERE id = ?", (yeni_durum, gecikme, simdi, s_id))

                # Arka Plan Olay Günlüğü (Incident Detection)
                if eski_durum != 'Bilinmiyor' and eski_durum != yeni_durum:
                    tam_tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if yeni_durum.startswith("Erişilemiyor") or "Hata" in yeni_durum:
                        c.execute("INSERT INTO loglar (islem, tarih) VALUES (?, ?)", 
                                  (f"🚨 KESİNTİ: '{ad}' servisine erişim koptu! ({yeni_durum})", tam_tarih))
                    elif yeni_durum == "Çalışıyor":
                        c.execute("INSERT INTO loglar (islem, tarih) VALUES (?, ?)", 
                                  (f"✅ KURTAR
