import os
import random
import time
import uuid
import datetime
import io
import threading
import requests
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, redirect, url_for, jsonify, Response, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from bs4 import BeautifulSoup
import pandas as pd

# 關鍵：使用 curl_cffi 繞過 Cloudflare/WAF 阻擋
try:
    from curl_cffi import requests as crequests
except ImportError:
    print("請執行 pip install curl-cffi 安裝必要套件")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_for_session') 

# --- [功能] 防止 Render 休眠邏輯 ---
def keep_alive():
    """在背景每 10 分鐘 Ping 自己一次，防止 Render 免費版休眠"""
    # 重要：請將下方的網址替換成你 Render 的實際網址
    url = "https://library-system-9ti8.onrender.com" 
    
    time.sleep(30) # 延遲啟動
    print(f"Keep-alive thread started: {url}")
    
    while True:
        try:
            r = requests.get(url, timeout=20)
            print(f"Keep-alive ping: Status {r.status_code}")
        except Exception as e:
            print(f"Keep-alive error: {e}")
        time.sleep(600) # 10 分鐘

# 僅在 Render 環境下啟動喚醒執行緒
if os.environ.get('RENDER'):
    threading.Thread(target=keep_alive, daemon=True).start()

# --- 1. 資料庫與設定 ---
database_url = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/covers'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)

# --- 2. 資料庫模型 ---
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    books = db.relationship('Book', backref='category', lazy=True)

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    publisher = db.Column(db.String(100))
    isbn = db.Column(db.String(20))
    year = db.Column(db.Integer)
    month = db.Column(db.Integer)
    cover_url = db.Column(db.String(500))
    description = db.Column(db.Text)
    series = db.Column(db.String(100))
    volume = db.Column(db.String(20))
    location = db.Column(db.String(100))
    status = db.Column(db.String(20), default='未讀')
    rating = db.Column(db.Integer, default=0)
    tags = db.Column(db.String(200))
    added_date = db.Column(db.Date, default=datetime.date.today)
    notes = db.Column(db.Text)
    print_version = db.Column(db.String(50))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))

# --- 3. 爬蟲工具與搜尋 API ---
def safe_get(url):
    try:
        impersonate_ver = random.choice(["chrome110", "edge101", "safari15_3"])
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-TW,zh;q=0.9"}
        res = crequests.get(url, impersonate=impersonate_ver, headers=headers, timeout=10)
        return res if res.status_code == 200 else None
    except: return None

def search_google_api(keyword):
    results = []
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={quote(keyword)}&maxResults=5"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            for item in r.json().get('items', []):
                v = item.get('volumeInfo', {})
                results.append({
                    "source": "Google", "title": v.get('title'), "author": ", ".join(v.get('authors', [])),
                    "publisher": v.get('publisher', ''), "cover_url": v.get('imageLinks', {}).get('thumbnail', ""),
                    "isbn": v.get('industryIdentifiers', [{}])[0].get('identifier', ""), "year": v.get('publishedDate', '')[:4]
                })
    except: pass
    return results

# --- 4. 路由設定 (含補足 HTML 缺失的路由) ---

@app.route('/')
def index():
    # 取得搜尋參數
    q = request.args.get('query', '')
    cat_ids = request.args.getlist('category_id')
    status_filters = request.args.getlist('status_filter')

    query = Book.query
    if q:
        query = query.filter(Book.title.ilike(f"%{q}%") | Book.author.ilike(f"%{q}%"))
    if cat_ids:
        query = query.filter(Book.category_id.in_(cat_ids))
    if status_filters:
        query = query.filter(Book.status.in_(status_filters))

    books = query.order_by(Book.added_date.desc()).all()
    categories = Category.query.all()
    return render_template('index.html', books=books, categories=categories, 
                           current_query=q, selected_cats=cat_ids, selected_status=status_filters)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            cover_url = process_cover_image(request)
            new_book = Book(
                title=request.form['title'], author=request.form['author'],
                publisher=request.form.get('publisher'),
                category_id=request.form.get('category'),
                isbn=request.form.get('isbn'),
                status=request.form.get('status', '未讀'),
                rating=int(request.form.get('rating') or 0),
                cover_url=cover_url,
                description=request.form.get('description')
            )
            db.session.add(new_book)
            db.session.commit()
            flash('新增成功！', 'success')
            return redirect(url_for('index'))
        except Exception as e: flash(f'錯誤: {e}', 'danger')
    return render_template('add_book.html', categories=Category.query.all())

@app.route('/edit/<int:book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        book.title = request.form['title']
        book.status = request.form.get('status')
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('add_book.html', book=book, categories=Category.query.all(), is_edit=True)

@app.route('/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/categories')
def categories():
    cats = Category.query.all()
    return render_template('categories.html', categories=cats)

# --- 補足 HTML 引用但缺少的路由 (解決 500 錯誤) ---

@app.route('/dashboard')
def dashboard():
    return "<h1>數據儀表板</h1><p>開發中，請回首頁。</p><a href='/'>返回</a>"

@app.route('/export_excel')
def export_excel():
    return "<h1>匯出 Excel</h1><p>功能開發中。</p><a href='/'>返回</a>"

@app.route('/import_books')
def import_books():
    return "<h1>匯入 Excel</h1><p>功能開發中。</p><a href='/'>返回</a>"

@app.route('/api/book/<int:book_id>')
def get_book_api(book_id):
    book = Book.query.get_or_404(book_id)
    return jsonify({
        'id': book.id, 'title': book.title, 'author': book.author,
        'publisher': book.publisher, 'status': book.status, 'rating': book.rating,
        'cover_url': book.cover_url, 'description': book.description,
        'added_date': str(book.added_date), 'isbn': book.isbn
    })

# --- 工具函式 ---
def process_cover_image(req):
    cover_url = req.form.get('cover_url')
    if 'cover_file' in req.files:
        file = req.files['cover_file']
        if file and file.filename != '':
            fname = f"{uuid.uuid4().hex}.{file.filename.split('.')[-1]}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            cover_url = url_for('static', filename=f'covers/{fname}')
    return cover_url

@app.route('/static/covers/<path:filename>')
def serve_cover(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- 啟動初始化 ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Category.query.first():
            for name in ['文學小說', '商業理財', '心理勵志']:
                db.session.add(Category(name=name))
            db.session.commit()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
