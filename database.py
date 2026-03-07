from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Book(db.Model):
    __tablename__ = 'books'
    
    # 核心資訊
    id = db.Column(db.Integer, primary_key=True)             # ID
    title = db.Column(db.String(200), nullable=False)        # 書名 (必填)
    author = db.Column(db.String(100))                       # 作者
    publisher = db.Column(db.String(100))                    # 出版社
    isbn = db.Column(db.String(30), unique=True)             # ISBN (設為唯一值)
    
    # 分類與出版資訊
    category = db.Column(db.String(50))                      # 分類 (如：文學、科學)
    series = db.Column(db.String(100))                       # 叢書名
    volume = db.Column(db.String(20))                        # 集數 (用字串，可填 "上", "3", "特裝版")
    publish_year = db.Column(db.Integer)                     # 出版年
    publish_month = db.Column(db.Integer)                    # 出版月
    
    # 狀態與管理資訊
    status = db.Column(db.String(20), default='在館')        # 狀態 (如：在館、借出、遺失)
    rating = db.Column(db.Float)                             # 評分 (支援小數點，如 4.5)
    location = db.Column(db.String(100))                     # 位置
    tags = db.Column(db.String(200))                         # 標籤 (可逗號分隔，如 "熱門,推薦")
    date_added = db.Column(db.DateTime, default=datetime.utcnow) # 入庫日期 (系統自動抓取當下時間)
    
    # 詳細內容
    summary = db.Column(db.Text)                             # 大綱
    notes = db.Column(db.Text)                               # 備註
    image_url = db.Column(db.String(500))                    # 圖片網址 (保留先前的功能)
