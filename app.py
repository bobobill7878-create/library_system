from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename
import requests
import datetime
import os 
import uuid 
import csv
import io
import re
from bs4 import BeautifulSoup
import pandas as pd
import urllib3

# 🔥 引入最強偽裝套件
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
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

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

# ==========================================
# 🔥 核彈級爬蟲工具區 (curl_cffi) 🔥
# ==========================================

# 通用請求函式：模擬 Chrome 110 的指紋，繞過 WAF
def safe_get(url):
    try:
        # impersonate="chrome110" 是關鍵，它會發送跟真實 Chrome 完全一樣的 TLS 封包
        response = crequests.get(url, impersonate="chrome110", timeout=15)
        return response
    except Exception as e:
        print(f"Request Error: {e}")
        return None

# 1. MOMO 購物網 (救援主力)
def scrape_momo(isbn):
    print(f">>> [MOMO] 開始查詢: {isbn}")
    url = f"https://m.momoshop.com.tw/search.momo?searchKeyword={isbn}"
    try:
        res = safe_get(url)
        if not res or res.status_code != 200: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # MOMO 搜尋結果
        item = soup.select_one('.goodsItem')
        if not item: 
            print(">>> [MOMO] 未找到項目")
            return None

        title = item.select_one('.prdName').text.strip()
        
        # 進入詳情頁
        detail_link = item.select_one('a')['href']
        author = "未知作者"
        publisher = ""
        year, month = None, None
        cover = ""
        desc = ""

        if detail_link:
            if not detail_link.startswith("http"): 
                detail_link = "https://m.momoshop.com.tw" + detail_link
            
            d_res = safe_get(detail_link)
            if d_res:
                d_soup = BeautifulSoup(d_res.text, 'html.parser')
                
                content_area = d_soup.select_one('.Area02') or d_soup.select_one('.attributesTable')
                if content_area:
                    text = content_area.get_text()
                    pub_match = re.search(r'出版社[：:]\s*(.+)', text)
                    if pub_match: publisher = pub_match.group(1).strip()
                    auth_match = re.search(r'作者[：:]\s*(.+)', text)
                    if auth_match: author = auth_match.group(1).strip()
                    date_match = re.search(r'出版日[：:]\s*(\d{4})[\/-](\d{1,2})', text)
                    if date_match: year, month = date_match.group(1), date_match.group(2)

                img = d_soup.select_one('.swiper-slide img')
                if img: cover = img.get('src')
                
                desc_area = d_soup.select_one('.Area03')
                if desc_area: desc = desc_area.get_text(strip=True)[:500]

        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": desc}
            
    except Exception as e:
        print(f">>> [MOMO] 錯誤: {e}")
        return None

# 2. 三民書局 (非常適合 curl_cffi)
def scrape_sanmin(isbn):
    print(f">>> [三民] 開始查詢: {isbn}")
    url = f"https://www.sanmin.com.tw/search/index?ct=all&k={isbn}"
    try:
        res = safe_get(url)
        if not res: return None
        soup = BeautifulSoup(res.text, 'html.parser')
        
        item = soup.select_one('.SearchItem')
        if not item: return None
        
        title = item.select_one('.ProdName').text.strip()
        author = item.select_one('.Author').text.strip()
        publisher = item.select_one('.Publisher').text.strip()
        
        year, month = None, None
        date_tag = item.select_one('.PubDate')
        if date_tag:
            match = re.search(r'(\d{4})[\/-](\d{1,2})', date_tag.text)
            if match: year, month = match.group(1), match.group(2)
            
        img = item.select_one('img')
        cover = img.get('src') if img else ""
        
        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": "(來源:三民書局)"}
    except: return None

# 3. 博客來 (需要 curl_cffi 繞過 WAF)
def scrape_books_com_tw(isbn):
    print(f">>> [博客來] 開始查詢: {isbn}")
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
        match = re.search(r'(\d{4})[\/-](\d{1,2})', text)
        if match: year, month = match.group(1), match.group(2)
        
        img = item.select_one('img')
        cover = img.get('data-src') or img.get('src') or ""
        if cover and not cover.startswith("http"): cover = "https:" + cover
        
        return {"success": True, "title": title, "author": author.strip(), "publisher": publisher.strip(), "year": year, "month": month, "cover_url": cover, "description": ""}
    except: return None

# 4. Google Books API (不需要 cffi，普通 requests 即可)
def scrape_google(isbn):
    try:
        api_url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('totalItems', 0) > 0:
                v = data['items'][0]['volumeInfo']
                pd = v.get('publishedDate', '')
                y = pd.split('-')[0] if pd else None
                m = pd.split('-')[1] if len(pd.split('-')) > 1 else None
                img = v.get('imageLinks', {})
                cover = img.get('large') or img.get('thumbnail')
                if cover and cover.startswith("http://"): cover = cover.replace("http://", "https://")
                return {"success": True, "title": v.get('title'), "author": ", ".join(v.get('authors', [])), "publisher": v.get('publisher'), "year": y, "month": m, "cover_url": cover, "description": v.get('description')}
    except: pass
    return None

# ==========================================

@app.route('/init_db')
def init_db():
    try:
        db.create_all()
        if not Category.query.first():
            default_categories = ['小說','原文小說', '漫畫', '原文漫畫', '畫冊', '寫真', '設定集']
            for name in default_categories: db.session.add(Category(name=name))
            db.session.commit()
            return "初始化成功"
        return "無需初始化"
    except Exception as e: return f"失敗: {e}"

@app.route('/')
def index():
    try:
        search_field = request.args.get('search_field', 'all') 
        query = request.args.get('query', '').strip()  
        category_id = request.args.get('category_id') 
        status_filter = request.args.get('status_filter')
        books_query = Book.query
        if query:
            base_filter = Book.title.ilike(f'%{query}%') | Book.author.ilike(f'%{query}%') | Book.publisher.ilike(f'%{query}%') | Book.series.ilike(f'%{query}%') | Book.tags.ilike(f'%{query}%')
            if search_field == 'title': search_filter = Book.title.ilike(f'%{query}%')
            elif search_field == 'author': search_filter = Book.author.ilike(f'%{query}%')
            elif search_field == 'publisher': search_filter = Book.publisher.ilike(f'%{query}%')
            elif search_field == 'series': search_filter = Book.series.ilike(f'%{query}%')
            else: search_filter = base_filter
            books_query = books_query.filter(search_filter)
        if category_id and category_id.isdigit(): books_query = books_query.filter(Book.category_id == int(category_id))
        if status_filter: books_query = books_query.filter(Book.status == status_filter)
        all_books = books_query.order_by(Book.series.desc(), Book.volume.asc(), Book.id.desc()).all()
        all_categories = Category.query.all()
        return render_template('index.html', books=all_books, categories=all_categories, current_query=query, current_category_id=category_id, current_search_field=search_field, current_status=status_filter)
    except Exception as e: return f"資料庫未連線: {e} <a href='/init_db'>初始化</a>"

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        title = request.form.get('title')
        author = request.form.get('author')
        publisher = request.form.get('publisher') 
        isbn = request.form.get('isbn')
        year = request.form.get('year')
        month = request.form.get('month') 
        category_id = request.form.get('category')
        cover_url = request.form.get('cover_url') 
        print_version = request.form.get('print_version') 
        notes = request.form.get('notes')
        description = request.form.get('description')
        series = request.form.get('series')
        volume = request.form.get('volume')
        location = request.form.get('location')
        status = request.form.get('status')
        rating = request.form.get('rating')
        tags = request.form.get('tags')

        if 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{file_ext}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                cover_url = url_for('static', filename=f'covers/{unique_filename}')
                
        if not title or not author:
             all_categories = Category.query.all()
             return render_template('add_book.html', categories=all_categories, error="書名與作者為必填欄位。"), 400

        new_book = Book(
            title=title, author=author, publisher=publisher, isbn=isbn,
            year=int(year) if year and year.isdigit() else None,
            month=int(month) if month and month.isdigit() else None,
            category_id=int(category_id) if category_id and category_id.isdigit() else None,
            cover_url=cover_url, description=description, print_version=print_version, notes=notes,
            series=series, volume=volume, location=location, status=status, rating=int(rating) if rating else 0, tags=tags
        )
        try:
            db.session.add(new_book)
            db.session.commit()
            return redirect(url_for('add_book', success=True))
        except Exception as e:
            all_categories = Category.query.all()
            return render_template('add_book.html', categories=all_categories, error=f'錯誤: {e}'), 500
    all_categories = Category.query.all()
    success_message = request.args.get('success')
    return render_template('add_book.html', categories=all_categories, success_message="圖書新增成功！" if success_message else None)

@app.route('/edit/<int:book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.publisher = request.form.get('publisher')
        book.isbn = request.form.get('isbn')
        year = request.form.get('year')
        book.year = int(year) if year and year.isdigit() else None
        month = request.form.get('month')
        book.month = int(month) if month and month.isdigit() else None
        cat_id = request.form.get('category')
        book.category_id = int(cat_id) if cat_id and cat_id.isdigit() else None
        book.print_version = request.form.get('print_version')
        book.description = request.form.get('description')
        book.notes = request.form.get('notes')
        book.series = request.form.get('series')
        book.volume = request.form.get('volume')
        book.location = request.form.get('location')
        book.status = request.form.get('status')
        rating_val = request.form.get('rating')
        book.rating = int(rating_val) if rating_val else 0
        book.tags = request.form.get('tags')

        current_cover_url = request.form.get('cover_url')
        if 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{file_ext}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                current_cover_url = url_for('static', filename=f'covers/{unique_filename}')
        book.cover_url = current_cover_url
        try:
            db.session.commit()
            return redirect(url_for('index'))
        except: return '錯誤', 500
    all_categories = Category.query.all()
    return render_template('edit_book.html', book=book, categories=all_categories)

@app.route('/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    book_to_delete = Book.query.get_or_404(book_id)
    db.session.delete(book_to_delete)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('category_name').strip()
        if name:
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name))
                db.session.commit()
                return redirect(url_for('manage_categories'))
        return render_template('manage_categories.html', categories=Category.query.all(), error="錯誤")
    return render_template('manage_categories.html', categories=Category.query.all())

@app.route('/category/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    Category.query.get_or_404(category_id)
    Book.query.filter_by(category_id=category_id).update({'category_id': None})
    db.session.delete(Category.query.get(category_id))
    db.session.commit()
    return redirect(url_for('manage_categories'))

@app.route('/category/edit/<int:category_id>', methods=['POST'])
def edit_category(category_id):
    cat = Category.query.get_or_404(category_id)
    new_name = request.form.get('new_name').strip()
    if not new_name: return jsonify({"success": False}), 400
    if new_name != cat.name and Category.query.filter_by(name=new_name).first():
        return jsonify({"success": False}), 409
    cat.name = new_name
    db.session.commit()
    return jsonify({"success": True, "new_name": new_name})

@app.route('/api/book/<int:book_id>', methods=['GET'])
def get_book_data(book_id):
    book = Book.query.get_or_404(book_id)
    return jsonify({
        'id': book.id, 'title': book.title, 'author': book.author,
        'publisher': book.publisher or 'N/A', 'isbn': book.isbn or 'N/A',
        'year': book.year, 'month': book.month,
        'category': book.category.name if book.category else '無分類',
        'print_version': book.print_version or 'N/A',
        'notes': book.notes or '', 'description': book.description or '',
        'cover_url': book.cover_url,
        'series': book.series or '', 'volume': book.volume or '',
        'location': book.location or '', 'status': book.status, 'rating': book.rating, 'tags': book.tags or ''
    })

@app.route('/dashboard')
def dashboard():
    total = Book.query.count()
    cat = dict(db.session.query(Category.name, func.count(Book.id)).join(Book).group_by(Category.name).all())
    status = dict(db.session.query(Book.status, func.count(Book.id)).group_by(Book.status).all())
    rating = dict(db.session.query(Book.rating, func.count(Book.id)).group_by(Book.rating).all())
    return render_template('dashboard.html', total=total, cat_stats=cat, status_stats=status, rating_stats=rating)

@app.route('/export')
def export_csv():
    books = Book.query.all()
    output = io.StringIO()
    output.write('\ufeff') 
    writer = csv.writer(output)
    writer.writerow(['ID', '書名', '作者', '出版社', 'ISBN', '分類', '叢書', '集數', '狀態', '評分', '位置', '加入日期'])
    for book in books:
        writer.writerow([book.id, book.title, book.author, book.publisher, f"'{book.isbn}" if book.isbn else '', book.category.name if book.category else '無分類', book.series, book.volume, book.status, book.rating, book.location, book.added_date])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=library_backup.csv"})

@app.route('/import', methods=['GET', 'POST'])
def import_books():
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '': return redirect(request.url)
        if file:
            try:
                if file.filename.endswith('.csv'):
                    try: df = pd.read_csv(file, encoding='utf-8-sig')
                    except: file.seek(0); df = pd.read_csv(file, encoding='big5')
                elif file.filename.endswith(('.xls', '.xlsx')):
                    df = pd.read_excel(file)
                else: return render_template('import_books.html', error="不支援的檔案格式")

                success_count = 0
                df.columns = [c.strip() for c in df.columns]
                for index, row in df.iterrows():
                    title = str(row.get('書名', '')).strip()
                    if not title or title == 'nan': continue
                    
                    cat_name = str(row.get('分類', '')).strip()
                    category_id = None
                    if cat_name and cat_name != 'nan':
                        cat = Category.query.filter_by(name=cat_name).first()
                        if not cat:
                            cat = Category(name=cat_name)
                            db.session.add(cat); db.session.flush()
                        category_id = cat.id

                    def get_int(val): 
                        try: return int(float(val))
                        except: return None
                    def get_str(val):
                        s = str(val).strip()
                        return s if s != 'nan' else ''

                    new_book = Book(
                        title=title, author=str(row.get('作者', '')).strip(),
                        publisher=get_str(row.get('出版社')), isbn=get_str(row.get('ISBN')),
                        series=get_str(row.get('叢書') or row.get('叢書名')),
                        volume=get_str(row.get('集數')), location=get_str(row.get('位置')),
                        status=get_str(row.get('狀態')) or '未讀',
                        print_version=get_str(row.get('版本')),
                        year=get_int(row.get('出版年')), month=get_int(row.get('出版月')),
                        rating=get_int(row.get('評分')) or 0, tags=get_str(row.get('標籤')),
                        description=get_str(row.get('大綱')), notes=get_str(row.get('備註')),
                        category_id=category_id
                    )
                    db.session.add(new_book)
                    success_count += 1
                db.session.commit()
                return render_template('import_books.html', success_message=f"成功匯入 {success_count} 本！")
            except Exception as e: return render_template('import_books.html', error=f"失敗：{str(e)}")
    return render_template('import_books.html')

@app.route('/api/search_keyword/<keyword>', methods=['GET'])
def search_keyword(keyword):
    if not keyword: return jsonify([]), 400
    results = []
    try:
        api_url = f"https://www.googleapis.com/books/v1/volumes?q={keyword}&maxResults=15&printType=books"
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'items' in data:
                for item in data['items']:
                    v = item.get('volumeInfo', {})
                    isbn = ""
                    for ident in v.get('industryIdentifiers', []):
                        if ident['type'] == 'ISBN_13': isbn = ident['identifier']; break
                    if not isbn and v.get('industryIdentifiers'): isbn = v['industryIdentifiers'][0]['identifier']
                    
                    pd = v.get('publishedDate', '')
                    year = pd.split('-')[0] if pd else ""
                    img = v.get('imageLinks', {})
                    cover = img.get('thumbnail') or img.get('smallThumbnail') or ""
                    if cover and cover.startswith("http://"): cover = cover.replace("http://", "https://")

                    results.append({
                        "title": v.get('title', '無標題'),
                        "author": ", ".join(v.get('authors', ['未知'])),
                        "publisher": v.get('publisher', ''),
                        "year": year, "isbn": isbn, "cover_url": cover,
                        "description": v.get('description', '')
                    })
    except: pass
    return jsonify(results)

# ====== 🔥 診斷路由 (請訪問 /api/debug_scrape/ISBN) 🔥 ======
@app.route('/api/debug_scrape/<isbn>', methods=['GET'])
def debug_scrape(isbn):
    clean_isbn = isbn.replace('-', '').strip()
    result = {"isbn": clean_isbn, "logs": []}
    
    # 測試 MOMO
    try:
        momo_data = scrape_momo(clean_isbn)
        if momo_data: result["logs"].append(f"MOMO: Success! Found {momo_data['title']}")
        else: result["logs"].append("MOMO: Failed (None)")
    except Exception as e: result["logs"].append(f"MOMO: Error {e}")

    # 測試 Sanmin
    try:
        sanmin_data = scrape_sanmin(clean_isbn)
        if sanmin_data: result["logs"].append(f"Sanmin: Success! Found {sanmin_data['title']}")
        else: result["logs"].append("Sanmin: Failed (None)")
    except Exception as e: result["logs"].append(f"Sanmin: Error {e}")

    return jsonify(result)

# ====== 智慧查詢路由 (MOMO -> 三民 -> 博客來 -> Google) ======
@app.route('/api/lookup_isbn/<isbn>', methods=['GET'])
def lookup_isbn(isbn):
    if not isbn: return jsonify({"error": "ISBN 碼不可為空"}), 400
    clean_isbn = isbn.replace('-', '').strip()
    result_data = None
    
    # 1. MOMO (最強新書源)
    momo_data = scrape_momo(clean_isbn)
    if momo_data: return jsonify(momo_data)

    # 2. 三民 (次強)
    sanmin_data = scrape_sanmin(clean_isbn)
    if sanmin_data: return jsonify(sanmin_data)

    # 3. 博客來
    books_tw = scrape_books_com_tw(clean_isbn)
    if books_tw: return jsonify(books_tw)

    # 4. Google API (補充外文)
    google_data = scrape_google(clean_isbn)
    if google_data: return jsonify(google_data)

    return jsonify({"error": "找不到此 ISBN (Render IP 可能被封鎖，請嘗試診斷路由)"}), 404

if __name__ == '__main__':
    app.run(debug=True)
