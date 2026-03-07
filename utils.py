import pandas as pd
from database import db, Book

def export_books_to_excel(books, filepath="library_export.xlsx"):
    data = [{
        'ISBN': b.isbn, 
        '書名': b.title, 
        '作者': b.author, 
        '出版社': b.publisher, 
        '儲存位置': b.location, 
        '簡介': b.summary,
        '圖片網址': b.image_url  # 🌟 新增：將資料庫的圖片網址匯出至 Excel
    } for b in books]
    
    df = pd.DataFrame(data)
    df.to_excel(filepath, index=False)
    return filepath

def import_books_from_excel(filepath):
    try:
        df = pd.read_excel(filepath)
        # 🌟 新增 '圖片網址' 到預期欄位清單中
        expected_cols = ['ISBN', '書名', '作者', '出版社', '儲存位置', '簡介', '圖片網址']
        
        # 檢查欄位是否正確
        for col in expected_cols:
            if col not in df.columns:
                return False, f"匯入失敗：缺少必要欄位 '{col}'"

        imported_count = 0
        for index, row in df.iterrows():
            isbn_val = str(row['ISBN']).strip()
            # 避免重複匯入
            if not Book.query.filter_by(isbn=isbn_val).first():
                new_book = Book(
                    isbn=isbn_val,
                    title=str(row['書名']),
                    author=str(row['作者']) if pd.notna(row['作者']) else "",
                    publisher=str(row['出版社']) if pd.notna(row['出版社']) else "",
                    location=str(row['儲存位置']) if pd.notna(row['儲存位置']) else "",
                    summary=str(row['簡介']) if pd.notna(row['簡介']) else "",
                    image_url=str(row['圖片網址']) if pd.notna(row['圖片網址']) else ""  # 🌟 新增：讀取 Excel 的圖片網址並存入資料庫
                )
                db.session.add(new_book)
                imported_count += 1
        
        db.session.commit()
        return True, f"成功匯入 {imported_count} 筆圖書資料！"
    except Exception as e:
        return False, f"匯入發生錯誤: {str(e)}"
