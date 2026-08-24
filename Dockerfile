# 用于 Hugging Face Spaces / 任意容器平台的构建文件
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces 等平台会注入 PORT 环境变量（默认 7860）
ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
