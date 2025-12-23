import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- 設定 ---
# 資料庫連線 (Render 會自動填入 DATABASE_URL)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 設定圖片上傳路徑
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(os.path.join(app.root_path, UPLOAD_FOLDER), exist_ok=True)

db = SQLAlchemy(app)

# --- 資料庫模型 ---
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    publisher = db.Column(db.String(100))
    isbn = db.Column(db.String(20))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    category = db.relationship('Category', backref='books')
    status = db.Column(db.String(20), default='未讀')
    rating = db.Column(db.Integer, default=0)
    series = db.Column(db.String(100))
    volume = db.Column(db.String(20))
    print_version = db.Column(db.String(50))
    publish_year = db.Column(db.Integer)
    publish_month = db.Column(db.Integer)
    location = db.Column(db.String(100))
    tags = db.Column(db.String(200))
    description = db.Column(db.Text)
    notes = db.Column(db.Text)
    cover_url = db.Column(db.String(500)) # 儲存網址或檔案路徑
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())

# --- 初始化 ---
with app.app_context():
    db.create_all()
    if not Category.query.first():
        cats = ['漫畫', '輕小說', '文學小說', '商業理財', '心理勵志', '人文社科', '其他']
        for c in cats:
            db.session.add(Category(name=c))
        db.session.commit()

# --- 路由 ---

@app.route('/')
def index():
    q = request.args.get('q', '')
    selected_cats = request.args.getlist('category') 
    selected_status = request.args.getlist('status')

    query = Book.query

    # 關鍵字搜尋
    if q:
        query = query.filter(
            (Book.title.ilike(f'%{q}%')) | 
            (Book.author.ilike(f'%{q}%')) |
            (Book.isbn.ilike(f'%{q}%'))
        )

    # Checkbox 多選過濾
    if selected_cats:
        query = query.filter(Book.category_id.in_(selected_cats))
    if selected_status:
        query = query.filter(Book.status.in_(selected_status))

    books = query.order_by(Book.status.asc(), Book.updated_at.desc()).all()
    categories = Category.query.all()
    
    return render_template('index.html', books=books, categories=categories, 
                           q=q, selected_cats=selected_cats, selected_status=selected_status)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            cover_url = request.form.get('cover_url')
            
            # 處理檔案上傳
            if 'cover_file' in request.files:
                file = request.files['cover_file']
                if file and file.filename != '':
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                    cover_url = url_for('static', filename=f'uploads/{filename}')

            new_book = Book(
                isbn=request.form.get('isbn'),
                title=request.form.get('title'),
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                category_id=request.form.get('category'),
                series=request.form.get('series'),
                volume=request.form.get('volume'),
                print_version=request.form.get('print_version'),
                publish_year=request.form.get('year') or None,
                publish_month=request.form.get('month') or None,
                status=request.form.get('status'),
                rating=request.form.get('rating') or 0,
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
            categories = Category.query.all()
            return render_template('add_book.html', categories=categories, error=str(e))

    categories = Category.query.all()
    return render_template('add_book.html', categories=categories)

# ★★★ 這裡修正了：使用 <int:id> 而不是 <int:book_id> ★★★
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        new_cover_url = request.form.get('cover_url')
        
        # 優先處理上傳檔案
        if 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                book.cover_url = url_for('static', filename=f'uploads/{filename}')
            elif new_cover_url:
                book.cover_url = new_cover_url
        elif new_cover_url:
             book.cover_url = new_cover_url

        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.isbn = request.form.get('isbn')
        book.publisher = request.form.get('publisher')
        book.category_id = request.form.get('category')
        book.series = request.form.get('series')
        book.volume = request.form.get('volume')
        book.print_version = request.form.get('print_version')
        book.publish_year = request.form.get('year') or None
        book.publish_month = request.form.get('month') or None
        book.status = request.form.get('status')
        book.rating = request.form.get('rating') or 0
        book.location = request.form.get('location')
        book.tags = request.form.get('tags')
        book.description = request.form.get('description')
        book.notes = request.form.get('notes')
        
        db.session.commit()
        return redirect(url_for('index'))
        
    categories = Category.query.all()
    return render_template('edit_book.html', book=book, categories=categories)

# ★★★ 這裡也確認使用 <int:id> ★★★
@app.route('/delete/<int:id>')
def delete_book(id):
    book = Book.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/api/lookup_isbn/<isbn>')
def api_lookup(isbn):
    return jsonify({"error": "Backend lookup skipped, use frontend"}), 404

if __name__ == '__main__':
    app.run(debug=True)
