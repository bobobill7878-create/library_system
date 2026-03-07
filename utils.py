import pandas as pd
from database import db, Book

def export_books_to_excel(books, filepath="library_export.xlsx"):
    # 🌟 升級：將資料庫中所有的 17 個欄位完整對應到 Excel
    data = []
    for b in books:
        data.append({
            'ID': b.id,
            'ISBN': b.isbn,
            '書名': b.title,
            '作者': b.author,
            '出版社': b.publisher,
            '分類': b.category,
            '叢書': b.series,
            '集數': b.volume,
            '出版年': b.publish_year,
            '出版月': b.publish_month,
            '狀態': b.status,
            '評分': b.rating,
            '儲存位置': b.location,
            '標籤': b.tags,
            '簡介': b.summary,
            '備註': b.notes,
            '圖片網址': b.image_url,
            '入庫日期': b.date_added.strftime('%Y-%m-%d %H:%M:%S') if b.date_added else ''
        })
    
    df = pd.DataFrame(data)
    df.to_excel(filepath, index=False)
    return filepath

def import_books_from_excel(filepath):
    try:
        df = pd.read_excel(filepath)
        
        # 🌟 升級防呆：為了相容舊版 Excel，我們只把最核心的設為「必填檢查」
        expected_cols = ['ISBN', '書名']
        
        # 檢查必填欄位是否正確
        for col in expected_cols:
            if col not in df.columns:
                return False, f"匯入失敗：缺少必要欄位 '{col}'"

        imported_count = 0
        for index, row in df.iterrows():
            # 安全抓取 ISBN，如果沒填則跳過該列
            isbn_val = str(row.get('ISBN', '')).strip()
            if not isbn_val or isbn_val == 'nan' or pd.isna(row.get('書名')):
                continue

            # 避免重複匯入
            if not Book.query.filter_by(isbn=isbn_val).first():
                
                # 建立內部小幫手函數：安全轉換資料型態 (防止 Excel 裡的空值或文字造成崩潰)
                def get_int(val):
                    try: return int(val) if pd.notna(val) else None
                    except: return None
                    
                def get_float(val):
                    try: return float(val) if pd.notna(val) else None
                    except: return None

                def get_str(col_name):
                    # 如果該欄位存在於 Excel 且有值，就轉字串，否則回傳空字串
                    if col_name in df.columns and pd.notna(row[col_name]):
                        return str(row[col_name])
                    return ""

                # 建立並寫入完整的新書資料
                new_book = Book(
                    isbn=isbn_val,
                    title=get_str('書名'),
                    author=get_str('作者'),
                    publisher=get_str('出版社'),
                    category=get_str('分類'),
                    series=get_str('叢書'),
                    volume=get_str('集數'),
                    publish_year=get_int(row.get('出版年')),
                    publish_month=get_int(row.get('出版月')),
                    status=get_str('狀態') or '在館', # 若沒填狀態，預設為「在館」
                    rating=get_float(row.get('評分')),
                    location=get_str('儲存位置'), # 注意：這裡對應新表單通常叫「儲存位置」或「位置」
                    tags=get_str('標籤'),
                    summary=get_str('簡介'),      # 對應資料庫的 summary
                    notes=get_str('備註'),
                    image_url=get_str('圖片網址')
                )
                db.session.add(new_book)
                imported_count += 1
        
        db.session.commit()
        return True, f"成功匯入 {imported_count} 筆圖書資料！"
    except Exception as e:
        return False, f"匯入發生錯誤: {str(e)}"
