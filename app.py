import threading
import time
import requests
import os
import uuid
import re
import datetime
import io
import random
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename
from bs4 import BeautifulSoup
import pandas as pd

# 🔥 引入偽裝瀏覽器套件 (解決博客來/MOMO 擋爬蟲問題)
from curl_cffi import requests as crequests

app = Flask(__name__)

# --- 1. 設定與資料庫 ---
# 支援 Render 的 PostgreSQL，本地則使用 SQLite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 圖片上傳設定
UPLOAD_FOLDER = 'static/covers'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

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
    publisher = db.Column(db.String(100), nullable=True)
    isbn = db.Column(db.String(20), nullable=True)
    year = db.Column(db.Integer)
    month = db.Column(db.Integer)
    cover_url = db.Column(db.String(500), nullable=True)
    added_date = db.Column(db.Date, default=datetime.date.today, nullable=False)
    description = db.Column(db.Text, nullable=True)
    print_version = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    series = db.Column(db.String(100), nullable=True)
    volume = db.Column(db.String(20), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='未讀')
    rating = db.Column(db.Integer, default=0)
    tags = db.Column(db.String(200), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'author': self.author,
            'publisher': self.publisher, 'isbn': self.isbn,
            'year': self.year, 'month': self.month,
            'category': self.category.name if self.category else '無分類',
            'status': self.status, 'rating': self.rating, 'location': self.location,
            'description': self.description, 'notes': self.notes,
            'cover_url': self.cover_url, 'series': self.series, 'volume': self.volume, 'tags': self.tags,
            'print_version': self.print_version,
            'added_date': self.added_date.strftime('%Y-%m-%d') if self.added_date else ''
        }

# --- 3. 輔助函式 ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def normalize_string(s):
    """
    模糊比對用的正規化函式：
    移除標點符號、空格、括號，只保留中英文字母與數字。
    例如: "書名 (7)" -> "書名7"
    """
    if not s: return ""
    s = s.lower()
    # 保留 CJK漢字, A-Z, 0-9
    s = re.sub(r'[^\u4e00-\u9fa5a-z0-9]', '', s)
    return s

def safe_get(url):
    """
    使用 curl_cffi 偽裝成真實瀏覽器發送請求。
    隨機切換指紋以降低被阻擋機率。
    """
    try:
        browser_type = random.choice(["chrome110", "edge101", "safari15_3"])
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ]
        
        # Timeout 設定為 6 秒，避免拖慢整體搜尋
        response = crequests.get(
            url, 
            impersonate=browser_type, 
            headers={
                "User-Agent": random.choice(user_agents),
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.com/"
            },
            timeout=6 
        )
        return response
    except Exception as e:
        print(f"⚠️ Fetch Error ({url}): {e}")
        return None

# --- 4. 搜尋邏輯 (API 與 爬蟲) ---

def search_google_api(keyword):
    """【推薦】Google Books 官方 API (穩定、不擋IP)"""
    results = []
    try:
        # maxResults=10, 限制繁體中文
        api_url = f"https://www.googleapis.com/books/v1/volumes?q={quote(keyword)}&langRestrict=zh-TW&maxResults=10&printType=books"
        # 官方 API 用一般 requests 即可
        r = requests.get(api_url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            for item in data.get('items', []):
                v = item.get('volumeInfo', {})
                isbn = ""
                for ident in v.get('industryIdentifiers', []):
                    if ident['type'] == 'ISBN_13': isbn = ident['identifier']
                
                img = v.get('imageLinks', {})
                cover = img.get('thumbnail') or img.get('smallThumbnail') or ""
                if cover.startswith("http://"): cover = cover.replace("http://", "https://")

                results.append({
                    "source": "GoogleAPI",
                    "title": v.get('title'),
                    "author": ", ".join(v.get('authors', [])),
                    "publisher": v.get('publisher', ''),
                    "cover_url": cover,
                    "isbn": isbn,
                    "description": v.get('description', '')
                })
    except Exception as e:
        print(f"GoogleAPI Error: {e}")
    return results

def scrape_sanmin(keyword):
    """三民書局 (較好爬)"""
    results = []
    try:
        url = f"https://www.sanmin.com.tw/search/index/?ct=K&q={quote(keyword)}"
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 三民結構可能會變，嘗試多種選擇器
        items = soup.select('.result_list .item') or soup.select('.product-list > div')
        
        for item in items[:5]:
            try:
                title_tag = item.select_one('h3 a') or item.select_one('.prod_name a')
                if not title_tag: continue
                
                img_tag = item.select_one('img')
                cover = img_tag.get('src') if img_tag else ""
                
                txt = item.text
                author = txt.split('作者：')[1].split('\n')[0].strip() if '作者：' in txt else ""
                publisher = txt.split('出版社：')[1].split('\n')[0].strip() if '出版社：' in txt else ""

                results.append({
                    "source": "三民",
                    "title": title_tag.text.strip(),
                    "author": author,
                    "publisher": publisher,
                    "cover_url": cover,
                    "isbn": "",
                    "description": ""
                })
            except: continue
    except: pass
    return results

def scrape_stepstone(keyword):
    """墊腳石 (API 模式)"""
    results = []
    try:
        url = f"https://www.tcsb.com.tw/v2/Search?q={quote(keyword)}&shopId=14"
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.box-shadow-product-item')
        
        for item in items[:5]:
            try:
                title = item.select_one('.b-text-overflow').text.strip()
                img = item.select_one('img')['src']
                results.append({
                    "source": "墊腳石",
                    "title": title,
                    "author": "",
                    "publisher": "墊腳石來源",
                    "cover_url": img,
                    "isbn": "", "description": ""
                })
            except: continue
    except: pass
    return results

def scrape_books_com(keyword):
    """博客來 (容易被擋，作為輔助)"""
    results = []
    try:
        url = f"https://search.books.com.tw/search/query/key/{quote(keyword)}/cat/all"
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.table-search-tbody tr') or soup.select('li.item')
        
        for item in items[:5]:
            try:
                title_tag = item.select_one('h4 a') or item.select_one('h3 a')
                if not title_tag: continue
                img = item.select_one('img')
                cover = img.get('data-src') or img.get('src') or ""
                if cover and not cover.startswith('http'): cover = 'https:' + cover
                
                author_tag = item.select_one('a[rel="go_author"]')
                author = author_tag.text if author_tag else ""
                
                results.append({
                    "source": "博客來",
                    "title": title_tag.get('title') or title_tag.text.strip(),
                    "author": author,
                    "publisher": "",
                    "cover_url": cover,
                    "isbn": "", "description": ""
                })
            except: continue
    except: pass
    return results

def scrape_eslite(keyword):
    """誠品 (輔助)"""
    try:
        res = safe_get(f"https://www.eslite.com/search?q={quote(keyword)}")
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        results = []
        items = soup.select('.product-item') or soup.select('.item-card')
        for item in items[:5]:
            try:
                title_tag = item.select_one('.product-name') or item.select_one('h3')
                if not title_tag: continue
                img = item.select_one('img')
                cover = img.get('src') if img else ""
                results.append({
                    "source": "誠品",
                    "title": title_tag.text.strip(),
                    "author": "",
                    "publisher": "誠品來源",
                    "cover_url": cover,
                    "isbn": "", "description": ""
                })
            except: continue
        return results
    except: return []

# --- 5. 路由設定 ---

@app.route('/init_db')
def init_db():
    try:
        db.create_all()
        if not Category.query.first():
            for name in ['小說','原文小說', '漫畫', '原文漫畫', '畫冊', '寫真', '設定集']: 
                db.session.add(Category(name=name))
            db.session.commit()
        return "初始化完成"
    except Exception as e: return f"失敗: {e}"

@app.route('/')
def index():
    search_field = request.args.get('search_field', 'all') 
    query = request.args.get('query', '').strip()  
    
    # Checkbox 多選
    selected_cats = request.args.getlist('category_id') 
    selected_status = request.args.getlist('status_filter')

    books_query = Book.query

    if query:
        base_filter = (
            Book.title.ilike(f'%{query}%') | 
            Book.author.ilike(f'%{query}%') | 
            Book.publisher.ilike(f'%{query}%') | 
            Book.series.ilike(f'%{query}%') | 
            Book.isbn.ilike(f'%{query}%') |
            Book.tags.ilike(f'%{query}%')
        )
        if search_field == 'title': books_query = books_query.filter(Book.title.ilike(f'%{query}%'))
        elif search_field == 'author': books_query = books_query.filter(Book.author.ilike(f'%{query}%'))
        elif search_field == 'isbn': books_query = books_query.filter(Book.isbn.ilike(f'%{query}%'))
        elif search_field == 'publisher': books_query = books_query.filter(Book.publisher.ilike(f'%{query}%'))
        else: books_query = books_query.filter(base_filter)

    if selected_cats:
        cat_ids = [int(c) for c in selected_cats if c.isdigit()]
        if cat_ids: books_query = books_query.filter(Book.category_id.in_(cat_ids))
        
    if selected_status:
        books_query = books_query.filter(Book.status.in_(selected_status))
    
    all_books = books_query.order_by(Book.added_date.desc(), Book.id.desc()).all()
    all_categories = Category.query.all()
    
    return render_template('index.html', 
                           books=all_books, 
                           categories=all_categories, 
                           current_query=query, 
                           current_search_field=search_field,
                           selected_cats=selected_cats, 
                           selected_status=selected_status)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            cover_url = request.form.get('cover_url')
            if 'cover_file' in request.files:
                file = request.files['cover_file']
                if file and allowed_file(file.filename):
                    fname = f"{uuid.uuid4().hex}.{file.filename.rsplit('.', 1)[1].lower()}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                    cover_url = url_for('static', filename=f'covers/{fname}')

            y = request.form.get('year')
            m = request.form.get('month')
            cat_id = request.form.get('category')
            isbn_val = request.form.get('isbn') 

            new_book = Book(
                title=request.form.get('title'),
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                isbn=isbn_val, 
                year=int(y) if y and y.isdigit() else None,
                month=int(m) if m and m.isdigit() else None,
                category_id=int(cat_id) if cat_id and cat_id.isdigit() else None,
                cover_url=cover_url,
                description=request.form.get('description'),
                print_version=request.form.get('print_version'),
                notes=request.form.get('notes'),
                series=request.form.get('series'),
                volume=request.form.get('volume'),
                location=request.form.get('location'),
                status=request.form.get('status'),
                rating=int(request.form.get('rating') or 0),
                tags=request.form.get('tags'),
                added_date=datetime.date.today()
            )
            db.session.add(new_book)
            db.session.commit()
            return redirect(url_for('add_book', success=True))
        except Exception as e:
            return render_template('add_book.html', categories=Category.query.all(), error=str(e))
    return render_template('add_book.html', categories=Category.query.all(), success_message="新增成功" if request.args.get('success') else None)

@app.route('/edit/<int:book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.publisher = request.form.get('publisher')
        book.isbn = request.form.get('isbn')
        y, m = request.form.get('year'), request.form.get('month')
        book.year = int(y) if y and y.isdigit() else None
        book.month = int(m) if m and m.isdigit() else None
        cid = request.form.get('category')
        book.category_id = int(cid) if cid and cid.isdigit() else None
        book.print_version = request.form.get('print_version')
        book.description = request.form.get('description')
        book.notes = request.form.get('notes')
        book.series = request.form.get('series')
        book.volume = request.form.get('volume')
        book.location = request.form.get('location')
        book.status = request.form.get('status')
        book.rating = int(request.form.get('rating') or 0)
        book.tags = request.form.get('tags')
        
        if d := request.form.get('added_date'):
            try: book.added_date = datetime.datetime.strptime(d, '%Y-%m-%d').date()
            except: pass

        file = request.files.get('cover_file')
        if file and file.filename and allowed_file(file.filename):
            fname = f"{uuid.uuid4().hex}.{file.filename.rsplit('.', 1)[1].lower()}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            book.cover_url = url_for('static', filename=f'covers/{fname}')
        else:
            new_url = request.form.get('cover_url')
            if new_url is not None: 
                book.cover_url = new_url

        db.session.commit()
        return redirect(url_for('index'))
    return render_template('edit_book.html', book=book, categories=Category.query.all())

@app.route('/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    db.session.delete(Book.query.get_or_404(book_id))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        if name := request.form.get('name').strip():
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name))
                db.session.commit()
                return redirect(url_for('manage_categories'))
    return render_template('categories.html', categories=Category.query.all())

@app.route('/category/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    cat = Category.query.get_or_404(category_id)
    Book.query.filter_by(category_id=category_id).update({'category_id': None})
    db.session.delete(cat)
    db.session.commit()
    return redirect(url_for('manage_categories'))

# --- API 路由 ---

@app.route('/api/book/<int:book_id>')
def get_book_data(book_id): 
    return jsonify(Book.query.get_or_404(book_id).to_dict())

@app.route('/api/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    """主要使用 Google API 查詢 ISBN，因為它最穩定"""
    clean = isbn.replace('-', '').strip()
    if not clean: return jsonify({"error": "Empty"}), 400
    
    # 優先使用 Google API
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get('totalItems', 0) > 0:
                v = data['items'][0]['volumeInfo']
                img = v.get('imageLinks', {})
                cover = img.get('thumbnail') or img.get('smallThumbnail') or ""
                if cover.startswith("http://"): cover = cover.replace("http://", "https://")
                
                return jsonify({
                    "source": "GoogleAPI",
                    "title": v.get('title'),
                    "author": ", ".join(v.get('authors', [])),
                    "publisher": v.get('publisher', ''),
                    "year": v.get('publishedDate', '')[:4],
                    "cover_url": cover,
                    "description": v.get('description', '')
                })
    except: pass
    
    # 如果 Google 沒找到，可以嘗試其他來源 (這裡省略以保持回應速度)
    return jsonify({"error": "Not Found"}), 404

@app.route('/api/check_title')
def check_title():
    """模糊書名查重"""
    raw_title = request.args.get('title', '').strip()
    if not raw_title: return jsonify({'exists': False})
    
    target = normalize_string(raw_title)
    all_titles = db.session.query(Book.title).all()
    
    for (db_t,) in all_titles:
        if normalize_string(db_t) == target:
            return jsonify({'exists': True, 'match': db_t})
    return jsonify({'exists': False})

@app.route('/api/search_keyword/<keyword>')
def search_keyword_api(keyword):
    """並行搜尋 API"""
    if not keyword: return jsonify([]), 400
    
    final_results = []
    # 使用 4 個執行緒，包含最穩定的 GoogleAPI
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(search_google_api, keyword),  # Google Official (最重要)
            executor.submit(scrape_sanmin, keyword),      # 三民 (次穩)
            executor.submit(scrape_stepstone, keyword),   # 墊腳石
            executor.submit(scrape_books_com, keyword),   # 博客來 (輔助)
            executor.submit(scrape_eslite, keyword)       # 誠品 (輔助)
        ]
        
        for future in as_completed(futures):
            try:
                # 設定 Timeout 8秒，避免拖累
                data = future.result(timeout=8)
                if data: final_results.extend(data)
            except Exception: pass
            
    return jsonify(final_results)

# --- 儀表板與匯出入 ---

@app.route('/dashboard')
def dashboard():
    total = Book.query.count()
    cat = dict(db.session.query(Category.name, func.count(Book.id)).join(Book).group_by(Category.name).all())
    status = dict(db.session.query(Book.status, func.count(Book.id)).group_by(Book.status).all())
    rating = dict(db.session.query(Book.rating, func.count(Book.id)).group_by(Book.rating).all())
    return render_template('dashboard.html', total=total, cat_stats=cat, status_stats=status, rating_stats=rating)

@app.route('/export')
def export_excel():
    books = Book.query.all()
    data = []
    for b in books:
        data.append({
            'ID': b.id, '書名': b.title, '作者': b.author, '出版社': b.publisher, 'ISBN': b.isbn,
            '分類': b.category.name if b.category else '無分類',
            '叢書': b.series, '集數': b.volume, '出版年': b.year, '出版月': b.month,
            '狀態': b.status, '評分': b.rating, '位置': b.location, '標籤': b.tags,
            '入庫日期': b.added_date, '大綱': b.description, '備註': b.notes
        })
    df = pd.DataFrame(data)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer: df.to_excel(writer, index=False)
    out.seek(0)
    return Response(out, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=library_export.xlsx"})

@app.route('/import', methods=['GET', 'POST'])
def import_books():
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '': return redirect(request.url)
        try:
            df = pd.read_csv(file, encoding='utf-8-sig') if file.filename.endswith('.csv') else pd.read_excel(file)
            df.columns = [str(c).strip() for c in df.columns]
            count = 0
            for _, row in df.iterrows():
                if not str(row.get('書名', '')).strip() or str(row.get('書名')) == 'nan': continue
                cat_id = None
                if cname := str(row.get('分類', '')).strip():
                    if cname != 'nan':
                        cat = Category.query.filter_by(name=cname).first()
                        if not cat: cat = Category(name=cname); db.session.add(cat); db.session.flush()
                        cat_id = cat.id
                
                def g(k): v=row.get(k); return str(v).strip() if str(v)!='nan' else ''
                def gi(k): 
                    try: return int(float(row.get(k))) 
                    except: return None
                
                ad = datetime.date.today()
                if d := row.get('入庫日期'):
                    try: ad = pd.to_datetime(d).date()
                    except: pass

                db.session.add(Book(
                    title=g('書名'), author=g('作者'), publisher=g('出版社'), isbn=g('ISBN'),
                    year=gi('出版年'), month=gi('出版月'), category_id=cat_id,
                    status=g('狀態') or '未讀', rating=gi('評分') or 0, description=g('大綱'),
                    series=g('叢書'), volume=g('集數'), location=g('位置'), tags=g('標籤'),
                    added_date=ad, notes=g('備註')
                ))
                count += 1
            db.session.commit()
            return render_template('import_books.html', success_message=f"成功匯入 {count} 本")
        except Exception as e: return render_template('import_books.html', error=str(e))
    return render_template('import_books.html')

# --- Render 防止休眠機制 ---
def keep_alive():
    # 請替換為您的 Render URL
    url = "https://your-app-name.onrender.com/" 
    while True:
        time.sleep(600) # 每10分鐘喚醒
        try:
            if "your-app-name" not in url: return # 若沒設定 URL 則不執行
            requests.get(url)
        except: pass

if os.environ.get('RENDER'):
    threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True)
