from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    isbn = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(100), nullable=False)
    author = db.Column(db.String(100))
    publisher = db.Column(db.String(100))
    location = db.Column(db.String(100))
    summary = db.Column(db.Text)
    image_url = db.Column(db.String(700))  # 🌟 新增：圖片網址欄位