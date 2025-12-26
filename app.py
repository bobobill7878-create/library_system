import threading
import time
import requests # 用於自我喚醒
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

# 🔥 引入最強偽裝套件 (用於爬蟲)
from curl_cffi import requests as crequests

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- 資料庫設定 ---
database_url = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- 檔案上傳設定 ---
UPLOAD_FOLDER = 'static/covers'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# --- 模型定義 ---
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
    # 🔥 入庫日期 (預設今天)
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

# --- 輔助函式 ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def safe_get(url):
    try:
        # 使用 curl_cffi 模擬 Chrome 110
        response = crequests.get(url, impersonate="chrome110", timeout=15)
        return response
    except Exception as e:
        print(f"Request Error: {e}")
        return None

# ==========================================
# 🔥 爬蟲工具區
# ==========================================

# 1. MOMO
def scrape_momo(isbn):
    url = f"https://m.momoshop.com.tw/search.momo?searchKeyword={isbn}"
    try:
        res = safe_get(url)
        if not res or res.status_code != 200: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.goodsItem')
        if not item: return None

        title = item.select_one('.prdName').text.strip()
        detail_link = item.select_one('a')['href']
        author, publisher, year, month, cover, desc = "未知作者", "", None, None, "", ""

        if detail_link:
            if not detail_link.startswith("http"): detail_link = "https://m.momoshop.com.tw" + detail_link
            d_res = safe_get(detail_link)
            if d_res:
                d_soup = BeautifulSoup(d_res.text, 'html.parser')
                content_area = d_soup.select_one('.Area02') or d_soup.select_one('.attributesTable')
                if content_area:
                    text = content_area.get_text()
                    m = re.search(r'出版社[：:]\s*(.+)', text); publisher = m.group(1).strip() if m else ""
                    m = re.search(r'作者[：:]\s*(.+)', text); author = m.group(1).strip() if m else "未知作者"
                    m = re.search(r'出版日[：:]\s*(\d{4})[\/-](\d{1,2})', text); 
                    if m: year, month = m.group(1), m.group(2)

                img = d_soup.select_one('.swiper-slide img')
                if img: cover = img.get('src')
                desc_area = d_soup.select_one('.Area03')
                if desc_area: desc = desc_area.get_text(strip=True)[:500]

        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": desc}
    except: return None

# 2. 三民
def scrape_sanmin(isbn):
    url = f"https://www.sanmin.com.tw/search/index?ct=all&k={isbn}"
    try:
        res = safe_get(url)
        if not res: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.SearchItem')
        if not item: return None

        title = item.select_one('.ProdName').text.strip()
        author = (item.select_one('.Author') or {}).text.strip() or "未知"
        publisher = (item.select_one('.Publisher') or {}).text.strip() or ""
        year, month = None, None
        date_tag = item.select_one('.PubDate')
        if date_tag:
            m = re.search(r'(\d{4})[\/-](\d{1,2})', date_tag.text)
            if m: year, month = m.group(1), m.group(2)
        img = item.select_one('img')
        cover = img.get('src') if img else ""
        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": "(來源:三民書局)"}
    except: return None

# 3. 博客來 (ISBN)
def scrape_books_com_tw(isbn):
    url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
    try:
        res = safe_get(url)
        if not res: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.table-search-tbody .table-td') or soup.select_one('li.item')
        if not item: return None

        title_tag = item.select_one('h4 a') or item.select_one('h3 a')
        if not title_tag: return None
        title = title_tag.get('title') or title_tag.text.strip()
        author = (item.select_one('a[rel="go_author"]') or {}).text or "未知"
        publisher = (item.select_one('a[rel="go_publisher"]') or {}).text or ""
        text = item.get_text()
        year, month = None, None
        m = re.search(r'(\d{4})[\/-](\d{1,2})', text)
        if m: year, month = m.group(1), m.group(2)
        img = item.select_one('img')
        cover = img.get('data-src') or img.get('src') or ""
        if cover and not cover.startswith("http"): cover = "https:" + cover
        return {"success": True, "title": title, "author": author.strip(), "publisher": publisher.strip(), "year": year, "month": month, "cover_url": cover, "description": ""}
    except: return None

# 4. Google Books (ISBN)
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
                cover = img.get('large') or img.get('thumbnail')
                if cover and cover.startswith("http"): cover = cover.replace("http", "https", 1)
                return {"success": True, "title": v.get('title'), "author": ", ".join(v.get('authors', [])), "publisher": v.get('publisher'), "year": y, "month": m, "cover_url": cover, "description": v.get('description')}
    except: pass
    return None

# 5. 博客來 (關鍵字搜尋)
def search_books_com_tw_keyword(keyword):
    url = f"https://search.books.com.tw/search/query/key/{keyword}/cat/all"
    try:
        res = safe_get(url)
        if not res: return []
        soup = BeautifulSoup(res.text, 'html.parser')
        results = []
        items = soup.select('.table-search-tbody tr') or soup.select('li.item')
        for item in items[:8]:
            try:
                title_tag = item.select_one('h4 a') or item.select_one('h3 a') or item.select_one('.box_header h3 a')
                if not title_tag: continue
                title = title_tag.get('title') or title_tag.text.strip()
                
                img_tag = item.select_one('img')
                cover = img_tag.get('data-src') or img_tag.get('src') or ""
                if cover and not cover.startswith('http'): cover = 'https:' + cover
                
                author = "未知"
                publisher = ""
                
                a_auth = item.select_one('a[rel="go_author"]')
                if a_auth: author = a_auth.text.strip()
                
                a_pub = item.select_one('a[rel="go_publisher"]')
                if a_pub: publisher = a_pub.text.strip()
                
                if author == "未知":
                    text = item.get_text()
                    if '作者：' in text: author = text.split('作者：')[1].split('出版社：')[0].strip()

                results.append({
                    "source": "博客來",
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "cover_url": cover,
                    "year": "",
                    "isbn": "",
                    "description": ""
                })
            except: continue
        return results
    except: return []

# 6. Google (關鍵字搜尋)
def search_google_keyword(keyword):
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={keyword}&maxResults=8&printType=books"
        res = requests.get(url, timeout=5)
        results = []
        if res.status_code == 200:
            data = res.json()
            for item in data.get('items', []):
                v = item.get('volumeInfo', {})
                isbn = ""
                for ident in v.get('industryIdentifiers', []):
                    if ident['type'] == 'ISBN_13': isbn = ident['identifier']
                
                img = v.get('imageLinks', {})
                cover = img.get('thumbnail') or img.get('smallThumbnail') or ""
                if cover.startswith("http://"): cover = cover.replace("http://", "https://")

                pd = v.get('publishedDate', '')
                year = pd.split('-')[0] if pd else ""

                results.append({
                    "source": "Google",
                    "title": v.get('title'),
                    "author": ", ".join(v.get('authors', [])),
                    "publisher": v.get('publisher', ''),
                    "cover_url": cover,
                    "year": year,
                    "isbn": isbn,
                    "description": v.get('description', '')
                })
        return results
    except: return []

# ==========================================
# 路由設定
# ==========================================

@app.route('/init_db')
def init_db():
    try:
        db.create_all()
        if not Category.query.first():
            for name in ['小說','原文小說', '漫畫', '原文漫畫', '畫冊', '寫真', '設定集']: db.session.add(Category(name=name))
            db.session.commit()
        return "初始化完成"
    except Exception as e: return f"失敗: {e}"

# 🔥 首頁 (支援多選篩選、完整欄位搜尋)
@app.route('/')
def index():
    try:
        search_field = request.args.get('search_field', 'all') 
        query = request.args.get('query', '').strip()  
        
        # 接收多選 Checkbox
        selected_cats = request.args.getlist('category_id') 
        selected_status = request.args.getlist('status_filter')

        books_query = Book.query

        if query:
            # 全欄位搜尋
            base_filter = (
                Book.title.ilike(f'%{query}%') | 
                Book.author.ilike(f'%{query}%') | 
                Book.publisher.ilike(f'%{query}%') | 
                Book.series.ilike(f'%{query}%') | 
                Book.isbn.ilike(f'%{query}%') |
                Book.tags.ilike(f'%{query}%')
            )
            
            # 指定欄位搜尋
            if search_field == 'title': search_filter = Book.title.ilike(f'%{query}%')
            elif search_field == 'author': search_filter = Book.author.ilike(f'%{query}%')
            elif search_field == 'publisher': search_filter = Book.publisher.ilike(f'%{query}%')
            elif search_field == 'isbn': search_filter = Book.isbn.ilike(f'%{query}%')
            elif search_field == 'series': search_filter = Book.series.ilike(f'%{query}%')
            else: search_filter = base_filter
            
            books_query = books_query.filter(search_filter)

        # 多選分類篩選
        if selected_cats:
            cat_ids = [int(c) for c in selected_cats if c.isdigit()]
            if cat_ids:
                books_query = books_query.filter(Book.category_id.in_(cat_ids))

        # 多選狀態篩選
        if selected_status:
            books_query = books_query.filter(Book.status.in_(selected_status))
        
        # 排序：入庫日期新->舊，ID新->舊
        all_books = books_query.order_by(Book.added_date.desc(), Book.id.desc()).all()
        all_categories = Category.query.all()
        
        # 回傳給前端
        return render_template('index.html', 
                               books=all_books, 
                               categories=all_categories, 
                               current_query=query, 
                               current_search_field=search_field,
                               selected_cats=selected_cats, 
                               selected_status=selected_status)
    except Exception as e: return f"資料庫錯誤: {e}"

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            cover_url = request.form.get('cover_url')
            if 'cover_file' in request.files:
                file = request.files['cover_file']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4().hex}.{filename.rsplit('.', 1)[1].lower()}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    cover_url = url_for('static', filename=f'covers/{unique_filename}')

            y = request.form.get('year')
            m = request.form.get('month')
            cat_id = request.form.get('category')
            rating = request.form.get('rating')

            new_book = Book(
                title=request.form.get('title'),
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                isbn=request.form.get('isbn'),
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
                rating=int(rating) if rating else 0,
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
        y = request.form.get('year')
        book.year = int(y) if y and y.isdigit() else None
        m = request.form.get('month')
        book.month = int(m) if m and m.isdigit() else None
        cat_id = request.form.get('category')
        book.category_id = int(cat_id) if cat_id and cat_id.isdigit() else None
        book.print_version = request.form.get('print_version')
        book.description = request.form.get('description')
        book.notes = request.form.get('notes')
        book.series = request.form.get('series')
        book.volume = request.form.get('volume')
        book.location = request.form.get('location')
        book.status = request.form.get('status')
        r = request.form.get('rating')
        book.rating = int(r) if r else 0
        book.tags = request.form.get('tags')

        # 編輯入庫日期
        added_d = request.form.get('added_date')
        if added_d:
            try: book.added_date = datetime.datetime.strptime(added_d, '%Y-%m-%d').date()
            except: pass

        if 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}.{filename.rsplit('.', 1)[1].lower()}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                book.cover_url = url_for('static', filename=f'covers/{unique_filename}')
        elif request.form.get('cover_url'):
            book.cover_url = request.form.get('cover_url')

        db.session.commit()
        return redirect(url_for('index'))
    return render_template('edit_book.html', book=book, categories=Category.query.all())

@app.route('/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            name = name.strip()
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

@app.route('/api/book/<int:book_id>', methods=['GET'])
def get_book_data(book_id):
    book = Book.query.get_or_404(book_id)
    return jsonify(book.to_dict())

@app.route('/api/search_keyword/<keyword>', methods=['GET'])
def search_keyword(keyword):
    if not keyword: return jsonify([]), 400
    books_results = search_books_com_tw_keyword(keyword)
    google_results = search_google_keyword(keyword)
    return jsonify(books_results + google_results)

@app.route('/api/lookup_isbn/<isbn>', methods=['GET'])
def lookup_isbn(isbn):
    if not isbn: return jsonify({"error": "Empty ISBN"}), 400
    clean_isbn = isbn.replace('-', '').strip()
    if res := scrape_momo(clean_isbn): return jsonify(res)
    if res := scrape_sanmin(clean_isbn): return jsonify(res)
    if res := scrape_books_com_tw(clean_isbn): return jsonify(res)
    if res := scrape_google(clean_isbn): return jsonify(res)
    return jsonify({"error": "Not Found"}), 404

@app.route('/dashboard')
def dashboard():
    total = Book.query.count()
    cat = dict(db.session.query(Category.name, func.count(Book.id)).join(Book).group_by(Category.name).all())
    status = dict(db.session.query(Book.status, func.count(Book.id)).group_by(Book.status).all())
    rating = dict(db.session.query(Book.rating, func.count(Book.id)).group_by(Book.rating).all())
    return render_template('dashboard.html', total=total, cat_stats=cat, status_stats=status, rating_stats=rating)

# 🔥 匯出 Excel
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
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='圖書清單')
    output.seek(0)
    return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=library_export.xlsx"})

# 🔥 匯入 Excel
@app.route('/import', methods=['GET', 'POST'])
def import_books():
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '': return redirect(request.url)
        if file:
            try:
                df = None
                if file.filename.endswith('.csv'):
                    try: df = pd.read_csv(file, encoding='utf-8-sig')
                    except: file.seek(0); df = pd.read_csv(file, encoding='big5')
                elif file.filename.endswith(('.xls', '.xlsx')):
                    df = pd.read_excel(file)
                else: return render_template('import_books.html', error="格式不支援")

                df.columns = [str(c).strip() for c in df.columns]
                success_count = 0
                for index, row in df.iterrows():
                    title = str(row.get('書名', '')).strip()
                    if not title or title == 'nan': continue
                    
                    cat_name = str(row.get('分類', '')).strip()
                    cat_id = None
                    if cat_name and cat_name != 'nan':
                        cat = Category.query.filter_by(name=cat_name).first()
                        if not cat:
                            cat = Category(name=cat_name)
                            db.session.add(cat); db.session.flush()
                        cat_id = cat.id

                    def gstr(v): return str(v).strip() if str(v)!='nan' else ''
                    def gint(v): 
                        try: return int(float(v))
                        except: return None
                    
                    added_d = row.get('入庫日期')
                    final_date = datetime.date.today()
                    if added_d and str(added_d) != 'nan':
                        try: final_date = pd.to_datetime(added_d).date()
                        except: pass

                    new_book = Book(
                        title=title, author=str(row.get('作者', '')),
                        publisher=gstr(row.get('出版社')), isbn=gstr(row.get('ISBN')),
                        year=gint(row.get('出版年')), month=gint(row.get('出版月')),
                        category_id=cat_id, status=gstr(row.get('狀態')) or '未讀',
                        rating=gint(row.get('評分')) or 0, description=gstr(row.get('大綱')),
                        series=gstr(row.get('叢書')), volume=gstr(row.get('集數')),
                        location=gstr(row.get('位置')), tags=gstr(row.get('標籤')),
                        added_date=final_date, notes=gstr(row.get('備註'))
                    )
                    db.session.add(new_book)
                    success_count += 1
                db.session.commit()
                return render_template('import_books.html', success_message=f"成功匯入 {success_count} 本書籍")
            except Exception as e: return render_template('import_books.html', error=str(e))
    return render_template('import_books.html')

# ==========================================
# 🔥 防止 Render 休眠的自我喚醒機制
# ==========================================
def keep_alive():
    # 請將此網址改為您 Render 部署後的實際網址
    url = "https://library-system-9ti8.onrender.com" 
    while True:
        time.sleep(600)  # 每 10 分鐘 (600秒) 喚醒一次
        try:
            print(f"⏰ 自我喚醒: {url}")
            requests.get(url)
        except Exception as e:
            print(f"❌ 喚醒失敗: {e}")

# 在背景啟動防休眠執行緒 (只在 Render 環境執行)
if os.environ.get('RENDER'):
    threading.Thread(target=keep_alive, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True)
