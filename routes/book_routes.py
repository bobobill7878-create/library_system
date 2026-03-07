import os
from flask import Blueprint, render_template, request, redirect, url_for, send_file, flash
from database import db, Book
from utils import export_books_to_excel, import_books_from_excel

book_bp = Blueprint('book_bp', __name__)

@book_bp.route('/', methods=['GET'])
def index():
    query = request.args.get('query', '')
    if query:
        books = Book.query.filter(
            (Book.title.ilike(f'%{query}%')) | (Book.author.ilike(f'%{query}%'))
        ).all()
    else:
        books = Book.query.all()
    return render_template('index.html', books=books, query=query)

@book_bp.route('/add', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        isbn = request.form.get('isbn', '')
        if isbn and Book.query.filter_by(isbn=isbn).first():
            flash('此 ISBN 已存在系統中！', 'danger')
            return redirect(url_for('book_bp.add_book'))

        # 安全轉換數值欄位 (若空白則設為 None)
        publish_year = request.form.get('publish_year')
        publish_year = int(publish_year) if publish_year and publish_year.isdigit() else None
        
        publish_month = request.form.get('publish_month')
        publish_month = int(publish_month) if publish_month and publish_month.isdigit() else None

        rating_val = request.form.get('rating')
        try:
            rating = float(rating_val) if rating_val else None
        except ValueError:
            rating = None

        new_book = Book(
            isbn=isbn,
            title=request.form['title'],
            author=request.form.get('author', ''),
            publisher=request.form.get('publisher', ''),
            category=request.form.get('category', ''),
            series=request.form.get('series', ''),
            volume=request.form.get('volume', ''),
            publish_year=publish_year,
            publish_month=publish_month,
            status=request.form.get('status', '在館'),
            rating=rating,
            location=request.form.get('location', ''),
            tags=request.form.get('tags', ''),
            summary=request.form.get('summary', ''),
            notes=request.form.get('notes', ''),
            image_url=request.form.get('image_url', '')
        )
        db.session.add(new_book)
        db.session.commit()
        flash('圖書新增成功！', 'success')
        return redirect(url_for('book_bp.index'))
    return render_template('add_book.html')

@book_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    book = Book.query.get_or_404(id)
    if request.method == 'POST':
        book.isbn = request.form.get('isbn', '')
        book.title = request.form.get('title', '')
        book.author = request.form.get('author', '')
        book.publisher = request.form.get('publisher', '')
        book.category = request.form.get('category', '')
        book.series = request.form.get('series', '')
        book.volume = request.form.get('volume', '')
        
        # 安全轉換數值欄位
        year_val = request.form.get('publish_year')
        book.publish_year = int(year_val) if year_val and year_val.isdigit() else None
        
        month_val = request.form.get('publish_month')
        book.publish_month = int(month_val) if month_val and month_val.isdigit() else None
        
        book.status = request.form.get('status', '在館')
        
        rating_val = request.form.get('rating')
        try:
            book.rating = float(rating_val) if rating_val else None
        except ValueError:
            book.rating = None

        book.location = request.form.get('location', '')
        book.tags = request.form.get('tags', '')
        book.summary = request.form.get('summary', '')
        book.notes = request.form.get('notes', '')
        book.image_url = request.form.get('image_url', '')
        
        db.session.commit()
        flash('圖書編輯成功！', 'success')
        return redirect(url_for('book_bp.index'))
    return render_template('edit_book.html', book=book)

@book_bp.route('/export')
def export_excel():
    import os
    
    # 從資料庫抓取所有書籍
    books = Book.query.all()
    
    # 指定儲存到 Linux/Render 的安全暫存目錄
    filepath = os.path.join('/tmp', 'library_export.xlsx')
    
    # 呼叫 utils.py 的匯出函數，並指定我們寫好的安全路徑
    export_books_to_excel(books, filepath)
    
    # 傳送檔案給使用者下載
    return send_file(filepath, as_attachment=True, download_name="library_export.xlsx")

@book_bp.route('/import', methods=['POST'])
def import_excel():
    if 'file' not in request.files:
        flash('沒有選擇檔案', 'danger')
        return redirect(url_for('book_bp.index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('沒有選擇檔案', 'danger')
        return redirect(url_for('book_bp.index'))
        
    if file and file.filename.endswith(('.xls', '.xlsx')):
        filepath = os.path.join('/tmp', file.filename)
        file.save(filepath)
        success, msg = import_books_from_excel(filepath)
        if success:
            flash(msg, 'success')
        else:
            flash(msg, 'danger')
        # 清除暫存檔
        if os.path.exists(filepath):
            os.remove(filepath)
    else:
        flash('僅支援 Excel 檔案 (.xlsx, .xls)', 'danger')
        
    return redirect(url_for('book_bp.index'))
