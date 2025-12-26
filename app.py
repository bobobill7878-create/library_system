import os
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime
from bs4 import BeautifulSoup
import re

app = Flask(__name__)

# --- 設定上傳資料夾 ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///books.db').replace("postgres://", "postgresql://", 1)
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
    rating = db.Column(db.Integer, default=0)
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
    
    # 增加一個方法方便轉成 JSON
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'author': self.author,
            'publisher': self.publisher,
            'isbn': self.isbn,
            'status': self.status,
            'rating': self.rating,
            'series': self.series,
            'volume': self.volume,
            'publish_year': self.publish_year,
            'publish_month': self.publish_month,
            'location': self.location,
            'tags': self.tags,
            'description': self.description,
            'notes': self.notes,
            'cover_url': self.cover_url
        }

with app.app_context():
    db.create_all()
    if not Category.query.first():
        cats = ['漫畫', '輕小說', '文學小說', '商業理財', '心理勵志', '人文社科', '工具書', '其他']
        for c in cats: db.session.add(Category(name=c))
        db.session.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- API 路由 ---
@app.route('/api/book/<int:id>')
def get_book_api(id):
    book = Book.query.get_or_404(id)
    return jsonify(book.to_dict())

@app.route('/api/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    # (同之前的代碼，省略以節省空間，請保留您原本的邏輯)
    return jsonify({'error': 'Not found'}), 404

# --- 頁面路由 ---
@app.route('/')
def index():
    query = Book.query
    
    # 接收前端的參數
    search_field = request.args.get('search_field', 'all')
    q = request.args.get('query', '')
    cat_id = request.args.get('category_id')
    status = request.args.get('status_filter')

    # 搜尋邏輯
    if q:
        if search_field == 'title':
            query = query.filter(Book.title.contains(q))
        elif search_field == 'author':
            query = query.filter(Book.author.contains(q))
        elif search_field == 'series':
            query = query.filter(Book.series.contains(q))
        else: # all
            query = query.filter((Book.title.contains(q)) | (Book.author.contains(q)) | (Book.isbn.contains(q)) | (Book.series.contains(q)))
    
    if cat_id:
        query = query.filter(Book.category_id == cat_id)
    
    if status:
        query = query.filter(Book.status == status)

    books = query.order_by(Book.updated_at.desc()).all()
    categories = Category.query.all()
    
    return render_template('index.html', 
                           books=books, 
                           categories=categories,
                           current_query=q,
                           current_search_field=search_field,
                           current_category_id=cat_id,
                           current_status=status)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            cat_id = request.form.get('category_id')
            cover_url = request.form.get('cover_url')
            file = request.files.get('cover_file')
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
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

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        book.title = request.form['title']
        book.author = request.form.get('author')
        book.status = request.form.get('status')
        book.rating = request.form.get('rating')
        # ... 其他欄位更新邏輯與 add_book 類似 ...
        
        # 簡單處理：
        book.description = request.form.get('description')
        book.notes = request.form.get('notes')
        
        db.session.commit()
        return redirect(url_for('index'))
    
    categories = Category.query.all()
    return render_template('edit_book.html', book=book, categories=categories)

@app.route('/delete_book/<int:id>', methods=['GET', 'POST'])
def delete_book(id):
    book = Book.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/categories')
def manage_categories():
    return "分類管理頁面 (建置中) <a href='/'>回首頁</a>"

# --- 新增的佔位路由 (防止 HTML 報錯) ---
@app.route('/dashboard')
def dashboard():
    return "數據儀表板 (建置中) <a href='/'>回首頁</a>"

@app.route('/export')
def export_csv():
    return "匯出功能 (建置中) <a href='/'>回首頁</a>"

@app.route('/import')
def import_books():
    return "匯入功能 (建置中) <a href='/'>回首頁</a>"

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
