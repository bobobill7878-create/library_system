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

# 應用程式設定
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


# ====== 🕷️ 爬蟲 1：博客來 (Books.com.tw) ======
def scrape_books_com_tw(isbn):
    print(f">>> [爬蟲] 查詢博客來 ISBN: {isbn}")
    url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        results = soup.select('.table-search-tbody .table-td')
        if not results: return None

        first_item = results[0] 
        title_tag = first_item.select_one('h4 a')
        if not title_tag: return None
        title = title_tag.get('title') or title_tag.text.strip()
        detail_url = title_tag.get('href')
        if detail_url and detail_url.startswith("//"): detail_url = "https:" + detail_url

        author_tag = first_item.select_one('a[rel="go_author"]')
        author = author_tag.get('title') if author_tag else "未知作者"
        publisher_tag = first_item.select_one('a[rel="go_publisher"]')
        publisher = publisher_tag.get('title') if publisher_tag else ""

        text_content = first_item.get_text()
        year, month = None, None
        date_match = re.search(r'出版日期：(\d{4})/(\d{1,2})', text_content)
        if date_match:
            year, month = date_match.group(1), date_match.group(2)
        
        img_tag = first_item.select_one('img')
        cover_url = ""
        if img_tag: cover_url = img_tag.get('data-src') or img_tag.get('src')
        
        description = ""
        if detail_url:
            try:
                detail_res = requests.get(detail_url, headers=headers, timeout=5)
                detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                desc_div = detail_soup.select_one('div.content')
                if desc_div: description = desc_div.get_text(strip=True)
            except: pass

        return {
            "success": True, "title": title, "author": author, "publisher": publisher,
            "year": year, "month": month, "cover_url": cover_url, "description": description
        }
    except Exception as e:
        print(f">>> [爬蟲] 博客來錯誤: {e}")
        return None

# ====== 🕷️ 爬蟲 2：國家圖書館 (NCL ISBN Net) - 強力修正版 ======
def scrape_ncl_isbn(isbn):
    # 清理 ISBN，移除可能的連字號，國圖有時候對連字號敏感
    clean_isbn = isbn.replace("-", "").strip()
    print(f">>> [爬蟲] 查詢國圖 ISBN: {clean_isbn}")
    
    session = requests.Session()
    
    # 偽裝成真正的 Chrome 瀏覽器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Origin": "https://isbn.ncl.edu.tw",
        "Referer": "https://isbn.ncl.edu.tw/NEW_ISBNNet/H30_SearchBooks.php",
        "Upgrade-Insecure-Requests": "1"
    }
    session.headers.update(headers)
    
    try:
        # 步驟 1: 訪問首頁，取得 PHPSESSID
        # 加上 verify=False 忽略 SSL 憑證錯誤 (國圖憑證有時候會有問題)
        # 加上 requests.packages.urllib3.disable_warnings() 避免跳出警告
        requests.packages.urllib3.disable_warnings()
        
        base_url = "https://isbn.ncl.edu.tw/NEW_ISBNNet/"
        print(">>> [爬蟲] 1. 連線至首頁取得 Cookie...")
        session.get(base_url, verify=False, timeout=10)
        
        # 步驟 2: 模擬送出搜尋表單
        search_url = "https://isbn.ncl.edu.tw/NEW_ISBNNet/H30_SearchBooks.php"
        
        # 這是國圖搜尋表單的標準 Payload
        payload = {
            "FO_SearchField0": "ISBN",
            "FO_SearchValue0": clean_isbn,
            "FO_Match": "1", # 1:精確, 2:包含 (改成1試試看)
            "FB_search": "查詢", # 模擬按鈕點擊
            "Pact": "DisplayAll4Simple",
            "FB_pageSID": "Simple",
            "FO_每頁筆數": "10",
            "FO_目前頁數": "1"
        }
        
        print(">>> [爬蟲] 2. 發送搜尋請求...")
        res = session.post(search_url, data=payload, verify=False, timeout=15)
        
        # 修正編碼：國圖有時候不會在 Header 說它是 utf-8，導致 Python 用 ISO-8859-1 解碼變亂碼
        res.encoding = 'utf-8' 
        
        # 步驟 3: 解析 HTML
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 檢查是否搜尋到結果
        # 國圖的結果通常在一個 ID 為 "table_list" 或 class "table-searchbooks" 的表格中
        # 或是直接找有沒有包含 "詳" 的連結
        
        # 策略 A: 先看有沒有直接進入詳情頁 (有時候只有一筆結果會直接跳轉?)
        # 策略 B: 找列表
        
        results = soup.select("tr") # 抓所有列
        target_data = None
        
        print(f">>> [爬蟲] 3. 解析頁面，找到 {len(results)} 行資料")

        for row in results:
            text = row.get_text()
            # 簡單過濾：這行要有 ISBN 且要有 書名
            if clean_isbn in text:
                cols = row.find_all("td")
                # 國圖列表通常欄位：序號 | ISBN | 書名/作者 | 出版者 | ...
                # 對應 index: 0 | 1 | 2 | 3
                if len(cols) >= 4:
                    print(">>> [爬蟲] 找到疑似目標的資料列")
                    
                    # 抓取 書名/作者 (第3欄, index 2)
                    title_author = cols[2].get_text(strip=True)
                    if "/" in title_author:
                        title = title_author.split("/")[0].strip()
                        author = title_author.split("/")[1].strip()
                    else:
                        title = title_author
                        author = "未知作者"
                    
                    # 抓取 出版社 (第4欄, index 3)
                    publisher = cols[3].get_text(strip=True)
                    
                    # 抓取 出版日期 (第5欄, index 4)
                    pub_date = ""
                    if len(cols) > 4:
                        pub_date = cols[4].get_text(strip=True)
                    
                    year = None
                    month = None
                    # 解析日期 YYYY/MM
                    match = re.search(r'(\d{4})/(\d{1,2})', pub_date)
                    if match:
                        year = match.group(1)
                        month = match.group(2)
                    
                    target_data = {
                        "success": True,
                        "title": title,
                        "author": author,
                        "publisher": publisher,
                        "year": year,
                        "month": month,
                        "cover_url": "",
                        "description": "(資料來源：國家圖書館)"
                    }
                    break # 找到就跳出
        
        if target_data:
            print(f">>> [爬蟲] 成功解析: {target_data['title']}")
            return target_data
        else:
            # 如果還是找不到，把 HTML 存下來除錯 (在本地測試時有用)
            # print(soup.prettify()) 
            print(">>> [爬蟲] 解析失敗，HTML 中未發現目標表格")
            return None

    except Exception as e:
        print(f">>> [爬蟲] 發生例外錯誤: {e}")
        return None

# ========================================

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

# ====== 🔥 智慧查詢路由 (三段式查詢) 🔥 ======
@app.route('/api/lookup_isbn/<isbn>', methods=['GET'])
def lookup_isbn(isbn):
    if not isbn: return jsonify({"error": "ISBN 碼不可為空"}), 400
    
    result_data = None
    
    # 1. 嘗試 Google API
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
                print(">>> Google API 命中")
    except: pass

    # 2. 如果 Google 失敗，嘗試博客來
    if not result_data or not result_data.get('title'):
        books_tw = scrape_books_com_tw(isbn)
        if books_tw:
            result_data = books_tw
            print(">>> 博客來命中")

    # 3. 如果博客來也失敗，嘗試國圖 (NCL)
    if not result_data or not result_data.get('title'):
        ncl_data = scrape_ncl_isbn(isbn)
        if ncl_data:
            result_data = ncl_data
            print(">>> 國圖 (NCL) 命中")

    if result_data: return jsonify(result_data)
    else: return jsonify({"error": "找不到此 ISBN (Google/博客來/國圖皆無資料)"}), 404

if __name__ == '__main__':
    app.run(debug=True)


