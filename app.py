import os
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import tempfile

app = Flask(__name__)

# 允许特定域名访问
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://your-nextjs-app.vercel.app",  # 替换为你的Vercel域名
            "http://localhost:3000"  # 本地开发用
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# 使用临时目录而不是固定目录
UPLOAD_FOLDER = tempfile.gettempdir()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 添加健康检查路由
@app.route('/healthz')
def health_check():
    return jsonify({"status": "healthy"}), 200

# ... 其他代码保持不变 ...

if __name__ == '__main__':
    # 确保使用环境变量中的端口
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port) 
