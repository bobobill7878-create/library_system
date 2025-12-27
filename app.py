import threading
import time
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename
import datetime
import os
import uuid
import re
from bs4 import BeautifulSoup
import pandas as pd
import io
import urllib3
from curl_cffi import requests as crequests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- 資料庫與設定 ---
database_url = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/covers'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# --- 模型 ---
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    books = db.relationship('Book', backref='category', lazy=True)

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 爬蟲工具 ---
def safe_get(url):
    try:
        response = crequests.get(
            url, impersonate="chrome120", 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=10
        )
        return response
    except: return None

# ISBN 爬蟲 (MOMO, 三民, 博客來, Google) - 保持原本邏輯
def scrape_momo(isbn):
    url = f"https://m.momoshop.com.tw/search.momo?searchKeyword={isbn}"
    try:
        res = safe_get(url)
        if not res or "驗證碼" in res.text: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.goodsItem')
        if not item: return None
        title = item.select_one('.prdName').text.strip()
        detail_link = item.select_one('a')['href']
        author, publisher, year, month, cover, desc = "", "", None, None, "", ""
        if detail_link:
            if not detail_link.startswith("http"): detail_link = "https://m.momoshop.com.tw" + detail_link
            if d_res := safe_get(detail_link):
                d_soup = BeautifulSoup(d_res.text, 'html.parser')
                img = d_soup.select_one('.swiper-slide img')
                if img: cover = img.get('src')
                content = d_soup.select_one('.Area02') or d_soup.select_one('.attributesTable')
                if content:
                    txt = content.get_text()
                    if m := re.search(r'出版社[：:]\s*(.+)', txt): publisher = m.group(1).strip()
                    if m := re.search(r'作者[：:]\s*(.+)', txt): author = m.group(1).strip()
                    if m := re.search(r'出版日[：:]\s*(\d{4})[\/-](\d{1,2})', txt): year, month = m.group(1), m.group(2)
                d_area = d_soup.select_one('.Area03')
                if d_area: desc = d_area.get_text(strip=True)[:500]
        return {"source": "MOMO", "success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": desc}
    except: return None

def scrape_sanmin(isbn):
    try:
        res = safe_get(f"https://www.sanmin.com.tw/search/index?ct=all&k={isbn}")
        if not res: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.SearchItem')
        if not item: return None
        title = item.select_one('.ProdName').text.strip()
        author = (item.select_one('.Author') or {}).text or ""
        publisher = (item.select_one('.Publisher') or {}).text or ""
        year, month = None, None
        if dt := item.select_one('.PubDate'):
            if m := re.search(r'(\d{4})[\/-](\d{1,2})', dt.text): year, month = m.group(1), m.group(2)
        img = item.select_one('img')
        return {"source": "三民", "success": True, "title": title, "author": author.strip(), "publisher": publisher.strip(), "year": year, "month": month, "cover_url": img.get('src') if img else "", "description": ""}
    except: return None

def scrape_books(isbn):
    try:
        res = safe_get(f"https://search.books.com.tw/search/query/key/{isbn}/cat/all")
        if not res: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.table-search-tbody .table-td') or soup.select_one('li.item')
        if not item: return None
        title_tag = item.select_one('h4 a') or item.select_one('h3 a')
        if not title_tag: return None
        title = title_tag.get('title') or title_tag.text.strip()
        author = (item.select_one('a[rel="go_author"]') or {}).text or ""
        if not author and "作者：" in item.text: author = item.text.split("作者：")[1].split("出版社")[0].strip()
        publisher = (item.select_one('a[rel="go_publisher"]') or {}).text or ""
        year, month = None, None
        if m := re.search(r'(\d{4})[\/-](\d{1,2})', item.text): year, month = m.group(1), m.group(2)
        img = item.select_one('img')
        cover = img.get('data-src') or img.get('src') or ""
        if cover and not cover.startswith("http"): cover = "https:" + cover
        return {"source": "博客來", "success": True, "title": title, "author": author.strip(), "publisher": publisher.strip(), "year": year, "month": month, "cover_url": cover, "description": ""}
    except: return None

def scrape_google(isbn):
    try:
        res = requests.get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('totalItems', 0) > 0:
                v = data['items'][0]['volumeInfo']
                pd = v.get('publishedDate', '')
                y = pd.split('-')[0] if pd else None
                m = pd.split('-')[1] if len(pd.split('-')) > 1 else None
                img = v.get('imageLinks', {})
                cover = img.get('thumbnail') or img.get('smallThumbnail') or ""
                if cover.startswith("http://"): cover = cover.replace("http://", "https://")
                return {"source": "Google", "success": True, "title": v.get('title'), "author": ", ".join(v.get('authors', [])), "publisher": v.get('publisher', ''), "year": y, "month": m, "cover_url": cover, "description": v.get('description', '')}
    except: pass
    return None

# 🔥 新增：MOMO 關鍵字搜尋
def search_momo_keyword(keyword):
    try:
        res = safe_get(f"https://m.momoshop.com.tw/search.momo?searchKeyword={keyword}")
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        results = []
        for item in soup.select('.goodsItem')[:5]: # 取前5筆
            try:
                title = item.select_one('.prdName').text.strip()
                link = item.select_one('a')['href']
                if not link.startswith("http"): link = "https://m.momoshop.com.tw" + link
                
                # 簡單抓作者出版社
                desc_text = item.get_text()
                pub = ""
                # MOMO 列表頁資訊較少，主要抓標題封面
                img = item.select_one('img')
                cover = img.get('src') if img else ""

                results.append({
                    "source": "MOMO",
                    "title": title,
                    "author": "詳見內頁",
                    "publisher": "MOMO來源",
                    "cover_url": cover,
                    "isbn": "", # 列表頁通常沒ISBN
                    "description": ""
                })
            except: continue
        return results
    except: return []

# 🔥 新增：博客來 關鍵字搜尋 (改進版)
def search_books_keyword(keyword):
    try:
        res = safe_get(f"https://search.books.com.tw/search/query/key/{keyword}/cat/all")
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        results = []
        items = soup.select('.table-search-tbody tr') or soup.select('li.item')
        for item in items[:5]:
            try:
                title_tag = item.select_one('h4 a') or item.select_one('h3 a')
                if not title_tag: continue
                title = title_tag.get('title') or title_tag.text.strip()
                img = item.select_one('img')
                cover = img.get('data-src') or img.get('src') or ""
                if cover and not cover.startswith('http'): cover = 'https:' + cover
                
                author = (item.select_one('a[rel="go_author"]') or {}).text or ""
                publisher = (item.select_one('a[rel="go_publisher"]') or {}).text or ""
                
                results.append({
                    "source": "博客來",
                    "title": title,
                    "author": author.strip(),
                    "publisher": publisher.strip(),
                    "cover_url": cover,
                    "isbn": "",
                    "description": ""
                })
            except: continue
        return results
    except: return []

# Google 關鍵字
def search_google_keyword(keyword):
    try:
        res = requests.get(f"https://www.googleapis.com/books/v1/volumes?q={keyword}&maxResults=5&printType=books", timeout=5)
        results = []
        if res.status_code == 200:
            data = res.json()
            for item in data.get('items', []):
                v = item.get('volumeInfo', {})
                isbn = ""
                for ident in v.get('industryIdentifiers', []):
                    if ident['type'] == 'ISBN_13': isbn = ident['identifier']
                
                img = v.get('imageLinks', {})
                cover = img.get('thumbnail') or ""
                if cover.startswith("http://"): cover = cover.replace("http://", "https://")

                results.append({
                    "source": "Google",
                    "title": v.get('title'),
                    "author": ", ".join(v.get('authors', [])),
                    "publisher": v.get('publisher', ''),
                    "cover_url": cover,
                    "isbn": isbn,
                    "description": v.get('description', '')
                })
        return results
    except: return []

# --- Routes ---
@app.route('/init_db')
def init_db():
    db.create_all()
    if not Category.query.first():
        for name in ['小說','原文小說', '漫畫', '原文漫畫', '畫冊', '寫真', '設定集']: db.session.add(Category(name=name))
        db.session.commit()
    return "初始化完成"

@app.route('/')
def index():
    search_field = request.args.get('search_field', 'all') 
    query = request.args.get('query', '').strip()  
    selected_cats = request.args.getlist('category_id') 
    selected_status = request.args.getlist('status_filter')

    books_query = Book.query

    if query:
        base_filter = (Book.title.ilike(f'%{query}%') | Book.author.ilike(f'%{query}%') | Book.publisher.ilike(f'%{query}%') | Book.series.ilike(f'%{query}%') | Book.isbn.ilike(f'%{query}%') | Book.tags.ilike(f'%{query}%'))
        if search_field == 'title': books_query = books_query.filter(Book.title.ilike(f'%{query}%'))
        elif search_field == 'author': books_query = books_query.filter(Book.author.ilike(f'%{query}%'))
        elif search_field == 'isbn': books_query = books_query.filter(Book.isbn.ilike(f'%{query}%'))
        else: books_query = books_query.filter(base_filter)

    if selected_cats:
        books_query = books_query.filter(Book.category_id.in_([int(c) for c in selected_cats if c.isdigit()]))
    if selected_status:
        books_query = books_query.filter(Book.status.in_(selected_status))
    
    return render_template('index.html', books=books_query.order_by(Book.added_date.desc(), Book.id.desc()).all(), categories=Category.query.all(), current_query=query, current_search_field=search_field, selected_cats=selected_cats, selected_status=selected_status)

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
            
            # 🔥 修正：確保 ISBN 從表單獲取
            isbn_val = request.form.get('isbn') 

            new_book = Book(
                title=request.form.get('title'),
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                isbn=isbn_val, # 使用修正後的 ISBN
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

        if 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and allowed_file(file.filename):
                fname = f"{uuid.uuid4().hex}.{file.filename.rsplit('.', 1)[1].lower()}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                book.cover_url = url_for('static', filename=f'covers/{fname}')
        elif request.form.get('cover_url'): book.cover_url = request.form.get('cover_url')

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

@app.route('/api/book/<int:book_id>')
def get_book_data(book_id): return jsonify(Book.query.get_or_404(book_id).to_dict())

@app.route('/api/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    clean = isbn.replace('-', '').strip()
    if not clean: return jsonify({"error": "Empty"}), 400
    if res := scrape_momo(clean): return jsonify(res)
    if res := scrape_sanmin(clean): return jsonify(res)
    if res := scrape_books(clean): return jsonify(res)
    if res := scrape_google(clean): return jsonify(res)
    return jsonify({"error": "Not Found"}), 404

# 🔥 搜尋 API：同時搜尋 Google, 博客來, MOMO
@app.route('/api/search_keyword/<keyword>')
def search_keyword(keyword):
    if not keyword: return jsonify([]), 400
    r1 = search_books_keyword(keyword)
    r2 = search_momo_keyword(keyword)
    r3 = search_google_keyword(keyword)
    return jsonify(r1 + r2 + r3)

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
                
                # 簡單轉換
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

def keep_alive():
    url = "https://library-system-9ti8.onrender.com/" # 請確認此網址
    while True:
        time.sleep(600)
        try: requests.get(url)
        except: pass
if os.environ.get('RENDER'): threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__': app.run(debug=True)
