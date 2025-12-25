import os
import io
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
import pandas as pd

app = Flask(__name__)
app.secret_key = "super_secret_key"

# --- 資料庫設定 ---
db_url = os.environ.get("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///books.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 資料庫模型 ---

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    # 建立關聯，當分類被查詢時，可以透過 .books 找到該分類下的書
    books = db.relationship('Book', backref='category', lazy=True)

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    publisher = db.Column(db.String(100))
    isbn = db.Column(db.String(20))
    
    # 分類改用 ID 關聯
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    
    status = db.Column(db.String(20), default='未讀')
    rating = db.Column(db.Integer, default=0)
    
    # 新增欄位
    print_version = db.Column(db.String(50)) # 版本：首刷/豪華首刷/再版
    
    publish_year = db.Column(db.Integer)
    publish_month = db.Column(db.Integer)
    location = db.Column(db.String(50))
    description = db.Column(db.Text)
    notes = db.Column(db.Text) # 備註
    cover_url = db.Column(db.String(500000)) # 支援 Base64 長字串
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# --- 初始化 ---
with app.app_context():
    # ★★★ 請確保這兩行前面是對齊的 (建議用 4 個空白鍵) ★★★
    db.drop_all()
    db.create_all()
    
    # 預設分類 (如果資料庫是空的)
    if not Category.query.first():
        cats = ['漫畫', '輕小說', '文學小說', '商業理財', '心理勵志', '人文社科', '工具書', '其他']
        for c in cats:
            db.session.add(Category(name=c))
        db.session.commit()

# --- 路由 ---

@app.route('/')
def index():
    query_str = request.args.get('q', '')
    search_type = request.args.get('search_type', 'all')
    selected_cats = request.args.getlist('category')
    selected_status = request.args.getlist('status')

    query = Book.query

    # 搜尋邏輯
    if query_str:
        search = f"%{query_str}%"
        if search_type == 'title': query = query.filter(Book.title.like(search))
        elif search_type == 'author': query = query.filter(Book.author.like(search))
        elif search_type == 'publisher': query = query.filter(Book.publisher.like(search))
        elif search_type == 'isbn': query = query.filter(Book.isbn.like(search))
        else:
            query = query.filter(
                (Book.title.like(search)) | 
                (Book.author.like(search)) |
                (Book.publisher.like(search)) |
                (Book.isbn.like(search))
            )
    
    # 篩選邏輯
    if selected_cats: query = query.filter(Book.category_id.in_(selected_cats))
    if selected_status: query = query.filter(Book.status.in_(selected_status))

    # 排序：狀態優先，再來是更新時間
    books = query.order_by(Book.status.asc(), Book.updated_at.desc()).all()
    categories = Category.query.all()
    
    return render_template('index.html', books=books, categories=categories, 
                           q=query_str, search_type=search_type,
                           selected_cats=selected_cats, selected_status=selected_status)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            cover_url = request.form.get('cover_url')
            cover_file = request.files.get('cover_file')
            if cover_file and cover_file.filename:
                img_data = cover_file.read()
                b64_data = base64.b64encode(img_data).decode('utf-8')
                mime_type = cover_file.content_type
                cover_url = f"data:{mime_type};base64,{b64_data}"

            new_book = Book(
                title=request.form.get('title'),
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                isbn=request.form.get('isbn'),
                category_id=request.form.get('category'),
                status=request.form.get('status'),
                print_version=request.form.get('print_version'),
                publish_year=request.form.get('year') or None,
                publish_month=request.form.get('month') or None,
                description=request.form.get('description'),
                notes=request.form.get('notes'),
                cover_url=cover_url
            )
            db.session.add(new_book)
            db.session.commit()
            return "OK", 200
        except Exception as e:
            print(e)
            return "Error", 500
    
    categories = Category.query.all()
    return render_template('add_book.html', categories=categories)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.publisher = request.form.get('publisher')
        book.isbn = request.form.get('isbn')
        book.status = request.form.get('status')
        book.category_id = request.form.get('category')
        book.print_version = request.form.get('print_version')
        book.rating = request.form.get('rating') or 0
        book.location = request.form.get('location')
        book.notes = request.form.get('notes')
        book.description = request.form.get('description')
        y = request.form.get('year')
        if y: book.publish_year = y

        new_url = request.form.get('cover_url')
        cover_file = request.files.get('cover_file')
        if cover_file and cover_file.filename:
            img_data = cover_file.read()
            b64_data = base64.b64encode(img_data).decode('utf-8')
            mime_type = cover_file.content_type
            book.cover_url = f"data:{mime_type};base64,{b64_data}"
        elif new_url:
            book.cover_url = new_url
        
        db.session.commit()
        return redirect(url_for('index'))
        
    categories = Category.query.all()
    return render_template('edit_book.html', book=book, categories=categories)

@app.route('/delete/<int:id>')
def delete_book(id):
    book = Book.query.get_or_404(id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('index'))

# --- 分類管理路由 ---

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            existing = Category.query.filter_by(name=name).first()
            if not existing:
                db.session.add(Category(name=name))
                db.session.commit()
        return redirect(url_for('manage_categories'))
    
    categories = Category.query.all()
    cat_stats = []
    for c in categories:
        count = Book.query.filter_by(category_id=c.id).count()
        cat_stats.append({'id': c.id, 'name': c.name, 'count': count})

    return render_template('categories.html', categories=cat_stats)

@app.route('/delete_category/<int:id>')
def delete_category(id):
    category = Category.query.get_or_404(id)
    # 安全刪除：將該分類下的書設為無分類 (None)
    books_in_cat = Book.query.filter_by(category_id=id).all()
    for book in books_in_cat:
        book.category_id = None
    
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('manage_categories'))

# --- 匯入匯出路由 ---

@app.route('/export')
def export_excel():
    books = Book.query.all()
    data = []
    for b in books:
        data.append({
            '書名': b.title, '作者': b.author, '出版社': b.publisher,
            'ISBN': b.isbn, '分類': b.category.name if b.category else '',
            '狀態': b.status, 
            '版本': b.print_version, 
            '出版年': b.publish_year, '位置': b.location,
            '簡介': b.description, '備註': b.notes, '評分': b.rating
        })
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='我的藏書')
    output.seek(0)
    return send_file(output, download_name="books_export.xlsx", as_attachment=True)

@app.route('/import', methods=['POST'])
def import_excel():
    file = request.files.get('file')
    if not file: return "No file", 400
    try:
        df = pd.read_excel(file)
        df = df.where(pd.notnull(df), None)
        for _, row in df.iterrows():
            if not row.get('書名'): continue
            
            # 處理分類 (自動新增不存在的分類)
            cat_name = row.get('分類')
            cat_id = None
            if cat_name:
                category = Category.query.filter_by(name=cat_name).first()
                if not category:
                    category = Category(name=cat_name)
                    db.session.add(category)
                    db.session.commit()
                cat_id = category.id

            new_book = Book(
                title=str(row['書名']),
                author=str(row['作者'] or '未知'),
                publisher=str(row.get('出版社')) if row.get('出版社') else None,
                isbn=str(row.get('ISBN')) if row.get('ISBN') else None,
                category_id=cat_id,
                status=str(row.get('狀態', '未讀')),
                print_version=str(row.get('版本')) if row.get('版本') else None,
                publish_year=int(row.get('出版年')) if row.get('出版年') else None,
                location=str(row.get('位置')) if row.get('位置') else None,
                description=str(row.get('簡介')) if row.get('簡介') else None,
                notes=str(row.get('備註') or row.get('筆記')) if (row.get('備註') or row.get('筆記')) else None,
                rating=int(row.get('評分')) if row.get('評分') else 0
            )
            db.session.add(new_book)
        db.session.commit()
        return redirect(url_for('index'))
    except Exception as e:
        return f"匯入失敗: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)
