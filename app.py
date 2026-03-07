import os
from flask import Flask
from database import db
from routes.book_routes import book_bp

app = Flask(__name__)
# 設定 Secret Key 以啟用 Flash 訊息 (通知提示)
app.secret_key = 'your_super_secret_key_here' 

# 取得 Render 上的環境變數，若在本地開發則預設使用 SQLite
db_url = os.environ.get('DATABASE_URL', 'sqlite:///local_library.db')

# 自動修正 SQLAlchemy 處理 PostgreSQL 連線字串的相容性問題
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化資料庫
db.init_app(app)

# 註冊路由
app.register_blueprint(book_bp)

# 建立資料表 (若尚不存在)
with app.app_context():
    db.drop_all()
    db.create_all()

if __name__ == '__main__':

    app.run(debug=True)


