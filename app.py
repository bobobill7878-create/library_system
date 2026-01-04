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

from flask import Flask, render_template, request, redirect, url_for, jsonify, Response, flash
from flask_sqlalchemy import SQLAlchemy
from bs4 import BeautifulSoup
import pandas as pd

# 關鍵：使用 curl_cffi 繞過 Cloudflare/WAF 阻擋 (解決搜尋為 0 的問題)
try:
    from curl_cffi import requests as crequests
except ImportError:
    print("請執行 pip install curl-cffi 安裝必要套件")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_for_session') # Flash 訊息需要 Secret Key

# --- 1. 資料庫與設定 ---
database_url = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/covers'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# 確保圖片上傳目錄存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
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
    print_version = db.Column(db.String(50))
    notes = db.Column(db.Text)
    series = db.Column(db.String(100))
    volume = db.Column(db.String(20))
    location = db.Column(db.String(100))
    status = db.Column(db.String(20), default='未讀')
    rating = db.Column(db.Integer, default=0)
    tags = db.Column(db.String(200))
    added_date = db.Column(db.Date, default=datetime.date.today)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'author': self.author,
            'publisher': self.publisher, 'isbn': self.isbn,
            'cover_url': self.cover_url, 'year': self.year, 
            'description': self.description, 'status': self.status
        }

# --- 3. 爬蟲核心工具 (解決被擋問題) ---
def safe_get(url):
    """使用偽裝指紋發送請求，專門應對博客來/三民的防火牆"""
    try:
        impersonate_ver = random.choice(["chrome110", "edge101", "safari15_3"])
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
        ]
        time.sleep(random.uniform(0.5, 1.5)) # 模擬人類延遲

        response = crequests.get(
            url, 
            impersonate=impersonate_ver, 
            headers={
                "User-Agent": random.choice(user_agents),
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.com/"
            },
            timeout=10
        )
        if response.status_code == 200: return response
        return None
    except Exception as e:
        print(f"Crawler Error ({url}): {e}")
        return None

# --- 4. 各大書局搜尋邏輯 ---
def search_google_api(keyword):
    """Google Books API (穩定來源)"""
    results = []
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={quote(keyword)}&langRestrict=zh-TW&maxResults=10&printType=books"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            for item in data.get('items', []):
                v = item.get('volumeInfo', {})
                isbn = ""
                for ident in v.get('industryIdentifiers', []):
                    if ident['type'] == 'ISBN_13': isbn = ident['identifier']
                
                img_links = v.get('imageLinks', {})
                cover = img_links.get('thumbnail') or img_links.get('smallThumbnail') or ""
                if cover.startswith("http://"): cover = cover.replace("http://", "https://")

                results.append({
                    "source": "GoogleAPI",
                    "title": v.get('title'),
                    "author": ", ".join(v.get('authors', [])),
                    "publisher": v.get('publisher', ''),
                    "cover_url": cover,
                    "isbn": isbn,
                    "year": v.get('publishedDate', '')[:4],
                    "description": v.get('description', '')[:200]
                })
    except: pass
    return results

def scrape_readmoo(keyword):
    """Readmoo 讀墨 (雲端存活率高)"""
    results = []
    try:
        url = f"https://readmoo.com/search/keyword?q={quote(keyword)}"
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.item-info')
        for item in items[:5]:
            try:
                title_tag = item.select_one('h4 a')
                if not title_tag: continue
                img_div = item.parent.select_one('.thumbnail-wrap img')
                cover = img_div.get('data-original') or img_div.get('src') if img_div else ""
                author_tag = item.select_one('.author a')
                author = author_tag.text.strip() if author_tag else ""
                results.append({
                    "source": "Readmoo",
                    "title": title_tag.text.strip(),
                    "author": author,
                    "publisher": "Readmoo來源",
                    "cover_url": cover,
                    "isbn": "", "description": ""
                })
            except: continue
    except: pass
    return results

def scrape_sanmin(keyword):
    """三民書局"""
    results = []
    try:
        url = f"https://www.sanmin.com.tw/search/index/?ct=K&q={quote(keyword)}"
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.result_list .item') or soup.select('.product-list > div')
        for item in items[:5]:
            try:
                title_elem = item.select_one('h3 a') or item.select_one('.prod_name a')
                if not title_elem: continue
                img_elem = item.select_one('img')
                cover = img_elem.get('src') if img_elem else ""
                if cover and not cover.startswith('http'): cover = cover 
                txt = item.text
                author = txt.split('作者：')[1].split('\n')[0].strip() if '作者：' in txt else ""
                publisher = txt.split('出版社：')[1].split('\n')[0].strip() if '出版社：' in txt else ""
                results.append({
                    "source": "三民", "title": title_elem.text.strip(),
                    "author": author, "publisher": publisher, "cover_url": cover, "isbn": "", "description": ""
                })
            except: continue
    except: pass
    return results

def scrape_books_com(keyword):
    """博客來"""
    results = []
    try:
        url = f"https://search.books.com.tw/search/query/key/{quote(keyword)}/cat/all"
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.table-search-tbody tr') or soup.select('li.item')
        for item in items[:4]:
            try:
                title_tag = item.select_one('h4 a') or item.select_one('h3 a')
                if not title_tag: continue
                img = item.select_one('img')
                cover = img.get('data-src') or img.get('src') or ""
                if cover and not cover.startswith('http'): cover = 'https:' + cover
                author_tag = item.select_one('a[rel="go_author"]')
                author = author_tag.text if author_tag else ""
                results.append({
                    "source": "博客來", "title": title_tag.get('title') or title_tag.text.strip(),
                    "author": author, "publisher": "", "cover_url": cover, "isbn": "", "description": ""
                })
            except: continue
    except: pass
    return results

# --- 5. 核心路由 (完整 CRUD) ---

@app.route('/')
def index():
    """首頁：顯示書籍列表、搜尋、篩選"""
    cat_id = request.args.get('category')
    status = request.args.get('status')
    q = request.args.get('q')

    query = Book.query

    if cat_id:
        query = query.filter_by(category_id=cat_id)
    if status:
        query = query.filter_by(status=status)
    if q:
        search = f"%{q}%"
        query = query.filter(
            (Book.title.ilike(search)) | 
            (Book.author.ilike(search)) |
            (Book.tags.ilike(search))
        )
    
    books = query.order_by(Book.added_date.desc()).all()
    categories = Category.query.all()
    return render_template('index.html', books=books, categories=categories)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    """新增書籍"""
    if request.method == 'POST':
        try:
            cover_url = process_cover_image(request)
            
            y = request.form.get('year')
            m = request.form.get('month')
            cat_id = request.form.get('category')
            
            new_book = Book(
                title=request.form['title'],
                author=request.form['author'],
                publisher=request.form.get('publisher'),
                category_id=int(cat_id) if cat_id and cat_id.isdigit() else None,
                isbn=request.form.get('isbn'),
                year=int(y) if y and y.isdigit() else None,
                month=int(m) if m and m.isdigit() else None,
                status=request.form.get('status'),
                rating=int(request.form.get('rating') or 0),
                location=request.form.get('location'),
                series=request.form.get('series'),
                volume=request.form.get('volume'),
                print_version=request.form.get('print_version'),
                tags=request.form.get('tags'),
                description=request.form.get('description'),
                notes=request.form.get('notes'),
                cover_url=cover_url
            )
            db.session.add(new_book)
            db.session.commit()
            flash('書籍新增成功！', 'success')
            return redirect(url_for('add_book')) # 留在此頁繼續新增
        except Exception as e:
            flash(f'新增失敗：{str(e)}', 'danger')
            return redirect(url_for('add_book'))

    return render_template('add_book.html', categories=Category.query.all())

@app.route('/edit/<int:book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    """編輯書籍 (補回遺失的功能)"""
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        try:
            book.title = request.form['title']
            book.author = request.form['author']
            book.publisher = request.form.get('publisher')
            
            # 處理分類
            cat_id = request.form.get('category')
            book.category_id = int(cat_id) if cat_id and cat_id.isdigit() else None
            
            # 處理封面 (如果有新上傳才更新)
            new_cover = process_cover_image(request)
            if new_cover:
                book.cover_url = new_cover
            elif request.form.get('cover_url'): # 如果是貼網址
                book.cover_url = request.form.get('cover_url')

            book.isbn = request.form.get('isbn')
            book.year = int(request.form['year']) if request.form.get('year') else None
            book.month = int(request.form['month']) if request.form.get('month') else None
            book.status = request.form.get('status')
            book.rating = int(request.form.get('rating') or 0)
            book.location = request.form.get('location')
            book.series = request.form.get('series')
            book.volume = request.form.get('volume')
            book.print_version = request.form.get('print_version')
            book.tags = request.form.get('tags')
            book.description = request.form.get('description')
            book.notes = request.form.get('notes')
            
            db.session.commit()
            flash('書籍資料更新成功！', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'更新失敗：{str(e)}', 'danger')

    # 這裡為了方便，重複使用 add_book.html，但傳入 book 物件來填充資料
    return render_template('add_book.html', categories=Category.query.all(), book=book, is_edit=True)

@app.route('/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    """刪除書籍 (補回遺失的功能)"""
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    flash(f'已刪除書籍：{book.title}', 'warning')
    return redirect(url_for('index'))

@app.route('/categories', methods=['GET', 'POST'])
def categories():
    """分類管理 (補回遺失的功能)"""
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name))
                db.session.commit()
                flash('分類新增成功', 'success')
            else:
                flash('分類已存在', 'warning')
    
    cats = Category.query.all()
    # 計算每個分類的書籍數量
    for c in cats:
        c.count = Book.query.filter_by(category_id=c.id).count()
        
    return render_template('categories.html', categories=cats) # 需要 categories.html，若無請建立

@app.route('/categories/delete/<int:id>')
def delete_category(id):
    """刪除分類"""
    cat = Category.query.get_or_404(id)
    # 將該分類下的書籍設為無分類
    Book.query.filter_by(category_id=id).update({Book.category_id: None})
    db.session.delete(cat)
    db.session.commit()
    flash('分類已刪除', 'info')
    return redirect(url_for('categories'))

# --- 6. API 介面 ---

@app.route('/api/search_keyword/<keyword>')
def api_search(keyword):
    """多執行緒搜尋 API"""
    if not keyword: return jsonify([])
    final_results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(search_google_api, keyword),
            executor.submit(scrape_readmoo, keyword),
            executor.submit(scrape_sanmin, keyword),
            executor.submit(scrape_books_com, keyword)
        ]
        for future in as_completed(futures):
            try:
                data = future.result(timeout=10)
                if data: final_results.extend(data)
            except: pass
    return jsonify(final_results)

@app.route('/api/check_title')
def check_title():
    """檢查重複書名 API"""
    title = request.args.get('title', '')
    if not title: return jsonify({"exists": False})
    exists = Book.query.filter(Book.title.ilike(f"%{title}%")).first()
    if exists:
        return jsonify({"exists": True, "match": exists.title})
    return jsonify({"exists": False})

@app.route('/api/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    """ISBN 查詢 API"""
    try:
        clean = isbn.replace('-', '').strip()
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean}"
        r = requests.get(url, timeout=5)
        data = r.json()
        if 'items' in data:
            v = data['items'][0]['volumeInfo']
            img = v.get('imageLinks', {})
            cover = img.get('thumbnail') or img.get('smallThumbnail') or ""
            if cover.startswith("http://"): cover = cover.replace("http://", "https://")
            
            return jsonify({
                "source": "GoogleAPI",
                "title": v.get('title'),
                "author": ", ".join(v.get('authors', [])),
                "publisher": v.get('publisher'),
                "year": v.get('publishedDate', '')[:4],
                "cover_url": cover,
                "description": v.get('description', '')
            })
    except: pass
    return jsonify({"error": "Not Found"}), 404

# --- Helper Functions ---
def process_cover_image(req):
    """處理圖片上傳邏輯"""
    cover_url = req.form.get('cover_url')
    if 'cover_file' in req.files:
        file = req.files['cover_file']
        if file and file.filename != '':
            fname = f"{uuid.uuid4().hex}.{file.filename.split('.')[-1]}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            cover_url = url_for('static', filename=f'covers/{fname}')
    return cover_url

@app.route('/init_db')
def init_db():
    db.create_all()
    if not Category.query.first():
        defaults = ['文學小說', '商業理財', '心理勵志', '漫畫', '社會科學']
        for d in defaults: db.session.add(Category(name=d))
        db.session.commit()
    return "DB Initialized"

from flask import send_from_directory
@app.route('/static/covers/<path:filename>')
def serve_cover(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
