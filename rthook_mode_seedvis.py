# PyInstaller runtime hook: chạy trước seedvis_app.py trong bản exe Seedvis.exe
# → khóa app ở chế độ chỉ dùng Seedvis (Veo 3.1).
import os
os.environ["SEEDVIS_APP_MODE"] = "seedvis"
