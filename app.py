from flask import Flask, render_template, request, redirect, url_for, session, Response
import sqlite3
import socket
import time
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

def ping_server(ip, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    basla = time.time()
    try:
        s.connect((ip, port))
        gecikme = int((time.time() - basla) * 1000)
        s.close()
        return "Çalışıyor", gecikme
    except:
        return "Erişilemiyor", 0

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
    kapali = sum(1 for s in sunucular if s[4] == 'Erişilemiyor')

    conn.close()
    return render_template('index.html', sunucular=sunucular, toplam=toplam, aktif=aktif, kapali=kapali, loglar=son_loglar)

@app.route('/ekle', methods=['POST'])
def ekle():
    if not session.get('giris'):
        return redirect(url_for('login'))

    ad = request.form['sunucu_adi']
    ip = request.form['ip_adresi']
    port = int(request.form.get('port', 80))

    if ad and ip:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO sunucular (sunucu_adi, ip_adresi, port) VALUES (?, ?, ?)", (ad, ip, port))
        conn.commit()
        conn.close()
        log_ekle(f"Yeni altyapı eklendi: {ad} ({ip}:{port})")
    return redirect(url_for('index'))

@app.route('/duzenle/<int:id>', methods=['POST'])
def duzenle(id):
    if not session.get('giris'):
        return redirect(url_for('login'))

    yeni_ad = request.form['sunucu_adi']
    yeni_ip = request.form['ip_adresi']
    yeni_port = int(request.form.get('port', 80))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE sunucular SET sunucu_adi = ?, ip_adresi = ?, port = ? WHERE id = ?", (yeni_ad, yeni_ip, yeni_port, id))
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
        log_ekle(f"Test yapıldı: {ad} -> {durum} ({gecikme}ms)")

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
    log_ekle("Tüm altyapı için toplu sağlık taraması gerçekleştirildi.")
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

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
