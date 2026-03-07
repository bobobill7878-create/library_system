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
        isbn = request.form['isbn']
        if Book.query.filter_by(isbn=isbn).first():
            flash('此 ISBN 已存在系統中！', 'danger')
            return redirect(url_for('book_bp.add_book'))

        new_book = Book(
            isbn=isbn,
            title=request.form['title'],
            author=request.form['author'],
            publisher=request.form['publisher'],
            location=request.form['location'],
            summary=request.form['summary'],
            image_url=request.form.get('image_url', '') # 🌟 接收圖片網址
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
        book.isbn = request.form['isbn']
        book.title = request.form['title']
        book.author = request.form['author']
        book.publisher = request.form['publisher']
        book.location = request.form['location']
        book.summary = request.form['summary']
        book.image_url = request.form.get('image_url', '') # 🌟 更新圖片網址
        
        db.session.commit()
        flash('圖書編輯成功！', 'success')
        return redirect(url_for('book_bp.index'))
    return render_template('edit_book.html', book=book)

@book_bp.route('/export')
def export_excel():
    books = Book.query.all()
    filepath = export_books_to_excel(books)
    return send_file(f"../{filepath}", as_attachment=True, download_name="library_export.xlsx")

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