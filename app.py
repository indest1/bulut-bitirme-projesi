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

    ssl_gun = ssl_kalan_gun_hesapla(hedef, port)

    if port in [80, 443]:
        sema = "https" if port == 443 else "http"
        url = f"{sema}://{hedef}"
        try:
            # Gerçek Masaüstü Chrome gibi davranarak bot engellerini aşar
            tarayici_basligi = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            resp = requests.get(
                url, 
                timeout=4.0, 
                allow_redirects=True, 
                stream=True,  # Sayfa icerigini indirmeden sadece baglanti durumunu alir
                headers=tarayici_basligi
            )
            gecikme = int((time.time() - basla) * 1000)
            if resp.status_code < 400:
                return "Calisiyor", gecikme, ssl_gun
            else:
                return f"Hata ({resp.status_code})", gecikme, ssl_gun
        except requests.RequestException:
            return "Erisilemiyor", 0, ssl_gun
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        try:
            s.connect((ip, port))
            gecikme = int((time.time() - basla) * 1000)
            s.close()
            return "Calisiyor", gecikme, -1
        except (socket.timeout, ConnectionRefusedError, OSError):
            return "Erisilemiyor", 0, -1

def otomatik_kontrol_dongusu():
    while True:
        try:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT id, ip_adresi, port, sunucu_adi, durum, toplam_kontrol, basarili_kontrol FROM sunucular")
            sunucular = c.fetchall()

            simdi = datetime.now().strftime("%H:%M:%S")
            for s_id, hedef, port, ad, eski_durum, t_sayi, b_sayi in sunucular:
                yeni_durum, gecikme, ssl_gun = ping_server(hedef, port)
                
                t_sayi = (t_sayi or 0) + 1
                if yeni_durum == "Calisiyor":
                    b_sayi = (b_sayi or 0) + 1

                c.execute("""
                    UPDATE sunucular 
                    SET durum = ?, gecikme = ?, son_kontrol = ?, toplam_kontrol = ?, basarili_kontrol = ?, ssl_gun = ?
                    WHERE id = ?
                """, (yeni_durum, gecikme, simdi, t_sayi, b_sayi, ssl_gun, s_id))

                # Durum Değişikliği Tespiti & Anlık Telegram Bildirimi
                if eski_durum != 'Bilinmiyor' and eski_durum != yeni_durum:
                    tam_tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if yeni_durum.startswith("Erisilemiyor") or "Hata" in yeni_durum:
                        mesaj = f"🚨 KESINTI: '{ad}' servisine erisim koptu! ({yeni_durum})"
                        c.execute("INSERT INTO loglar (islem, tarih) VALUES (?, ?)", (mesaj, tam_tarih))
                        telegram_bildir(f"🚨 <b>CLOUDOPS ALARM: KESİNTİ!</b>\n\n<b>Sunucu:</b> {ad}\n<b>Adres:</b> {hedef}:{port}\n<b>Durum:</b> {yeni_durum}\n<b>Zaman:</b> {tam_tarih}")
                    elif yeni_durum == "Calisiyor":
                        mesaj = f"✅ KURTARILDI: '{ad}' servisi tekrar erisilebilir duruma geldi ({gecikme}ms)."
                        c.execute("INSERT INTO loglar (islem, tarih) VALUES (?, ?)", (mesaj, tam_tarih))
                        telegram_bildir(f"✅ <b>CLOUDOPS: SERVİS KURTARILDI</b>\n\n<b>Sunucu:</b> {ad}\n<b>Adres:</b> {hedef}:{port}\n<b>Gecikme:</b> {gecikme} ms\n<b>Zaman:</b> {tam_tarih}")

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Otomatik tarama hatasi: {e}")

        time.sleep(15)

def saatlik_rapor_dongusu():
    time.sleep(10)
    while True:
        try:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT sunucu_adi, durum, gecikme, port, ip_adresi FROM sunucular")
            sunucular = c.fetchall()
            conn.close()

            toplam = len(sunucular)
            aktif = sum(1 for s in sunucular if s[1] == 'Calisiyor')
            kapali = toplam - aktif

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")

            mesaj = f"📊 <b>CLOUDOPS SAATLİK ALTYAPI RAPORU</b>\n"
            mesaj += f"🕒 <i>Tarih: {zaman}</i>\n\n"
            mesaj += f"🖥 <b>Host Kaynakları:</b> CPU: %{cpu} | RAM: %{ram} | Disk: %{disk}\n"
            mesaj += f"📈 <b>Varlık Özeti:</b> Toplam: {toplam} | Aktif: {aktif} | Kapalı: {kapali}\n\n"
            mesaj += "📋 <b>Servis Durumları:</b>\n"

            if not sunucular:
                mesaj += "<i>Kayıtlı sunucu bulunmuyor.</i>"
            else:
                for s in sunucular:
                    simge = "🟢" if s[1] == "Calisiyor" else "🔴"
                    mesaj += f"{simge} <b>{s[0]}</b> ({s[4]}:{s[3]}): {s[1]} ({s[2]}ms)\n"

            telegram_bildir(mesaj)
        except Exception as e:
            print(f"Saatlik rapor hatasi: {e}")

        time.sleep(3600)

@app.route('/login', methods=['GET', 'POST'])
def login():
    hata = None
    if request.method == 'POST':
        if request.form['kullanici'] == ADMIN_USER and request.form['sifre'] == ADMIN_PASS:
            session['giris'] = True
            log_ekle("Yonetici sisteme giris yapti.")
            return redirect(url_for('index'))
        else:
            hata = "Hatali kullanici adi veya sifre!"
    return render_template('login.html', hata=hata)

@app.route('/logout')
def logout():
    session.pop('giris', None)
    log_ekle("Yonetici cikis yapti.")
    return redirect(url_for('login'))

@app.route('/loglar')
def log_sayfasi():
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, islem, tarih FROM loglar ORDER BY id DESC")
    tum_loglar = c.fetchall()
    conn.close()

    return render_template('loglar.html', loglar=tum_loglar)

@app.route('/')
def index():
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, sunucu_adi, ip_adresi, port, durum, gecikme, son_kontrol, toplam_kontrol, basarili_kontrol, ssl_gun FROM sunucular")
    sunucular = c.fetchall()

    c.execute("SELECT islem, tarih FROM loglar ORDER BY id DESC LIMIT 5")
    son_loglar = c.fetchall()

    toplam = len(sunucular)
    aktif = sum(1 for s in sunucular if s[4] == 'Calisiyor')
    kapali = sum(1 for s in sunucular if s[4] != 'Calisiyor' and s[4] != 'Bilinmiyor')

    conn.close()
    return render_template('index.html', sunucular=sunucular, toplam=toplam, aktif=aktif, kapali=kapali, loglar=son_loglar)

@app.route('/api/durum')
def api_durum():
    if not session.get('giris'):
        return jsonify({"hata": "Yetkisiz"}), 401

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, sunucu_adi, ip_adresi, port, durum, gecikme, son_kontrol, toplam_kontrol, basarili_kontrol, ssl_gun FROM sunucular")
    sunucular_raw = c.fetchall()

    c.execute("SELECT islem, tarih FROM loglar ORDER BY id DESC LIMIT 5")
    loglar_raw = c.fetchall()
    conn.close()

    sunucular = []
    for s in sunucular_raw:
        toplam_k = s[7] or 0
        basarili_k = s[8] or 0
        uptime_pct = round((basarili_k / toplam_k * 100), 1) if toplam_k > 0 else 100.0

        sunucular.append({
            "id": s[0],
            "sunucu_adi": s[1],
            "ip_adresi": s[2],
            "port": s[3],
            "durum": s[4],
            "gecikme": s[5],
            "son_kontrol": s[6] or '-',
            "uptime": uptime_pct,
            "ssl_gun": s[9] if s[9] is not None else -1
        })

    loglar = [{"islem": l[0], "tarih": l[1]} for l in loglar_raw]
    toplam = len(sunucular)
    aktif = sum(1 for s in sunucular if s['durum'] == 'Calisiyor')
    kapali = sum(1 for s in sunucular if s['durum'] != 'Calisiyor' and s['durum'] != 'Bilinmiyor')

    cpu_usage = psutil.cpu_percent(interval=None)
    ram_usage = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/').percent

    return jsonify({
        "sunucular": sunucular,
        "loglar": loglar,
        "istatistik": {
            "toplam": toplam,
            "aktif": aktif,
            "kapali": kapali
        },
        "sistem": {
            "cpu": cpu_usage,
            "ram": ram_usage,
            "disk": disk_usage
        }
    })

@app.route('/ekle', methods=['POST'])
def ekle():
    if not session.get('giris'):
        return redirect(url_for('login'))

    ad = request.form['sunucu_adi']
    ip = hedefi_temizle(request.form['ip_adresi'])
    port = int(request.form.get('port', 80))

    if ad and ip:
        durum, gecikme, ssl_gun = ping_server(ip, port)
        simdi = datetime.now().strftime("%H:%M:%S")
        basarili = 1 if durum == "Calisiyor" else 0
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            INSERT INTO sunucular (sunucu_adi, ip_adresi, port, durum, gecikme, son_kontrol, toplam_kontrol, basarili_kontrol, ssl_gun) 
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (ad, ip, port, durum, gecikme, simdi, basarili, ssl_gun))
        conn.commit()
        conn.close()
        log_ekle(f"Yeni altyapi eklendi: {ad} ({ip}:{port})")
    return redirect(url_for('index'))

@app.route('/duzenle/<int:id>', methods=['POST'])
def duzenle(id):
    if not session.get('giris'):
        return redirect(url_for('login'))

    yeni_ad = request.form['sunucu_adi']
    yeni_ip = hedefi_temizle(request.form['ip_adresi'])
    yeni_port = int(request.form.get('port', 80))

    durum, gecikme, ssl_gun = ping_server(yeni_ip, yeni_port)
    simdi = datetime.now().strftime("%H:%M:%S")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        UPDATE sunucular 
        SET sunucu_adi = ?, ip_adresi = ?, port = ?, durum = ?, gecikme = ?, son_kontrol = ?, ssl_gun = ?
        WHERE id = ?
    """, (yeni_ad, yeni_ip, yeni_port, durum, gecikme, simdi, ssl_gun, id))
    conn.commit()
    conn.close()
    log_ekle(f"Sunucu guncellendi (ID: {id}): {yeni_ad}")
    return redirect(url_for('index'))

@app.route('/ping/<int:id>')
def ping(id):
    if not session.get('giris'):
        return redirect(url_for('login'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT ip_adresi, port, sunucu_adi, toplam_kontrol, basarili_kontrol FROM sunucular WHERE id = ?", (id,))
    row = c.fetchone()

    if row:
        ip, port, ad, t_sayi, b_sayi = row
        durum, gecikme, ssl_gun = ping_server(ip, port)
        simdi = datetime.now().strftime("%H:%M:%S")
        t_sayi = (t_sayi or 0) + 1
        if durum == "Calisiyor":
            b_sayi = (b_sayi or 0) + 1
        c.execute("""
            UPDATE sunucular 
            SET durum = ?, gecikme = ?, son_kontrol = ?, toplam_kontrol = ?, basarili_kontrol = ?, ssl_gun = ?
            WHERE id = ?
        """, (durum, gecikme, simdi, t_sayi, b_sayi, ssl_gun, id))
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
    c.execute("SELECT id, ip_adresi, port, sunucu_adi, toplam_kontrol, basarili_kontrol FROM sunucular")
    liste = c.fetchall()

    simdi = datetime.now().strftime("%H:%M:%S")
    for s_id, ip, port, ad, t_sayi, b_sayi in liste:
        durum, gecikme, ssl_gun = ping_server(ip, port)
        t_sayi = (t_sayi or 0) + 1
        if durum == "Calisiyor":
            b_sayi = (b_sayi or 0) + 1
        c.execute("""
            UPDATE sunucular 
            SET durum = ?, gecikme = ?, son_kontrol = ?, toplam_kontrol = ?, basarili_kontrol = ?, ssl_gun = ?
            WHERE id = ?
        """, (durum, gecikme, simdi, t_sayi, b_sayi, ssl_gun, s_id))

    conn.commit()
    conn.close()
    log_ekle("Tum altyapi manuel toplu olarak tarandi.")
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
    c.execute("SELECT sunucu_adi, ip_adresi, port, durum, gecikme, son_kontrol, toplam_kontrol, basarili_kontrol, ssl_gun FROM sunucular")
    veriler = c.fetchall()
    conn.close()

    cikti = "Sunucu Adi,IP Adresi,Port,Durum,Gecikme (ms),Uptime (%),SSL Kalan Gun,Son Kontrol\n"
    for v in veriler:
        t_k = v[6] or 1
        b_k = v[7] or 0
        uptime = round((b_k / t_k * 100), 1)
        ssl_metin = f"{v[8]} gun" if v[8] >= 0 else "N/A"
        cikti += f"{v[0]},{v[1]},{v[2]},{v[3]},{v[4]}ms,%{uptime},{ssl_metin},{v[5]}\n"

    return Response(
        cikti,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=altyapi_sla_raporu.csv"}
    )

init_db()

# Arka Plan Kontrol Motoru (15 saniyede bir kesinti tespiti)
bg_thread = threading.Thread(target=otomatik_kontrol_dongusu, daemon=True)
bg_thread.start()

# Arka Plan Saatlik Rapor Motoru (Her 1 saatte bir tam durum ozeti)
report_thread = threading.Thread(target=saatlik_rapor_dongusu, daemon=True)
report_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
