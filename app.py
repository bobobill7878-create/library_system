import os
import io
import requests
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

# --- 資料庫設定 ---
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

# --- 初始化 ---
with app.app_context():
    # ★★★ 安全模式：這行加了 #，不會刪除資料 ★★★
    #db.    #db.dr
    
    db.create_all()

    if not Category.query.first():
        cats = ['漫畫', '輕小說', '文學小說', '商業理財', '心理勵志', '人文社科', '工具書', '其他']
        for c in cats:
            db.session.add(Category(name=c))
        db.session.commit()

# --- 博客來爬蟲 API (新增功能) ---
@app.route('/api/lookup_books_tw')
def lookup_books_tw():
    keyword = request.args.get('q')
    if not keyword:
        return jsonify({'success': False, 'message': '請輸入關鍵字'}), 400

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        url = f"https://search.books.com.tw/search/query/key/{keyword}/cat/all"
        res = requests.get(url, headers=headers)
        
        if res.status_code != 200:
            return jsonify({'success': False, 'message': '連接博客來失敗'}), 500

        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 嘗試抓取搜尋結果
        results = soup.select('.table-search-tbody tr')
        if not results:
            results = soup.select('.item') # 網格模式
        
        if not results:
            return jsonify({'success': False, 'message': '博客來找不到此書'}), 404

        item = results[0]
        data = {}
        
        # 圖片
        img_tag = item.select_one('img')
        if img_tag:
            src = img_tag.get('data-original') or img_tag.get('src')
            if src:
                data['cover_url'] = src.split('?')[0] # 拿掉參數取大圖

        # 書名
        title_tag = item.select_one('h3 a, h4 a, .box_header h3 a')
        if title_tag:
            data['title'] = title_tag.get('title') or title_tag.text.strip()
            
        # 作者
        author_tag = item.select_one('a[rel="go_author"]')
        if author_tag:
            data['author'] = author_tag.text.strip()
        else:
            data['author'] = '未知'

        # 出版社
        pub_tag = item.select_one('a[rel="mid_publish"]')
        if pub_tag:
            data['publisher'] = pub_tag.text.strip()
            
        # 出版日期解析
        text_content = item.text
        import re
        date_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', text_content)
        if date_match:
            data['year'] = date_match.group(1)
            data['month'] = date_match.group(2)
        
        # 簡介 (嘗試抓取)
        desc_tag = item.select_one('.box_contents p, .txt_cont')
        if desc_tag:
            data['description'] = desc_tag.text.strip()

        return jsonify({'success': True, 'data': data})

    except Exception as e:
        print(f"爬蟲錯誤: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# --- 路由 ---
@app.route('/')
def index():
    query = Book.query
    
    # 搜尋功能
    q = request.args.get('q')
    if q:
        query = query.filter(
            (Book.title.contains(q)) | 
            (Book.author.contains(q)) |
            (Book.isbn.contains(q))
        )
    
    # 分類篩選
    cat_id = request.args.get('category')
    if cat_id:
        query = query.filter(Book.category_id == cat_id)

    # 排序：未讀優先，然後按更新時間
    books = query.order_by(Book.status.asc(), Book.updated_at.desc()).all()
    categories = Category.query.all()
    
    return render_template('index.html', books=books, categories=categories)

@app.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        try:
            # 處理分類
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

            # 處理年份/月份
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
        book.title = request.form['title']
        book.author = request.form.get('author')
        book.publisher = request.form.get('publisher')
        book.isbn = request.form.get('isbn')
        book.status = request.form.get('status')
        book.rating = request.form.get('rating')
        book.series = request.form.get('series')
        book.volume = request.form.get('volume')
        book.print_version = request.form.get('print_version')
        
        y = request.form.get('publish_year')
        m = request.form.get('publish_month')
        book.publish_year = int(y) if y and y.isdigit() else None
        book.publish_month = int(m) if m and m.isdigit() else None
        
        book.location = request.form.get('location')
        book.tags = request.form.get('tags')
        book.description = request.form.get('description')
        book.notes = request.form.get('notes')
        book.cover_url = request.form.get('cover_url')
        
        cat_id = request.form.get('category_id')
        new_cat = request.form.get('new_category')
        if new_cat:
            c = Category.query.filter_by(name=new_cat).first()
            if not c:
                c = Category(name=new_cat)
                db.session.add(c)
                db.session.commit()
            book.category_id = c.id
        else:
            book.category_id = cat_id

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

@app.route('/categories')
def manage_categories():
    # 統計每個分類有多少本書
    stats = db.session.query(
        Category, db.func.count(Book.id)
    ).outerjoin(Book).group_by(Category.id).all()
    return render_template('categories.html', categories=stats)

# --- Excel 匯入/匯出 ---
@app.route('/export')
def export_excel():
    books = Book.query.all()
    data = []
    for b in books:
        c_name = b.category_ref.name if b.category_ref else ''
        data.append({
            '書名': b.title, '作者': b.author, '出版社': b.publisher,
            'ISBN': b.isbn, '分類': c_name, '狀態': b.status,
            '評分': b.rating, '系列': b.series, '集數': b.volume,
            '版本': b.print_version, '出版年': b.publish_year,
            '位置': b.location, '標籤': b.tags, '備註': b.notes
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Books')
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'library_export_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )

@app.route('/import', methods=['POST'])
def import_excel():
    if 'file' not in request.files:
        return "No file", 400
    file = request.files['file']
    if file.filename == '':
        return "No name", 400

    try:
        df = pd.read_excel(file)
        count = 0
        for _, row in df.iterrows():
            # 簡單檢查必填
            if pd.isna(row.get('書名')): continue
            
            # 處理分類
            cat_id = None
            if not pd.isna(row.get('分類')):
                c_name = str(row['分類']).strip()
                cat = Category.query.filter_by(name=c_name).first()
                if not cat:
                    cat = Category(name=c_name)
                    db.session.add(cat)
                    db.session.commit()
                cat_id = cat.id
            
            # 建立書籍
            book = Book(
                title=row.get('書名'),
                author=row.get('作者') if not pd.isna(row.get('作者')) else None,
                publisher=row.get('出版社') if not pd.isna(row.get('出版社')) else None,
                isbn=str(row.get('ISBN')) if not pd.isna(row.get('ISBN')) else None,
                category_id=cat_id,
                status=row.get('狀態', '未讀'),
                rating=row.get('評分') if not pd.isna(row.get('評分')) else None,
                notes=row.get('備註') if not pd.isna(row.get('備註')) else None
            )
            db.session.add(book)
            count += 1
        
        db.session.commit()
        return redirect(url_for('index'))
    except Exception as e:
        return f"匯入失敗: {str(e)}", 500

if __name__ == '__main__':
    app.run(debug=True)
