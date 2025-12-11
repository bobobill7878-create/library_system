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
import urllib3

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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 模型定義 ---
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    books = db.relationship('Book', backref='category', lazy=True)
    def __repr__(self): return f'<Category {self.name}>'

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
    def __repr__(self): return f'<Book {self.title}>'

# ==========================================
# 🔥 爬蟲工具區 (五大天王) 🔥
# ==========================================

# 通用 Header (偽裝成一般 Chrome)
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
}

# 1. 金石堂 (Kingstone) - 新增！
def scrape_kingstone(isbn):
    print(f">>> [金石堂] 開始查詢: {isbn}")
    url = f"https://www.kingstone.com.tw/search/key/{isbn}"
    try:
        res = requests.get(url, headers=COMMON_HEADERS, timeout=10)
        # 如果被重新導向到商品頁(只有一筆結果時)，或者在列表頁
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 嘗試找列表頁的第一個結果
        item = soup.select_one('li.displayunit')
        
        # 標題
        title = ""
        title_tag = soup.select_one('h3.pdname_box a') # 列表頁
        if not title_tag:
            title_tag = soup.select_one('h1.pdname_box') # 詳情頁
        
        if not title_tag: 
            print(">>> [金石堂] 未找到標題，可能無結果")
            return None
            
        title = title_tag.get('title') or title_tag.text.strip()
        
        # 作者
        author = "未知作者"
        author_tag = soup.select_one('span.author a') or soup.select_one('.basic_box .author a')
        if author_tag: author = author_tag.text.strip()

        # 出版社
        publisher = ""
        pub_tag = soup.select_one('span.publisher a') or soup.select_one('.basic_box .publisher a')
        if pub_tag: publisher = pub_tag.text.strip()

        # 日期
        year, month = None, None
        date_tag = soup.select_one('span.pubdate') or soup.select_one('.basic_box .pubdate')
        if date_tag:
            match = re.search(r'(\d{4})/(\d{1,2})', date_tag.text)
            if match: year, month = match.group(1), match.group(2)

        # 封面
        cover = ""
        img = soup.select_one('img.lazyload') or soup.select_one('.cover_box img')
        if img: cover = img.get('data-src') or img.get('src') or ""

        # 大綱 (如果是在列表頁，可能需要進去抓，這裡先略過以求速度)
        desc = ""
        desc_div = soup.select_one('.pdintro_txt1')
        if desc_div: desc = desc_div.get_text(strip=True)[:500] + "..."

        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": desc}

    except Exception as e:
        print(f">>> [金石堂] 錯誤: {e}")
        return None

# 2. 博客來
def scrape_books_com_tw(isbn):
    print(f">>> [博客來] 開始查詢: {isbn}")
    url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
    try:
        res = requests.get(url, headers=COMMON_HEADERS, timeout=8)
        if res.status_code != 200: 
            print(f">>> [博客來] HTTP {res.status_code} (可能被擋)")
            return None
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.table-search-tbody .table-td')
        if not item: return None

        title_tag = item.select_one('h4 a') or item.select_one('h3 a')
        if not title_tag: return None
        title = title_tag.get('title') or title_tag.text.strip()
        
        author = "未知"
        author_tag = item.select_one('a[rel="go_author"]')
        if author_tag: author = author_tag.get('title') or author_tag.text.strip()

        publisher = ""
        pub_tag = item.select_one('a[rel="go_publisher"]')
        if pub_tag: publisher = pub_tag.get('title') or pub_tag.text.strip()

        text = item.get_text()
        year, month = None, None
        match = re.search(r'(\d{4})/(\d{1,2})', text)
        if match: year, month = match.group(1), match.group(2)

        cover = ""
        img = item.select_one('img')
        if img: cover = img.get('data-src') or img.get('src') or ""
        
        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": ""}
    except Exception as e:
        print(f">>> [博客來] 錯誤: {e}")
        return None

# 3. 讀冊
def scrape_taaze(isbn):
    print(f">>> [讀冊] 開始查詢: {isbn}")
    url = f"https://www.taaze.tw/rwd_searchResult.html?keyType%5B%5D=0&keyword%5B%5D={isbn}"
    try:
        res = requests.get(url, headers=COMMON_HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        item = soup.select_one('.search_result_item')
        if not item: return None
        
        title_link = item.select_one('.book_title_link')
        if not title_link: return None
        title = title_link.text.strip()
        
        author = "未知"
        author_div = item.select_one('.book_author')
        if author_div: author = author_div.text.strip()

        publisher = ""
        pub_div = item.select_one('.book_publisher')
        if pub_div: publisher = pub_div.text.strip()

        year, month = None, None
        pub_date_div = item.select_one('.book_publish_date')
        if pub_date_div:
            match = re.search(r'(\d{4})-(\d{1,2})', pub_date_div.text)
            if match: year, month = match.group(1), match.group(2)

        cover = ""
        img = item.select_one('.book_img img')
        if img: cover = img.get('src') or ""
        
        return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": cover, "description": ""}
    except Exception as e:
        print(f">>> [讀冊] 錯誤: {e}")
        return None

# 4. 國圖 (NCL)
def scrape_ncl_isbn(isbn):
    print(f">>> [國圖] 開始查詢: {isbn}")
    clean_isbn = isbn.replace("-", "").strip()
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)
    session.headers.update({"Origin": "https://isbn.ncl.edu.tw", "Referer": "https://isbn.ncl.edu.tw/NEW_ISBNNet/H30_SearchBooks.php"})
    
    try:
        session.get("https://isbn.ncl.edu.tw/NEW_ISBNNet/", verify=False, timeout=10)
        payload = {"FO_SearchField0": "ISBN", "FO_SearchValue0": clean_isbn, "FO_Match": "1", "Pact": "DisplayAll4Simple", "FB_pageSID": "Simple", "FO_每頁筆數": "10", "FO_目前頁數": "1"}
        res = session.post("https://isbn.ncl.edu.tw/NEW_ISBNNet/H30_SearchBooks.php", data=payload, verify=False, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        
        rows = soup.select("tr")
        for row in rows:
            text = row.get_text()
            if clean_isbn in text:
                cols = row.find_all("td")
                if len(cols) >= 4:
                    raw_title = cols[2].get_text(strip=True)
                    title = raw_title.split("/")[0].strip() if "/" in raw_title else raw_title
                    author = raw_title.split("/")[1].strip() if "/" in raw_title else "未知"
                    publisher = cols[3].get_text(strip=True)
                    pub_raw = cols[4].get_text(strip=True) if len(cols)>4 else ""
                    year, month = None, None
                    match = re.search(r'(\d{4})/(\d{1,2})', pub_raw)
                    if match: year, month = match.group(1), match.group(2)
                    return {"success": True, "title": title, "author": author, "publisher": publisher, "year": year, "month": month, "cover_url": "", "description": "(來源:國圖)"}
        return None
    except Exception as e:
        print(f">>> [國圖] 錯誤: {e}")
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

# ====== 🔥 智慧查詢路由 (五大資料庫，金石堂優先) 🔥 ======
@app.route('/api/lookup_isbn/<isbn>', methods=['GET'])
def lookup_isbn(isbn):
    if not isbn: return jsonify({"error": "ISBN 碼不可為空"}), 400
    
    result_data = None
    
    # 1. Google Books (API)
    try:
        api_url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}&country=TW"
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('totalItems', 0) > 0:
                v = data['items'][0]['volumeInfo']
                pd = v.get('publishedDate', '')
                y = pd.split('-')[0] if pd else None
                m = pd.split('-')[1] if len(pd.split('-')) > 1 else None
                img = v.get('imageLinks', {})
                cover = img.get('large') or img.get('medium') or img.get('thumbnail')
                result_data = {"success": True, "title": v.get('title',''), "author": ", ".join(v.get('authors',['N/A'])), "publisher": v.get('publisher',''), "year": y, "month": m, "cover_url": cover, "description": v.get('description','')}
                print(">>> [Google] 命中")
    except: pass

    # 2. 金石堂 (Kingstone) - 台灣新書首選，反爬蟲較少
    if not result_data or not result_data.get('title'):
        ks_data = scrape_kingstone(isbn)
        if ks_data:
            result_data = ks_data
            print(">>> [金石堂] 命中")

    # 3. 博客來 (Books.com.tw)
    if not result_data or not result_data.get('title'):
        books_tw = scrape_books_com_tw(isbn)
        if books_tw:
            result_data = books_tw
            print(">>> [博客來] 命中")

    # 4. 讀冊 (TaaZe)
    if not result_data or not result_data.get('title'):
        taaze_data = scrape_taaze(isbn)
        if taaze_data:
            result_data = taaze_data
            print(">>> [讀冊] 命中")

    # 5. 國圖 (NCL) - 保底
    if not result_data or not result_data.get('title'):
        ncl_data = scrape_ncl_isbn(isbn)
        if ncl_data:
            result_data = ncl_data
            print(">>> [國圖] 命中")

    if result_data: return jsonify(result_data)
    else: return jsonify({"error": "找不到此 ISBN (五大資料庫皆無資料，可能因為國外IP被擋)"}), 404

if __name__ == '__main__':
    app.run(debug=True)
