import os
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from flask_sqlalchemy import SQLAlchemy
import requests
import pandas as pd  # 新增這個

app = Flask(__name__)
app.secret_key = "super_secret_key" # 用於 Flash 訊息

# 設定資料庫
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
    books = db.relationship('Book', backref='category', lazy=True)

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
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

# --- 初始化 ---
with app.app_context():
    # 注意：如果資料庫結構有變，請先執行 db.drop_all() 再 db.create_all()
    # db.drop_all() 
    db.create_all()
    
    if not Category.query.first():
        cats = ['漫畫', '輕小說', '文學小說', '商業理財', '心理勵志', '人文社科', '其他']
        for c in cats:
            db.session.add(Category(name=c))
        db.session.commit()

# --- 路由 ---
@app.route('/')
def index():
    query_str = request.args.get('q', '')
    selected_cats = request.args.getlist('category')
    selected_status = request.args.getlist('status')

    query = Book.query

    if query_str:
        search = f"%{query_str}%"
        query = query.filter(
            (Book.title.like(search)) | 
            (Book.author.like(search)) |
            (Book.isbn.like(search))
        )
    
    if selected_cats:
        query = query.filter(Book.category_id.in_(selected_cats))
    
    if selected_status:
        query = query.filter(Book.status.in_(selected_status))

    books = query.order_by(Book.status.asc(), Book.updated_at.desc()).all()
    categories = Category.query.all()
    
    return render_template('index.html', books=books, categories=categories, 
                           q=query_str, selected_cats=selected_cats, selected_status=selected_status)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        # 處理圖片上傳 (這裡為了簡化，如果使用者有上傳檔案，我們轉成 Data URL 存入資料庫)
        # 實際專案建議上傳到雲端儲存空間
        import base64
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
            publish_year=request.form.get('year') or None,
            publish_month=request.form.get('month') or None,
            description=request.form.get('description'),
            notes=request.form.get('notes'),
            cover_url=cover_url
        )
        db.session.add(new_book)
        db.session.commit()
        return "OK", 200 # AJAX 成功回應
    
    categories = Category.query.all()
    return render_template('add_book.html', categories=categories)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.publisher = request.form.get('publisher')
        book.status = request.form.get('status')
        book.category_id = request.form.get('category')
        book.rating = request.form.get('rating')
        book.location = request.form.get('location')
        book.notes = request.form.get('notes')
        
        # 簡單處理年份更新
        y = request.form.get('year')
        if y: book.publish_year = y
        
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

# --- 新增：匯出 Excel ---
@app.route('/export')
def export_excel():
    books = Book.query.all()
    
    # 將資料庫物件轉為字典列表，並使用中文欄位名稱
    data = []
    for b in books:
        data.append({
            '書名': b.title,
            '作者': b.author,
            '出版社': b.publisher,
            'ISBN': b.isbn,
            '分類': b.category.name if b.category else '',
            '狀態': b.status,
            '出版年': b.publish_year,
            '簡介': b.description,
            '筆記': b.notes,
            '位置': b.location,
            '評分': b.rating
        })
    
    df = pd.DataFrame(data)
    
    # 建立一個記憶體內的 Excel 檔案
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='我的藏書')
    
    output.seek(0)
    return send_file(output, download_name="books_export.xlsx", as_attachment=True)

# --- 新增：匯入 Excel ---
@app.route('/import', methods=['POST'])
def import_excel():
    file = request.files.get('file')
    if not file:
        return "No file uploaded", 400

    try:
        df = pd.read_excel(file)
        
        # 確保必要的欄位存在
        if '書名' not in df.columns or '作者' not in df.columns:
            return "Excel 格式錯誤：缺少「書名」或「作者」欄位", 400

        # 將 NaN (空值) 轉為 None
        df = df.where(pd.notnull(df), None)

        for _, row in df.iterrows():
            # 處理分類 (如果 Excel 裡的分類資料庫沒有，自動新增)
            cat_name = row.get('分類')
            cat_id = None
            if cat_name:
                category = Category.query.filter_by(name=cat_name).first()
                if not category:
                    category = Category(name=cat_name)
                    db.session.add(category)
                    db.session.commit() # 需要先 commit 才能拿到 id
                cat_id = category.id

            new_book = Book(
                title=str(row['書名']),
                author=str(row['作者']),
                publisher=str(row.get('出版社')) if row.get('出版社') else None,
                isbn=str(row.get('ISBN')) if row.get('ISBN') else None,
                category_id=cat_id,
                status=str(row.get('狀態', '未讀')),
                publish_year=int(row.get('出版年')) if row.get('出版年') else None,
                description=str(row.get('簡介')) if row.get('簡介') else None,
                notes=str(row.get('筆記')) if row.get('筆記') else None,
                location=str(row.get('位置')) if row.get('位置') else None,
                rating=int(row.get('評分')) if row.get('評分') else 0
            )
            db.session.add(new_book)
        
        db.session.commit()
        return redirect(url_for('index'))
        
    except Exception as e:
        return f"匯入失敗: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)
