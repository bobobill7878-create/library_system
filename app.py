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
# 引入 BeautifulSoup 用於爬取博客來資料
from bs4 import BeautifulSoup

# 應用程式設定
app = Flask(__name__)

# --- 資料庫設定 (雲端與本地兼容) ---
# 優先讀取 Render 環境變數 DATABASE_URL，如果沒有則使用本地 SQLite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///library.db')

# 修正部分雲端資料庫網址開頭為 postgres:// 的問題 (SQLAlchemy 需要 postgresql://)
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# --------------------------------

# --- 檔案上傳相關設定 ---
# 注意：Render 免費版重啟後，此資料夾內的圖片會消失
UPLOAD_FOLDER = 'static/covers'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
# -------------------------

db = SQLAlchemy(app)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- 📗 資料庫模型：分類 (Category) ---
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    books = db.relationship('Book', backref='category', lazy=True)
    
    def __repr__(self):
        return f'<Category {self.name}>'

# --- 📚 資料庫模型：圖書 (Book) V2.0 ---
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

    # ****** V2.0 新增欄位 ******
    series = db.Column(db.String(100), nullable=True)  # 叢書名
    volume = db.Column(db.String(20), nullable=True)   # 集數
    location = db.Column(db.String(100), nullable=True) # 存放位置
    status = db.Column(db.String(20), default='未讀')   # 閱讀狀態
    rating = db.Column(db.Integer, default=0)          # 評分
    tags = db.Column(db.String(200), nullable=True)    # 標籤
    # ***************************

    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)

    def __repr__(self):
        return f'<Book {self.title}>'


# ====== 🛠️ 工具函式：博客來爬蟲 ======
def scrape_books_com_tw(isbn):
    """
    透過爬蟲抓取博客來書籍資料
    """
    print(f">>> [爬蟲] 正在查詢博客來 ISBN: {isbn}")
    url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 博客來搜尋結果通常在 .table-search-tbody .table-td 或是新的結構
        results = soup.select('.table-search-tbody .table-td')
        
        if not results:
            print(">>> [爬蟲] 博客來未找到搜尋結果")
            return None

        # 抓取第一筆結果
        first_item = results[0] 
        
        # 1. 書名
        title_tag = first_item.select_one('h4 a')
        if not title_tag: return None
        title = title_tag.get('title') or title_tag.text.strip()
        
        # 詳情頁連結 (用於抓大綱)
        detail_url = title_tag.get('href')
        if detail_url and detail_url.startswith("//"):
            detail_url = "https:" + detail_url

        # 2. 作者
        author_tag = first_item.select_one('a[rel="go_author"]')
        author = author_tag.get('title') if author_tag else "未知作者"

        # 3. 出版社
        publisher_tag = first_item.select_one('a[rel="go_publisher"]')
        publisher = publisher_tag.get('title') if publisher_tag else ""

        # 4. 出版日期 (從列表文字中解析：出版日期：2023/10/01)
        text_content = first_item.get_text()
        year = None
        month = None
        date_match = re.search(r'出版日期：(\d{4})/(\d{1,2})', text_content)
        if date_match:
            year = date_match.group(1)
            month = date_match.group(2)
        
        # 5. 封面圖片
        img_tag = first_item.select_one('img')
        cover_url = ""
        if img_tag:
            # 博客來通常使用 data-src 進行懶加載，沒有的話用 src
            cover_url = img_tag.get('data-src') or img_tag.get('src')
        
        # 6. 進入詳情頁抓大綱
        description = ""
        if detail_url:
            try:
                detail_res = requests.get(detail_url, headers=headers, timeout=5)
                detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                # 博客來大綱通常在 div.content
                desc_div = detail_soup.select_one('div.content')
                if desc_div:
                    description = desc_div.get_text(strip=True)
            except Exception as e:
                print(f">>> [爬蟲] 抓取詳情頁大綱失敗: {e}")

        return {
            "success": True,
            "title": title,
            "author": author,
            "publisher": publisher,
            "year": year,
            "month": month,
            "cover_url": cover_url,
            "description": description
        }

    except Exception as e:
        print(f">>> [爬蟲] 發生錯誤: {e}")
        return None
# ========================================


# --- 路由：手動初始化資料庫 (解決 Render 500 Error) ---
@app.route('/init_db')
def init_db():
    try:
        db.create_all()
        # 初始化預設分類
        if not Category.query.first():
            default_categories = ['小說','原文小說', '漫畫', '原文漫畫', '畫冊', '寫真', '設定集']
            for name in default_categories:
                db.session.add(Category(name=name))
            db.session.commit()
            return "<h3>初始化成功！</h3><p>資料庫表格已建立，預設分類已新增。請點擊 <a href='/'>這裡</a> 返回首頁。</p>"
        else:
            return "<h3>資料庫已存在</h3><p>無需重複初始化。請點擊 <a href='/'>這裡</a> 返回首頁。</p>"
    except Exception as e:
        return f"<h3>初始化失敗</h3><p>錯誤訊息: {e}</p>"


# --- 路由 1: 主頁面 ---
@app.route('/')
def index():
    try:
        search_field = request.args.get('search_field', 'all') 
        query = request.args.get('query', '').strip()  
        category_id = request.args.get('category_id') 
        status_filter = request.args.get('status_filter')

        books_query = Book.query

        if query:
            base_filter = Book.title.ilike(f'%{query}%') | \
                          Book.author.ilike(f'%{query}%') | \
                          Book.publisher.ilike(f'%{query}%') | \
                          Book.series.ilike(f'%{query}%') | \
                          Book.tags.ilike(f'%{query}%')

            if search_field == 'title':
                search_filter = Book.title.ilike(f'%{query}%')
            elif search_field == 'author':
                search_filter = Book.author.ilike(f'%{query}%')
            elif search_field == 'publisher':
                search_filter = Book.publisher.ilike(f'%{query}%')
            elif search_field == 'series':
                search_filter = Book.series.ilike(f'%{query}%')
            else: 
                search_filter = base_filter
            
            books_query = books_query.filter(search_filter)

        if category_id and category_id.isdigit():
            books_query = books_query.filter(Book.category_id == int(category_id))

        if status_filter:
            books_query = books_query.filter(Book.status == status_filter)

        all_books = books_query.order_by(Book.series.desc(), Book.volume.asc(), Book.id.desc()).all()
        all_categories = Category.query.all()
        
        return render_template('index.html', 
                               books=all_books, 
                               categories=all_categories,
                               current_query=query,          
                               current_category_id=category_id,
                               current_search_field=search_field,
                               current_status=status_filter
                              )
    except Exception as e:
        # 如果資料庫尚未初始化，引導使用者去初始化
        return f"<h1>系統未就緒</h1><p>請點擊 <a href='/init_db'>這裡初始化資料庫</a></p><p>錯誤訊息: {e}</p>"

# --- 路由 2: 新增圖書 ---
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
            cover_url=cover_url,
            description=description, print_version=print_version, notes=notes,
            series=series, volume=volume, location=location,
            status=status, rating=int(rating) if rating else 0, tags=tags
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

# --- 路由 3: 編輯圖書 ---
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
        except:
            return '更新圖書時發生錯誤', 500
    
    all_categories = Category.query.all()
    return render_template('edit_book.html', book=book, categories=all_categories)

# --- 路由 4: 刪除圖書 ---
@app.route('/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    book_to_delete = Book.query.get_or_404(book_id)
    try:
        db.session.delete(book_to_delete)
        db.session.commit()
        return redirect(url_for('index'))
    except:
        return '刪除圖書時發生錯誤', 500

# --- 路由 5: ISBN 雙重查詢 (Google + 博客來) ---
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
            if data.get('totalItems', 0) > 0 and 'items' in data:
                volume_info = data['items'][0]['volumeInfo']
                published_date = volume_info.get('publishedDate', '')
                year = published_date.split('-')[0] if published_date else None
                month = published_date.split('-')[1] if len(published_date.split('-')) > 1 else None
                image_links = volume_info.get('imageLinks', {})
                cover_url = image_links.get('large') or image_links.get('medium') or image_links.get('thumbnail')
                
                result_data = {
                    "success": True,
                    "title": volume_info.get('title', ''),
                    "author": ", ".join(volume_info.get('authors', ['N/A'])), 
                    "publisher": volume_info.get('publisher', ''),
                    "year": year, "month": month, "cover_url": cover_url,
                    "description": volume_info.get('description', '')
                }
    except Exception as e:
        print(f"Google API Error: {e}")

    # 2. 如果 Google 失敗或沒標題，嘗試博客來
    if not result_data or not result_data.get('title'):
        books_tw_data = scrape_books_com_tw(isbn)
        if books_tw_data:
            result_data = books_tw_data

    if result_data:
        return jsonify(result_data)
    else:
        return jsonify({"error": "找不到此 ISBN (Google 與博客來皆無資料)"}), 404

# --- 路由 6: 分類管理 ---
@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('category_name').strip()
        if name:
            if Category.query.filter_by(name=name).first():
                error = f"分類 '{name}' 已存在。"
            else:
                db.session.add(Category(name=name))
                db.session.commit()
                return redirect(url_for('manage_categories'))
        else:
            error = "名稱不可為空。"
        return render_template('manage_categories.html', categories=Category.query.all(), error=error)
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
    if not new_name: return jsonify({"success": False, "message": "名稱不可為空"}), 400
    if new_name != cat.name and Category.query.filter_by(name=new_name).first():
        return jsonify({"success": False, "message": "名稱已存在"}), 409
    cat.name = new_name
    db.session.commit()
    return jsonify({"success": True, "message": "更新成功", "new_name": new_name})

# --- 路由 9: 單本書籍 API ---
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
        'location': book.location or '', 'status': book.status,
        'rating': book.rating, 'tags': book.tags or ''
    })

# --- 路由 10: 數據儀表板 ---
@app.route('/dashboard')
def dashboard():
    total_books = Book.query.count()
    cat_stats = db.session.query(Category.name, func.count(Book.id)).join(Book).group_by(Category.name).all()
    status_stats = db.session.query(Book.status, func.count(Book.id)).group_by(Book.status).all()
    rating_stats = db.session.query(Book.rating, func.count(Book.id)).group_by(Book.rating).all()
    return render_template('dashboard.html', total=total_books, cat_stats=dict(cat_stats), status_stats=dict(status_stats), rating_stats=dict(rating_stats))

# --- 路由 11: 匯出 CSV (修正亂碼版) ---
@app.route('/export')
def export_csv():
    books = Book.query.all()
    output = io.StringIO()
    # 寫入 BOM 以修正 Excel 中文亂碼
    output.write('\ufeff') 
    writer = csv.writer(output)
    writer.writerow(['ID', '書名', '作者', '出版社', 'ISBN', '分類', '叢書', '集數', '狀態', '評分', '位置', '加入日期'])
    for book in books:
        cat_name = book.category.name if book.category else '無分類'
        writer.writerow([
            book.id, book.title, book.author, book.publisher, 
            f"'{book.isbn}" if book.isbn else '', 
            cat_name, book.series, book.volume, book.status, book.rating, book.location, book.added_date
        ])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=library_backup.csv"})

if __name__ == '__main__':
    app.run(debug=True)
