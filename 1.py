from flask import Flask, request, jsonify, send_file
import yt_dlp
import whisper
import requests
import os
import threading
import uuid
from werkzeug.utils import secure_filename
import ffmpeg
import shutil
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
import io
from PIL import Image
import tempfile
import sys
import subprocess
from flask_cors import CORS
import re
import time

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = './uploads'
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'mp4', 'avi', 'mov', 'webm'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 确保文件夹存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 修改文件大小限制为 1GB
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB = 1024MB = 1024 * 1024 * 1024 bytes

# 在文件顶部修改常量定义
API_URL = 'https://xiaoai.plus/v1/chat/completions'
API_KEY = 'sk-wkJ8C4yXkzkXiwUm2e0322A6Bf254239824bC7D6F91a3468'
MODEL = 'claude-3-5-sonnet-20240620'

# 在文件顶部添加一个集合来存储已处理的URL
processed_urls = set()

def allowed_file(filename):
    """检查文件类型和大小"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_bilibili_url(url):
    """解析B站链接，返回BV号"""
    bv_match = re.search(r'BV\w+', url)
    if bv_match:
        return bv_match.group()
    raise Exception("无效的B站链接")

def download_video(url, filename):
    """通用视频下载函数"""
    try:
        # 检测是否是B站链接
        if "bilibili.com" in url:
            bv_id = parse_bilibili_url(url)
            url = f'https://www.bilibili.com/video/{bv_id}'
            print(f"处理B站视频: {url}")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'temp_audio.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            # 添加重试和超时设置
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 30,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            },
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print(f"开始下载: {url}")
                ydl.extract_info(url, download=True)
                print("下载完成")
            return 'temp_audio.mp3'
        except Exception as e:
            print(f"第一次下载失败，尝试备用方法: {str(e)}")
            # 备用下载方法
            ydl_opts['format'] = 'worstaudio/worst'  # 尝试下载较低质量的音频
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
            return 'temp_audio.mp3'
            
    except Exception as e:
        print(f"下载错误: {str(e)}")
        raise Exception(f"下载失败: {str(e)}")

def get_text_summary(text, custom_style=None):
    """获取文本总结（分别生成思维导图和文章）"""
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }
        
        # 添加错误处理和重试机制
        max_retries = 3
        retry_count = 0
        mindmap = None
        article = None
        
        # 生成思维导图
        while retry_count < max_retries:
            try:
                mindmap_response = requests.post(
                    API_URL,
                    headers=headers,
                    json={
                        "model": "claude-3-5-sonnet-20240620",
                        "messages": [
                            {
                                "role": "system", 
                                "content": """请将内容整理成一个清晰易读的思维导图，使用markdown格式。要求：

1. 格式要求：
   - 使用 # 表示一级标题
   - 使用 ## 表示二级标题
   - 使用 ### 表示三级标题
   - 每个层级使用简短的短语或关键词
   - 避免过长的句子

2. 内容要求：
   - 突出核心知识点和关键概念
   - 用简洁但有启发性的语言
   - 确保逻辑层次清晰
   - 重要内容用【】标注
   - 关键步骤用数字标记
   -内容输出是简体中文

3. 结构要求：
   - 最多使用三层层级
   - 同级内容保持对齐
   - 相关内容放在一起
   - 保持层次分明
   - 避免过于复杂的分支

4. 可读性要求：
   - 使用简单明了的语言
   - 避免专业术语堆砌
   - 适当使用符号标记
   - 保持条理清晰
   - 便于快速浏览和理解

注意：思维导图的目的是帮助读者快速理解和记忆内容，要突出重点，简明扼要。"""
                            },
                            {"role": "user", "content": text}
                        ]
                    },
                    timeout=30
                )
                
                if mindmap_response.ok:
                    mindmap = mindmap_response.json()['choices'][0]['message']['content']
                    break
                    
                retry_count += 1
                time.sleep(1)
                
            except requests.exceptions.RequestException as e:
                print(f"思维导图生成失败，正在重试 ({retry_count + 1}/{max_retries}): {str(e)}")
                retry_count += 1
                if retry_count >= max_retries:
                    raise Exception("API 服务暂时不可用，请稍后重试")
                time.sleep(1)
        
        # 生成文章
        if custom_style and custom_style.strip():
            style_prompt = f"""请以{custom_style}的风格，将这些内容转化为一篇极其详尽的教学文章。要求：

1. 内容完整性：
   - 确保每个概念、步骤都有充分详细的解释
   - 不要因篇幅限制而省略任何重要内容
   - 宁可重复也不要遗漏关键信息
   - 对重点内容要反复举例说明

2. 文章结构：
   第一部分：内容概览（10%篇幅）
   - 本文要讲什么
   - 为什么要学习这个内容
   - 学习这些内容能解决什么问题
   - 需要的前置知识
   - 预期的学习成果

   第二部分：基础知识（20%篇幅）
   - 详细解释每个核心概念
   - 阐述基本原理和理论
   - 介绍相关的背景知识
   - 解释专业术语的含义
   - 澄清常见的误解

   第三部分：主要内容（40%篇幅）
   - 每个步骤都要详细展开
   - 提供具体的操作方法
   - 给出清晰的判断标准
   - 列举可能的变化情况
   - 分析不同情况的处理方法

   第四部分：实践指导（20%篇幅）
   - 完整的操作流程演示
   - 每个步骤的注意事项
   - 常见问题的解决方案
   - 实践中的技巧和诀窍
   - 效果评估和优化方法

   第五部分：进阶内容（10%篇幅）
   - 高级应用场景
   - 优化和改进方法
   - 相关领域的拓展
   - 进阶学习建议
   - 推荐的学习资源

3. 写作要求：
   - 采用{custom_style}的表达风格
   - 通过具体例子解释抽象概念
   - 多角度分析每个问题
   - 预设读者可能的疑问并解答
   - 分享实践经验和教训
   - 保持逻辑的连贯性

4. 教学设计：
   - 设置循序渐进的学习节奏
   - 在关键点设置思考问题
   - 通过类比加深理解
   - 强调重点和难点
   - 及时总结和回顾
   - 提供练习和实践建议

5. 互动元素：
   - 设置思考题和练习
   - 提供自测问题
   - 布置实践任务
   - 引导读者思考和探索
   - 鼓励实践和创新

目标：让读者通过阅读就能完全掌握所有内容，不需要观看视频也能独立实践应用。内容长度不限，以充分讲解清楚为准。宁可重复也不要遗漏，宁可啰嗦也要讲透。"""
        else:
            style_prompt = """请将这些内容转化为一篇极其详尽的教学文章。要求：

[与上面相同的内容，只是去掉了自定义风格部分]"""

        retry_count = 0
        while retry_count < max_retries:
            try:
                print("开始生成文章...")
                article_response = requests.post(
                    API_URL,
                    headers=headers,
                    json={
                        "model": MODEL,
                        "messages": [
                            {"role": "system", "content": style_prompt},
                            {"role": "user", "content": text}
                        ]
                    },
                    timeout=60  # 增加超时时间
                )
                
                print(f"API响应状态码: {article_response.status_code}")
                
                if article_response.ok:
                    article_data = article_response.json()
                    if 'choices' in article_data and len(article_data['choices']) > 0:
                        article = article_data['choices'][0]['message']['content']
                        print("文章生成成功")
                        break
                    else:
                        print("API返回数据格式错误:", article_data)
                        raise Exception("API返回数据格式错误")
                else:
                    print(f"API请求失败: {article_response.text}")
                    
                retry_count += 1
                if retry_count < max_retries:
                    print(f"等待重试 ({retry_count}/{max_retries})...")
                    time.sleep(2)  # 增加重试间隔
                
            except Exception as e:
                print(f"文章生成失败，正在重试 ({retry_count + 1}/{max_retries}): {str(e)}")
                retry_count += 1
                if retry_count >= max_retries:
                    raise Exception(f"文章生成失败: {str(e)}")
                time.sleep(2)
        
        if mindmap is None or article is None:
            raise Exception("生成失败：思维导图或文章生成失败")
            
        return {
            "mindmap": mindmap,
            "article": article
        }
        
    except Exception as e:
        print(f"总结生成失败: {str(e)}")
        raise Exception(f"总结生成失败: {str(e)}")

# 存储任务状态
tasks = {}

@app.route('/api/process', methods=['POST'])
def process():
    try:
        urls = request.json.get('urls', [])
        custom_style = request.json.get('customStyle')
        if not urls:
            return jsonify({"error": "请提供至少一个YouTube URL"}), 400
        
        task_ids = []
        for url in urls:
            # 检查URL是否已经处理过
            if url in processed_urls:
                print(f"URL已处理过，跳过: {url}")
                continue
                
            task_id = str(uuid.uuid4())
            task_ids.append(task_id)
            tasks[task_id] = {"status": "等待中", "url": url}
            
            # 启动异步处理
            thread = threading.Thread(target=process_video, args=(url, task_id, custom_style))
            thread.start()
            
            # 将URL添加到已处理集合
            processed_urls.add(url)
        
        if not task_ids:
            return jsonify({"message": "所有链接都已处理过"}), 200
            
        return jsonify({"task_ids": task_ids})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 可以添加一个清除缓存的接口（可选）
@app.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    try:
        processed_urls.clear()
        return jsonify({"message": "缓存已清除"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            print("没有文件被上传")
            return jsonify({"error": "没有文件"}), 400
        
        file = request.files['file']
        if file.filename == '':
            print("文件名为空")
            return jsonify({"error": "未选择文件"}), 400
        
        # 检查文件大小
        file.seek(0, 2)  # 移动到文件末尾
        file_size = file.tell()  # 获取文件大小
        file.seek(0)  # 重置文件指针
        
        if file_size > MAX_FILE_SIZE:
            print(f"文件过大: {file_size} bytes")
            return jsonify({"error": f"文件大小不能超过 1GB"}), 400
        
        if file and allowed_file(file.filename):
            try:
                task_id = str(uuid.uuid4())
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_{filename}")
                print(f"尝试保存文件到: {file_path}")
                
                # 保存文件
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(file_path)
                print(f"文件保存成功: {file_path}")
                
                # 启异步处理
                tasks[task_id] = {"status": "等待中", "url": filename}
                custom_style = request.form.get('customStyle')
                thread = threading.Thread(target=process_file, args=(file_path, task_id, custom_style))
                thread.start()
                
                return jsonify({"task_id": task_id})
            except Exception as e:
                print(f"文件处理错误: {str(e)}")
                return jsonify({"error": str(e)}), 500
        else:
            print(f"不支持的文件类型: {file.filename}")
            return jsonify({"error": "不支持的文件类型"}), 400
    except Exception as e:
        print(f"上传过程错误: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/status/<task_id>')
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify({"data": tasks[task_id]})

def process_video(url, task_id, custom_style=None):
    audio_file = None
    try:
        # 1. 下载音频
        tasks[task_id]["status"] = "下载中..."
        try:
            audio_file = download_video(url, task_id)
        except Exception as e:
            print(f"下载失败: {str(e)}")
            tasks[task_id].update({
                "status": "失败",
                "error": f"下载失败: {str(e)}"
            })
            return
        
        # 2. 转文字
        tasks[task_id]["status"] = "转换文字中..."
        try:
            model = whisper.load_model("base", device="cpu")
            result = model.transcribe(audio_file)
            print("文字转换完成")
        except Exception as e:
            print(f"转换文字失败: {str(e)}")
            tasks[task_id].update({
                "status": "失败",
                "error": f"转换文字失败: {str(e)}"
            })
            return
        
        # 3. 获取总结
        tasks[task_id]["status"] = "生成总结中..."
        try:
            print("开始生成总结...")
            summary = get_text_summary(result["text"], custom_style)
            print("总结生成完成")
            tasks[task_id].update({
                "status": "完成",
                "result": summary["article"],
                "mindmap": summary["mindmap"],
                "original_text": result["text"]
            })
        except Exception as e:
            print(f"生成总结失败: {str(e)}")
            tasks[task_id].update({
                "status": "失败",
                "error": f"生成总结失败: {str(e)}"
            })
            
    except Exception as e:
        print(f"处理失败: {str(e)}")
        tasks[task_id].update({
            "status": "失败",
            "error": str(e)
        })
    finally:
        # 清理临时文件
        if audio_file and os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except Exception as e:
                print(f"清理文件失败: {str(e)}")

def process_file(file_path, task_id, custom_style=None):
    audio_file = None
    try:
        print(f"开始处理文件: {file_path}")  # 添加日志
        
        # 1. 如果是视频文件，先提取音频
        tasks[task_id]["status"] = "处理音中..."
        try:
            if not file_path.lower().endswith('.mp3'):
                print("提取音频...")
                audio_file = extract_audio(file_path, task_id)
            else:
                audio_file = file_path
            print(f"音频文件准备完成: {audio_file}")
        except Exception as e:
            print(f"音频处理失败: {str(e)}")
            tasks[task_id].update({
                "status": "失败",
                "error": f"音频处理失败: {str(e)}"
            })
            return
        
        # 2. 转文字
        tasks[task_id]["status"] = "转换文字中..."
        try:
            print("加载 Whisper 模型...")
            model = whisper.load_model("base", device="cpu")
            print("开始转换文字...")
            result = model.transcribe(audio_file)
            print("文字转换完成")
        except Exception as e:
            print(f"转换文字失败: {str(e)}")
            tasks[task_id].update({
                "status": "失败",
                "error": f"转换文字失败: {str(e)}"
            })
            return
        
        # 3. 获取总结
        tasks[task_id]["status"] = "生成总结中..."
        try:
            print("开始生成总结...")
            summary = get_text_summary(result["text"], custom_style)
            print("总结生成完成")
            tasks[task_id].update({
                "status": "完成",
                "result": summary["article"],
                "mindmap": summary["mindmap"],
                "original_text": result["text"]
            })
        except Exception as e:
            print(f"生成总结失败: {str(e)}")
            tasks[task_id].update({
                "status": "失败",
                "error": f"生成总结失败: {str(e)}"
            })
            
    except Exception as e:
        print(f"处理失败: {str(e)}")
        tasks[task_id].update({
            "status": "失败",
            "error": str(e)
        })
    finally:
        # 清理临时文件
        try:
            if audio_file and audio_file != file_path and os.path.exists(audio_file):
                os.remove(audio_file)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"清理文件失败: {str(e)}")

def extract_audio(video_path, task_id):
    """从视频文件提取音频"""
    try:
        print(f"开始从视频提取音频: {video_path}")
        audio_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_audio.mp3")
        audio_path = os.path.normpath(audio_path)
        
        if video_path.lower().endswith('.mp3'):
            print("已经是 MP3 文件，直接复制")
            shutil.copy2(video_path, audio_path)
        else:
            print("使用 ffmpeg 处理视频文件")
            try:
                stream = ffmpeg.input(video_path)
                stream = ffmpeg.output(stream, audio_path, acodec='libmp3lame')
                ffmpeg.run(stream, overwrite_output=True, capture_stderr=True)
            except ffmpeg.Error as e:
                print('FFmpeg error:', e.stderr.decode() if e.stderr else str(e))
                raise
        
        print(f"音频提取成: {audio_path}")
        return audio_path
    except Exception as e:
        print(f"音频提取失败: {str(e)}")
        raise

@app.route('/convert_svg_to_jpg', methods=['POST'])
def convert_svg_to_jpg():
    try:
        svg_data = request.data
        
        # 使用系统临时目录
        temp_dir = tempfile.gettempdir()
        temp_svg = os.path.join(temp_dir, f'temp_{uuid.uuid4()}.svg')
        temp_png = os.path.join(temp_dir, f'temp_{uuid.uuid4()}.png')
        
        try:
            print(f'Creating SVG file at: {temp_svg}')  # 调试信息
            # 写入 SVG 据
            with open(temp_svg, 'wb') as f:
                f.write(svg_data)
            
            print('Converting SVG to PNG')  # 调试信息
            # 转换 SVG 到 PNG
            drawing = svg2rlg(temp_svg)
            renderPM.drawToFile(drawing, temp_png, fmt='PNG', dpi=300)
            
            print('Converting PNG to JPG')  # 调试信息
            # 使用 Pillow 转换为 JPG
            with Image.open(temp_png) as img:
                # 创建白色背景
                background = Image.new('RGB', img.size, 'white')
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img)
                
                # 保存为 JPG
                output = io.BytesIO()
                background.save(output, format='JPEG', quality=95)
                output.seek(0)
                
                print('Sending file')  # 试信息
                return send_file(
                    output,
                    mimetype='image/jpeg',
                    as_attachment=True,
                    download_name='mindmap.jpg'
                )
                
        finally:
            # 理临时文件
            print('Cleaning up temporary files')  # 调试信息
            if os.path.exists(temp_svg):
                os.remove(temp_svg)
            if os.path.exists(temp_png):
                os.remove(temp_png)
                
    except Exception as e:
        print('Convert SVG to JPG error:', str(e))  # 详细的错误信息
        return jsonify({"error": str(e)}), 500

# 添加保存功能
@app.route('/api/save', methods=['POST'])
def save_result():
    try:
        data = request.json
        task_id = data.get('taskId')
        
        if task_id not in tasks:
            return jsonify({"error": "任务不存在"}), 404
            
        task = tasks[task_id]
        
        # 创建保存目录
        save_dir = os.path.join('saved_results', task_id)
        os.makedirs(save_dir, exist_ok=True)
        
        # 保存文章
        if task.get('result'):
            article_path = os.path.join(save_dir, 'article.txt')
            with open(article_path, 'w', encoding='utf-8') as f:
                f.write(task['result'])
                
        # 保存思维导图
        if task.get('mindmap'):
            mindmap_path = os.path.join(save_dir, 'mindmap.md')
            with open(mindmap_path, 'w', encoding='utf-8') as f:
                f.write(task['mindmap'])
                
        return jsonify({
            "message": "保存成功",
            "path": save_dir
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 添加新的问答接口
@app.route('/api/ask', methods=['POST'])
def ask_question():
    try:
        data = request.json
        if not data or 'taskId' not in data or 'question' not in data:
            return jsonify({"error": "无效的请求数据"}), 400
            
        task_id = data.get('taskId')
        question = data.get('question')
        
        if task_id not in tasks:
            return jsonify({"error": "找不到相关内容"}), 404
            
        task = tasks[task_id]
        if 'original_text' not in task:
            return jsonify({"error": "没有可用的内容来回答问题"}), 400
            
        # 预处理文本
        original_text = task['original_text']
        
        # 基本清理
        original_text = '\n'.join(line for line in original_text.split('\n') if line.strip())
        
        prompt = f"""请尽可能基于以下视频内容回答用户问题。如果内容有不清晰的地方，请根据上下文进行合理推断。

要求：
1. 优先使用明确的内容回答
2. 对于不清晰的部分，根据上下文推断含义
3. 如果必须进行推断，请明确标注"[推]"
4. 如果无法推断，再说明无法回答
5.回答格需要清晰，方便读者阅读，有分段分行

回答格式：
1. 【原文依据】
   - 引用视频中的明确相关内容
   - 标注关键信息的位置（开头/中间/结尾）

2. 【详细解答】
   - 基于明确内容的解释
   - 必要时加入合理推断，并标注[推断]
   - 分步骤说明具体做法

3. 【补充信息】
   - 指出哪些是明确的信息
   - 哪些是推断的内容
   - 哪些还需要进一步确认

4. 【建议】
   - 如何验证推断的正确性
   - 建议进一步了解的内容
   - 实践时的注意事项

原文内容：
{original_text}

用户问题：
{question}

注意：即使内容不够清晰，也请量提供有价值的回答。可以根据上下文和专业知识进行合理推断，但要明确标注推断的部分。"""

        response = requests.post(API_URL, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }, json={
            "model": "claude-3-5-sonnet-20240620",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question}
            ]
        })
        
        if not response.ok:
            return jsonify({"error": "AI服务暂时不可用，请稍后重试"}), 500
            
        try:
            answer = response.json()['choices'][0]['message']['content']
            
            # 确保返回的数据格式正确
            return jsonify({
                "answer": answer  # 确保 answer 不为 None
            })
            
        except Exception as e:
            return jsonify({"error": "处理AI回复时出错"}), 500
            
    except Exception as e:
        print(f"处理问题时出错: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8080)