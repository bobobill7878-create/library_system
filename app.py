import os
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
from bs4 import BeautifulSoup

app = Flask(__name__)

# --- 設定上傳資料夾 ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if 'RENDER' in os.environ:
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///books.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 資料模型 ---
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    books = db.relationship('Book', backref='category_ref', lazy=True)

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100))
    publisher = db.Column(db.String(100))
    isbn = db.Column(db.String(20))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    status = db.Column(db.String(20), default='未讀')
    rating = db.Column(db.Integer)
    series = db.Column(db.String(100))
    volume = db.Column(db.String(20))
    print_version = db.Column(db.String(20))
    publish_year = db.Column(db.Integer)
    publish_month = db.Column(db.Integer)
    location = db.Column(db.String(50))
    tags = db.Column(db.String(200))
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    cover_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

with app.app_context():
    db.create_all()
    if not Category.query.first():
        cats = ['漫畫', '輕小說', '文學小說', '商業理財', '心理勵志', '人文社科', '工具書', '其他']
        for c in cats: db.session.add(Category(name=c))
        db.session.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- API: ISBN 查詢 ---
@app.route('/api/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
        res = requests.get(url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            item = soup.select_one('.table-search-tbody tr') or soup.select_one('.item')
            if item:
                data = {}
                img = item.select_one('img')
                if img: data['cover_url'] = (img.get('data-original') or img.get('src') or '').split('?')[0]
                
                title = item.select_one('h3 a, h4 a')
                if title: data['title'] = title.get('title') or title.text.strip()
                
                author = item.select_one('a[rel="go_author"]')
                if author: data['author'] = author.text.strip()
                
                pub = item.select_one('a[rel="mid_publish"]')
                if pub: data['publisher'] = pub.text.strip()
                
                import re
                m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', item.text)
                if m:
                    data['year'] = m.group(1)
                    data['month'] = m.group(2)
                
                desc = item.select_one('.box_contents p, .txt_cont')
                if desc: data['description'] = desc.text.strip()[:300] + "..."
                return jsonify(data)
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- API: 關鍵字搜尋 (新增，支援前端 searchByTitle) ---
@app.route('/api/search_keyword/<keyword>')
def search_keyword(keyword):
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q={keyword}&maxResults=10"
        res = requests.get(url)
        data = res.json()
        results = []
        if 'items' in data:
            for item in data['items']:
                v = item.get('volumeInfo', {})
                isbn = ""
                if 'industryIdentifiers' in v:
                    for i in v['industryIdentifiers']:
                        if i['type'] == 'ISBN_13': isbn = i['identifier']
                
                img = v.get('imageLinks', {}).get('thumbnail', '')
                if img: img = img.replace('http:', 'https:')

                results.append({
                    'title': v.get('title', '無標題'),
                    'author': ', '.join(v.get('authors', [])),
                    'publisher': v.get('publisher', ''),
                    'year': v.get('publishedDate', '')[:4] if v.get('publishedDate') else '',
                    'cover_url': img,
                    'description': v.get('description', ''),
                    'isbn': isbn
                })
        return jsonify(results)
    except Exception as e:
        return jsonify([])

# --- 頁面路由 ---
@app.route('/')
def index():
    query = Book.query
    q = request.args.get('q')
    if q:
        query = query.filter((Book.title.contains(q)) | (Book.author.contains(q)) | (Book.isbn.contains(q)))
    
    cat_id = request.args.get('category')
    if cat_id: query = query.filter(Book.category_id == cat_id)

    books = query.order_by(Book.status.asc(), Book.updated_at.desc()).all()
    categories = Category.query.all()
    return render_template('index.html', books=books, categories=categories)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            # 處理分類
            cat_id = request.form.get('category_id')
            
            # 處理圖片上傳
            cover_url = request.form.get('cover_url')
            file = request.files.get('cover_file')
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # 加上時間戳記避免檔名衝突
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                cover_url = url_for('static', filename='uploads/' + filename)

            y = request.form.get('publish_year')
            m = request.form.get('publish_month')
            
            new_book = Book(
                title=request.form['title'],
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                isbn=request.form.get('isbn'),
                category_id=cat_id if cat_id else None,
                status=request.form.get('status', '未讀'),
                rating=request.form.get('rating'),
                series=request.form.get('series'),
                volume=request.form.get('volume'),
                print_version=request.form.get('print_version'),
                publish_year=int(y) if y and y.isdigit() else None,
                publish_month=int(m) if m and m.isdigit() else None,
                location=request.form.get('location'),
                tags=request.form.get('tags'),
                description=request.form.get('description'),
                notes=request.form.get('notes'),
                cover_url=cover_url
            )
            db.session.add(new_book)
            db.session.commit()
            return redirect(url_for('index'))
        except Exception as e:
            return f"Error: {e}", 500

    categories = Category.query.all()
    return render_template('add_book.html', categories=categories)

@app.route('/delete_book/<int:id>', methods=['POST'])
def delete_book(id):
    book = Book.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('name')
        if name and not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
            db.session.commit()
    return render_template('categories.html', categories=Category.query.all())

@app.route('/categories/delete/<int:id>', methods=['POST'])
def delete_category(id):
    cat = Category.query.get_or_404(id)
    if not Book.query.filter_by(category_id=id).first():
        db.session.delete(cat)
        db.session.commit()
    return redirect(url_for('manage_categories'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
