import os
from flask import Blueprint, render_template, request, redirect, url_for, send_file, flash
from database import db, Book
from utils import export_books_to_excel, import_books_from_excel

# 建立一個 Blueprint (藍圖)，用來將與「圖書」相關的路由打包在一起，讓主程式 (app.py) 更簡潔
book_bp = Blueprint('book_bp', __name__)

# ==========================================
# 1. 首頁與查詢功能 (讀取全部或搜尋圖書)
# ==========================================
@book_bp.route('/', methods=['GET'])
def index():
    # 嘗試從網址參數中取得 'query' (例如: /?query=哈利波特)
    query = request.args.get('query', '')
    
    if query:
        # 如果有搜尋關鍵字，使用 ilike 進行「模糊比對」 (不分大小寫)
        # 尋找書名或作者包含該關鍵字的書籍
        books = Book.query.filter(
            (Book.title.ilike(f'%{query}%')) | (Book.author.ilike(f'%{query}%'))
        ).all()
    else:
        # 如果沒有關鍵字，就從資料庫抓取所有書籍
        books = Book.query.all()
        
    # 將抓取到的書籍資料 (books) 和目前的搜尋字詞 (query) 傳遞給前端網頁
    return render_template('index.html', books=books, query=query)

# ==========================================
# 2. 新增圖書功能
# ==========================================
@book_bp.route('/add', methods=['GET', 'POST'])
def add_book():
    # 當使用者按下「儲存圖書」按鈕時，會發送 POST 請求
    if request.method == 'POST':
        # 取得表單中的 ISBN
        isbn = request.form.get('isbn', '')
        
        # 檢查資料庫中是否已經有相同的 ISBN (避免重複登錄)
        if isbn and Book.query.filter_by(isbn=isbn).first():
            flash('此 ISBN 已存在系統中！請確認是否重複輸入。', 'danger')
            return redirect(url_for('book_bp.add_book'))

        # --- 安全轉換數值欄位 ---
        # 因為從 HTML 表單傳來的資料都是「字串」，如果使用者沒填(空字串)，直接轉整數會當機
        publish_year = request.form.get('publish_year')
        publish_year = int(publish_year) if publish_year and publish_year.isdigit() else None
        
        publish_month = request.form.get('publish_month')
        publish_month = int(publish_month) if publish_month and publish_month.isdigit() else None

        # 評分支援小數點，所以用 float 轉換，並用 try-except 防止輸入奇怪的文字
        rating_val = request.form.get('rating')
        try:
            rating = float(rating_val) if rating_val else None
        except ValueError:
            rating = None

        # --- 建立新的資料庫物件 ---
        new_book = Book(
            isbn=isbn,
            title=request.form['title'], # 書名是必填，所以直接取值
            author=request.form.get('author', ''),
            publisher=request.form.get('publisher', ''),
            category=request.form.get('category', ''),
            series=request.form.get('series', ''),
            volume=request.form.get('volume', ''),
            publish_year=publish_year,
            publish_month=publish_month,
            status=request.form.get('status', '在館'), # 狀態預設為 '在館'
            rating=rating,
            location=request.form.get('location', ''),
            tags=request.form.get('tags', ''),
            summary=request.form.get('summary', ''),
            notes=request.form.get('notes', ''),
            image_url=request.form.get('image_url', '')
        )
        
        # 將新書籍加入資料庫並儲存變更
        db.session.add(new_book)
        db.session.commit()
        
        # 顯示成功提示訊息
        flash(f'圖書《{new_book.title}》新增成功！您可以繼續新增下一筆。', 'success')
        
        # 🌟 修改點：儲存後重新導向回 add_book 頁面，方便連續新增
        return redirect(url_for('book_bp.add_book'))
        
    # 如果是 GET 請求 (使用者剛點進「新增圖書」的網址)，則顯示表單畫面
    return render_template('add_book.html')

# ==========================================
# 3. 編輯圖書功能
# ==========================================
# 網址中的 <int:id> 代表這本書在資料庫的專屬 ID
@book_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    # 根據 ID 找出這本書，如果找不到就顯示 404 錯誤網頁
    book = Book.query.get_or_404(id)
    
    if request.method == 'POST':
        # 接收表單傳來的新資料，並覆蓋原本的資料
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
        
        # 儲存修改到資料庫
        db.session.commit()
        flash('圖書編輯成功！', 'success')
        
        # 編輯完成後，通常會導回首頁查看結果
        return redirect(url_for('book_bp.index'))
        
    # GET 請求：顯示編輯表單，並將舊資料 (book) 帶入前端 HTML 中顯示
    return render_template('edit_book.html', book=book)

# ==========================================
# 4. 匯出 Excel 功能
# ==========================================
@book_bp.route('/export')
def export_excel():
    # 從資料庫抓取所有書籍
    books = Book.query.all()
    
    # 將檔案存到 /tmp 目錄 (這是 Linux 和 Render 雲端環境中絕對安全的暫存區)
    filepath = os.path.join('/tmp', 'library_export.xlsx')
    
    # 呼叫 utils.py 中寫好的匯出邏輯，產出 Excel 檔案
    export_books_to_excel(books, filepath)
    
    # 使用 Flask 的 send_file 將檔案傳送給使用者的瀏覽器下載
    # as_attachment=True 代表強制下載，download_name 指定下載時的預設檔名
    return send_file(filepath, as_attachment=True, download_name="library_export.xlsx")

# ==========================================
# 5. 匯入 Excel 功能
# ==========================================
@book_bp.route('/import', methods=['POST'])
def import_excel():
    # 檢查請求中是否包含名為 'file' 的上傳檔案
    if 'file' not in request.files:
        flash('沒有選擇檔案', 'danger')
        return redirect(url_for('book_bp.index'))
    
    file = request.files['file']
    
    # 檢查使用者是否沒有選檔案就按送出
    if file.filename == '':
        flash('沒有選擇檔案', 'danger')
        return redirect(url_for('book_bp.index'))
        
    # 確認副檔名是否為 Excel 格式
    if file and file.filename.endswith(('.xls', '.xlsx')):
        # 將使用者上傳的檔案先存到伺服器的暫存區 (/tmp)
        filepath = os.path.join('/tmp', file.filename)
        file.save(filepath)
        
        # 呼叫 utils.py 中寫好的匯入邏輯讀取 Excel
        success, msg = import_books_from_excel(filepath)
        
        if success:
            flash(msg, 'success')
        else:
            flash(msg, 'danger')
            
        # 處理完畢後，把留在伺服器上的暫存 Excel 檔刪除，節省空間
        if os.path.exists(filepath):
            os.remove(filepath)
    else:
        # 如果上傳了非 Excel 的檔案 (如 PDF, 圖片)
        flash('僅支援 Excel 檔案 (.xlsx, .xls)', 'danger')
        
    # 回到首頁顯示結果
    return redirect(url_for('book_bp.index'))
