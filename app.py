import os
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from bs4 import BeautifulSoup

app = Flask(__name__)

# --- 資料庫設定 (維持不變) ---
if 'RENDER' in os.environ:
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///books.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 資料模型 (維持不變) ---
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

# --- API: ISBN 查詢 (配合您的前端邏輯) ---
@app.route('/api/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    """
    伺服器端爬蟲：優先爬博客來，供前端 ISBN 查詢使用
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'}
        url = f"https://search.books.com.tw/search/query/key/{isbn}/cat/all"
        res = requests.get(url, headers=headers)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # 嘗試抓第一筆結果
            item = soup.select_one('.table-search-tbody tr') or soup.select_one('.item')
            
            if item:
                data = {}
                # 圖片
                img = item.select_one('img')
                if img: data['cover_url'] = (img.get('data-original') or img.get('src') or '').split('?')[0]
                
                # 標題
                title = item.select_one('h3 a, h4 a')
                if title: data['title'] = title.get('title') or title.text.strip()
                
                # 作者
                author = item.select_one('a[rel="go_author"]')
                if author: data['author'] = author.text.strip()
                
                # 出版社
                pub = item.select_one('a[rel="mid_publish"]')
                if pub: data['publisher'] = pub.text.strip()
                
                # 日期
                import re
                m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', item.text)
                if m:
                    data['year'] = m.group(1)
                    data['month'] = m.group(2)
                
                # 簡介
                desc = item.select_one('.box_contents p, .txt_cont')
                if desc: data['description'] = desc.text.strip()[:300] + "..."

                return jsonify(data)
                
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500


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
            # 處理新增分類
            cat_name = request.form.get('new_category')
            cat_id = request.form.get('category_id')
            if cat_name:
                existing = Category.query.filter_by(name=cat_name).first()
                if not existing:
                    new_cat = Category(name=cat_name)
                    db.session.add(new_cat)
                    db.session.commit()
                    cat_id = new_cat.id
                else:
                    cat_id = existing.id

            y = request.form.get('publish_year')
            m = request.form.get('publish_month')
            
            new_book = Book(
                title=request.form['title'],
                author=request.form.get('author'),
                publisher=request.form.get('publisher'),
                isbn=request.form.get('isbn'),
                category_id=cat_id,
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
                cover_url=request.form.get('cover_url')
            )
            db.session.add(new_book)
            db.session.commit()
            return redirect(url_for('index'))
        except Exception as e:
            return f"Error: {e}", 500

    categories = Category.query.all()
    return render_template('add_book.html', categories=categories)

if __name__ == '__main__':
    app.run(debug=True)
