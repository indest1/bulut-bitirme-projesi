from flask import Flask, render_template, request, redirect, url_for, session, Response
import sqlite3
import socket
import time
import threading
import requests
from urllib.parse import urlparse
from datetime import datetime

app = Flask(__name__)
app.secret_key = "bulut-operasyon-yonetim-anahtari"
DB_NAME = "envanter.db"

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

    # 1. Aşama: DNS Çözümleme Kontrolü
    # Var olmayan bir adresi doğrudan eler
    try:
        ip = socket.gethostbyname(hedef)
    except socket.gaierror:
        return "Erişilemiyor (DNS Hatası)", 0

    # 2. Aşama: Web Siteleri (Port 80 ve 443) İçin HTTP Doğrulaması
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
            
            # Sadece 2xx ve 3xx başarılı sayılır, 4xx/5xx erişilemez
            if resp.status_code < 400:
                return "Çalışıyor", gecikme
            else:
                return f"Hata ({resp.status_code})", gecikme
        except requests.RequestException:
            return "Erişilemiyor", 0

    # 3. Aşama: Özel Servisler (Minecraft 25565, SSH 22, Veritabanı 3306 vb.)
    # Doğrudan hedeflenen IP ve Port'a TCP el sıkışması yapar
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
            c.execute("SELECT id, ip_adresi, port, sunucu_adi FROM sunucular")
            sunucular = c.fetchall()

            simdi = datetime.now().strftime("%H:%M:%S")
            for s_id, hedef, port, ad in sunucular:
                durum, gecikme = ping_server(hedef, port)
                c.execute("UPDATE sunucular SET durum = ?, gecikme = ?, son_kontrol = ? WHERE id = ?", (durum, gecikme, simdi, s_id))

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Otomatik tarama hatası: {e}")

        time.sleep(15)

@app.route('/login', methods=['GET', 'POST'])
def login():
    hata = None
    if request.method == 'POST':
        if request.form['kullanici'] == ADMIN_USER and request.form['sifre'] == ADMIN_PASS:
            session['giris'] = True
            log_ekle("Yönetici sisteme giriş yaptı.")
            return redirect(url_for('index'))
        else:
            hata = "Hatalı kullanıcı adı veya şifre!"
    return render_template('login.html', hata=hata)

@app.route('/logout')
def logout():
    session.pop('giris', None)
    log_ekle("Yönetici çıkış yaptı.")
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM sunucular")
    sunucular = c.fetchall()

    c.execute("SELECT * FROM loglar ORDER BY id DESC LIMIT 5")
    son_loglar = c.fetchall()

    toplam = len(sunucular)
    aktif = sum(1 for s in sunucular if s[4] == 'Çalışıyor')
    kapali = sum(1 for s in sunucular if s[4] != 'Çalışıyor' and s[4] != 'Bilinmiyor')

    conn.close()
    return render_template('index.html', sunucular=sunucular, toplam=toplam, aktif=aktif, kapali=kapali, loglar=son_loglar)

@app.route('/ekle', methods=['POST'])
def ekle():
    if not session.get('giris'):
        return redirect(url_for('login'))

    ad = request.form['sunucu_adi']
    ip = hedefi_temizle(request.form['ip_adresi'])
    port = int(request.form.get('port', 80))

    if ad and ip:
        durum, gecikme = ping_server(ip, port)
        simdi = datetime.now().strftime("%H:%M:%S")
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO sunucular (sunucu_adi, ip_adresi, port, durum, gecikme, son_kontrol) VALUES (?, ?, ?, ?, ?, ?)", (ad, ip, port, durum, gecikme, simdi))
        conn.commit()
        conn.close()
        log_ekle(f"Yeni altyapı eklendi: {ad} ({ip}:{port}) - Durum: {durum}")
    return redirect(url_for('index'))

@app.route('/duzenle/<int:id>', methods=['POST'])
def duzenle(id):
    if not session.get('giris'):
        return redirect(url_for('login'))

    yeni_ad = request.form['sunucu_adi']
    yeni_ip = hedefi_temizle(request.form['ip_adresi'])
    yeni_port = int(request.form.get('port', 80))

    durum, gecikme = ping_server(yeni_ip, yeni_port)
    simdi = datetime.now().strftime("%H:%M:%S")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE sunucular SET sunucu_adi = ?, ip_adresi = ?, port = ?, durum = ?, gecikme = ?, son_kontrol = ? WHERE id = ?", (yeni_ad, yeni_ip, yeni_port, durum, gecikme, simdi, id))
    conn.commit()
    conn.close()
    log_ekle(f"Sunucu güncellendi (ID: {id}): {yeni_ad}")
    return redirect(url_for('index'))

@app.route('/ping/<int:id>')
def ping(id):
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT ip_adresi, port, sunucu_adi FROM sunucular WHERE id = ?", (id,))
    row = c.fetchone()

    if row:
        ip, port, ad = row
        durum, gecikme = ping_server(ip, port)
        simdi = datetime.now().strftime("%H:%M:%S")
        c.execute("UPDATE sunucular SET durum = ?, gecikme = ?, son_kontrol = ? WHERE id = ?", (durum, gecikme, simdi, id))
        conn.commit()
        log_ekle(f"Manuel test: {ad} -> {durum} ({gecikme}ms)")

    conn.close()
    return redirect(url_for('index'))

@app.route('/tara-hepsi')
def tara_hepsi():
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, ip_adresi, port, sunucu_adi FROM sunucular")
    liste = c.fetchall()

    simdi = datetime.now().strftime("%H:%M:%S")
    for item in liste:
        s_id, ip, port, ad = item
        durum, gecikme = ping_server(ip, port)
        c.execute("UPDATE sunucular SET durum = ?, gecikme = ?, son_kontrol = ? WHERE id = ?", (durum, gecikme, simdi, s_id))

    conn.commit()
    conn.close()
    log_ekle("Tüm altyapı manuel toplu olarak tarandı.")
    return redirect(url_for('index'))

@app.route('/sil/<int:id>')
def sil(id):
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM sunucular WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    log_ekle(f"Sunucu silindi (ID: {id})")
    return redirect(url_for('index'))

@app.route('/export')
def export():
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT sunucu_adi, ip_adresi, port, durum, gecikme, son_kontrol FROM sunucular")
    veriler = c.fetchall()
    conn.close()

    cikti = "Sunucu Adi,IP Adresi,Port,Durum,Gecikme (ms),Son Kontrol\n"
    for v in veriler:
        cikti += f"{v[0]},{v[1]},{v[2]},{v[3]},{v[4]}ms,{v[5]}\n"

    return Response(
        cikti,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=envanter_raporu.csv"}
    )

init_db()
bg_thread = threading.Thread(target=otomatik_kontrol_dongusu, daemon=True)
bg_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
