from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os

app = Flask(__name__)
DB_NAME = "envanter.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sunucular (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sunucu_adi TEXT NOT NULL,
            ip_adresi TEXT NOT NULL,
            durum TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sunucular")
    sunucular = cursor.fetchall()
    conn.close()
    return render_template('index.html', sunucular=sunucular)

@app.route('/ekle', methods=['POST'])
def ekle():
    ad = request.form['sunucu_adi']
    ip = request.form['ip_adresi']
    durum = request.form['durum']
    if ad and ip:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sunucular (sunucu_adi, ip_adresi, durum) VALUES (?, ?, ?)", (ad, ip, durum))
        conn.commit()
        conn.close()
    return redirect(url_for('index'))

@app.route('/sil/<int:id>')
def sil(id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sunucular WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)