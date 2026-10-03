# TÀI LIỆU KỸ THUẬT TOÀN DIỆN — SEEDVIS STANDALONE v1.0.1
**Hệ thống Tự động hóa Sản xuất Video Shopee Affiliate bằng AI (Google Veo 3.1)**

---

## 1. TỔNG QUAN KIẾN TRÚC

### 1.1 Mục tiêu
Seedvis Standalone là phần mềm desktop độc lập, tự động hóa 100% quy trình sản xuất video ngắn (TikTok, Reels, Shopee Video) từ danh sách sản phẩm Shopee nhận qua Server Database trung tâm.

### 1.2 Cấu trúc Thư mục
```
E:\ThinAptm0707\0 - Seedvis\
├── seedvis_app.py          # Giao diện chính (CustomTkinter) + Worker điều phối
├── shopeevideo.py           # Thư viện hỗ trợ: template prompt, FFmpeg, TTS, API Veo
├── run_seedvis.bat          # File chạy phần mềm (pythonw, ẩn CMD)
├── install.bat              # Bộ cài đặt tự động môi trường (Python, pip, FFmpeg)
├── update.bat               # Cập nhật phiên bản mới nhất từ GitHub
├── update-github.bat        # Đẩy code lên GitHub (thincole/seedvis)
├── requirements.txt         # Danh sách 7 thư viện Python cần thiết
├── .gitignore               # Chặn push file nhạy cảm (settings, log, temp)
├── seedvis_settings.json    # Cấu hình phiên làm việc (tự động lưu/tải)
├── log.txt                  # Nhật ký (tự xóa trắng mỗi lần khởi động)
├── temp_render/             # Thư mục đệm ảnh/video tạm (tự dọn định kỳ)
└── output_seedvis/          # Thư mục lưu video thành phẩm
```

### 1.3 Luồng Vận hành Tổng quan
```
[Server Database] ──claim-jobs──▶ [Nhận Lô SP]
                                       │
                                       ▼
                              [Tải Ảnh từ CDN Shopee]
                                       │
                                       ▼
                          [AI Sinh Prompt (Gemini/Groq/Template)]
                            + Gemini Vision soi ảnh gốc (Base64)
                            + Khóa Giải Phẫu Bàn Tay
                                       │
                                       ▼
                          [Gửi Seedvis API (Veo 3.1 Image-to-Video)]
                                       │
                                       ▼
                          [Polling tiến trình mỗi 6s (timeout 10 phút)]
                                       │
                                       ▼
                          [Tải Video Segment từ CDN]
                                       │
                                       ▼
                          [Ghép Outro Ảnh 12s (FFmpeg) — nếu bật]
                                       │
                                       ▼
                          [Đặt tên + Lưu vào output_seedvis/]
                                       │
                                       ▼
                          [Báo cáo "completed" về Server Database]
```

---

## 2. LỚP CHÍNH: `SeedvisApp(ctk.CTk)`

### 2.1 Thuộc tính Trạng thái Quan trọng

| Thuộc tính | Kiểu | Mô tả |
| :--- | :--- | :--- |
| `self.settings` | dict | Toàn bộ cấu hình nạp từ `seedvis_settings.json` |
| `self.gemini_keys` | list[str] | Danh sách API key Google Gemini (xoay vòng) |
| `self.groq_keys` | list[str] | Danh sách API key Groq Cloud (xoay vòng) |
| `self._ai_key_lock` | threading.Lock | Bảo vệ xoay vòng key AI giữa các luồng |
| `self._gemini_key_rr_idx` | int | Con trỏ Round-Robin cho Gemini key |
| `self._seed_claimed_products` | list[dict] | Danh sách SP đã nhận từ Database |
| `self._seed_running` | bool | Cờ đánh dấu đang chạy tạo video |
| `self._seed_stop_flag` | bool | Cờ yêu cầu dừng |
| `self._seed_completion_times` | deque | Ghi timestamp hoàn thành để tính tốc độ rolling |
| `self._ui_queue` | queue.Queue | Hàng đợi điều phối UI thread-safe |
| `self._ffmpeg_sem` | Semaphore | Giới hạn số tiến trình FFmpeg đồng thời |

### 2.2 Các Phương thức Cốt lõi

| Phương thức | Chức năng |
| :--- | :--- |
| `__init__()` | Khởi tạo cửa sổ 1260x860, theme Light, tải cấu hình, xóa log, khởi chạy temp cleaner |
| `_load_settings()` | Nạp `seedvis_settings.json`, kế thừa key từ `settings.json` gốc |
| `_save_settings()` | Lưu trạng thái tất cả widget vào `seedvis_settings.json` |
| `_build_ui()` | Dựng layout UI gồm các Card bo tròn, bảng SP, khung log |
| `_seed_api_call(method, path, data)` | Gửi HTTP request kèm header `X-API-Key` đến Server |
| `_seed_claim_jobs()` | Nhận lô SP: `POST /api/thinaptm/claim-jobs` |
| `_seed_release_jobs()` | Giải phóng SP kẹt: `POST /api/thinaptm/release-jobs` |
| `_seed_clear_violations()` | Xóa SP bị `"vi phạm cs"` khỏi danh sách UI |
| `_seed_download_image(url, path)` | Tải ảnh SP từ CDN Shopee qua `urllib.request` |
| `_seed_ai_gen_prompts(...)` | Gọi Gemini/Groq sinh prompt Veo 3.1 + Vision + Anatomy Lock |
| `_run_ghep_anh_12s(video, img, out)` | FFmpeg ghép outro ảnh kéo dài video thành 12s |
| `_seed_start_work(api_key)` | Điều phối đa luồng trung tâm xử lý toàn bộ quy trình |
| `_start_temp_cleaner()` | Thread nền dọn rác `temp_render` định kỳ |
| `_on_closing()` | Thu nhỏ xuống khay hệ thống (pystray) thay vì tắt |
| `_poll_ui_queue()` | Định tuyến cập nhật UI từ worker threads về luồng chính (100ms) |

---

## 3. QUY TRÌNH CHI TIẾT

### 3.1 Claim Sản Phẩm từ Database
```python
POST /api/thinaptm/claim-jobs
Body: {
    "market": "PH",           # Mã quốc gia (PH, VN, ID, TH, MY, SG, TW)
    "clientId": "XEON-CT2A_822d66",
    "limit": 20,              # Số SP nhận mỗi lượt
    "sortBy": "sold",         # Ưu tiên: "sold" hoặc "commission"
    "min_item_id": 40000000000,
    "min_commission": 1.0
}
```
Server PostgreSQL đánh dấu SP sang `processing`, kèm `claimed_by = clientId`.

### 3.2 Sinh Prompt AI (4 chế độ)

| Chế độ | Mô tả |
| :--- | :--- |
| **Template (mặc định)** | Gọi `SV.build_tvc_prompt()` sinh prompt TVC 8s tinh gọn |
| **Prompt A + B** | Nếu 1 segment → dùng Template. Nếu >1 segment → `SV.build_video_prompts_fallback` |
| **Gemini** | Gọi `_seed_ai_gen_prompts(mode="gemini")` + Vision + Anatomy Lock |
| **Groq** | Gọi `_seed_ai_gen_prompts(mode="groq")` + Anatomy Lock |

### 3.3 Thuật toán Gemini Multimodal Vision (Soi Ảnh Gốc)

Khi chế độ AI là Gemini và có file ảnh sản phẩm:

```python
parts = []
# Gửi ảnh gốc cho Gemini "nhìn thấy"
if img_path and os.path.exists(img_path):
    with open(img_path, "rb") as imf:
        b64_img = base64.b64encode(imf.read()).decode('utf-8')
    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_img}})

    sys_prompt += """
    [VISION ANALYSIS]: Look at the attached product image.
    If the image already shows hands holding the product (POV),
    you MUST LOCK the perspective to POV and absolutely DO NOT
    add a presenter or face.
    If it's a standalone product, you can use a presenter but
    strictly LOCK hand anatomy to 2 hands attached to shoulders.
    """

parts.append({"text": sys_prompt})
payload = {
    "contents": [{"parts": parts}],
    "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800}
}
```

**Mục đích**: Gemini sẽ "soi" ảnh gốc, nếu thấy ảnh đã có tay cầm SP (POV) thì ép Veo 3.1 tiếp tục góc nhìn đó, không vẽ thêm người thứ 2 → triệt tiêu lỗi 3 tay.

### 3.4 Thuật toán Khóa Giải Phẫu Bàn Tay (Anatomy Lock)

**Nguyên nhân lỗi**: Ảnh SP Shopee thường có tay cầm SP (POV). Nếu prompt yêu cầu thêm người mẫu, Veo 3.1 giữ nguyên 2 tay từ ảnh gốc + vẽ thêm người mẫu với 2 cánh tay mới → 3-4 cánh tay dị tật.

**Giải pháp 3 lớp**:

1. **Khóa Người Mẫu (Presenter Lock)**:
   - Giới hạn đúng 2 cánh tay gắn liền vai, đúng 2 bàn tay với 5 ngón riêng biệt.
   - Phân vai cụ thể: Tay trái cầm đáy SP ngang ngực, tay phải cử chỉ/chạm bề mặt.
   - Tuyệt đối cấm tay thứ 3 từ ngoài khung hình thò vào.

2. **Khóa Góc Nhìn POV (khi ảnh gốc đã có tay)**:
   - Tiếp tục chuyển động từ góc nhìn thứ nhất nhìn xuống mặt bàn.
   - Kế thừa đặc điểm (màu áo, tay áo, màu da, móng tay) từ ảnh gốc.
   - **TUYỆT ĐỐI CẤM** thêm mặt/đầu/thân người mẫu đằng sau.

3. **Bộ lọc an toàn (Positive Reinforcement)**:
   - **KHÔNG ĐƯỢC** dùng từ phủ định ghê rợn (`mutated`, `deformed`, `extra limbs`) trong prompt gửi Veo 3.1 → sẽ bị chặn bởi Safety Filter (lỗi `generation_failed`).
   - Thay vào đó mô tả tích cực: *"two perfectly normal hands"*, *"natural five fingers"*.

### 3.5 Gửi Tạo Video qua Seedvis API

```python
POST https://seedvis.com/api/v1/developer/generations
Headers:
    Authorization: Bearer <seedvis_api_key>
    Content-Type: application/json
    Idempotency-Key: <uuid4>
    User-Agent: <SEEDVIS_UA>

Body:
{
    "model": "Veo-3.1",
    "prompt": "<AI_PROMPT>",
    "mode": "image-to-video",
    "image": {
        "data": "<BASE64_IMAGE>",
        "file_name": "<item_id>.jpg"
    },
    "aspect_ratio": "9:16",
    "duration": "8s",
    "count": 1,
    "upscale_video": "none"
}
```

### 3.6 Polling Tiến trình

```python
GET https://seedvis.com/api/v1/developer/generations/{job_id}?wait=60
```
- Lặp mỗi 6 giây, timeout tối đa 600 giây (10 phút).
- Kiểm tra `is_final`:
  - `status in ("completed", "succeeded")` → Lấy `outputs[0].url`.
  - Lỗi `policy/violation/filter/safety` → Trả về `"violation"`.
  - Lỗi `)]}'` → Lỗi nội bộ Seedvis, cho phép thử lại.

### 3.7 Hậu kỳ Video (FFmpeg)

**Ghép Outro Ảnh 12s** (`_run_ghep_anh_12s`):
- Kéo dài video 8s thành ~12s bằng cách nối thêm 3.5s-4s ảnh sản phẩm.
- Hiệu ứng chuyển động ngẫu nhiên (Zoom In/Out/Pan).
- Chèn text ngẫu nhiên trên ảnh outro.

**Ghép Nối Multi-Segment** (`SV.concat_videos`):
- Ưu tiên Stream Copy (`-c copy -movflags +faststart`) → gần như tức thì.
- Fallback Re-encode (`-c:v libx264 -preset superfast -crf 23`).

**Khử Watermark** (`SV.remove_veo_watermark`):
- Tính tọa độ góc phải dưới (nơi Seedvis chèn logo).
- Chạy bộ lọc FFmpeg `delogo=x=...:y=...:w=...:h=...`.

---

## 4. XỬ LÝ LỖI & RETRY

### 4.1 Cơ chế Retry Cycles
- Khi gặp lỗi tạm thời, biến `prod["_cycles"]` tăng dần.
- Nếu `_cycles < 3`: Đẩy SP vào hàng đợi thử lại.
- Sau 3 lần thất bại: Đánh dấu `error`, tag đỏ `❌`.

### 4.2 Bảng Mã Lỗi API

| Mã HTTP | Ý nghĩa | Xử lý |
| :--- | :--- | :--- |
| `401` | Sai API Key | Dừng job, hiện cảnh báo |
| `402` | Hết credit Seedvis | Bật `_seed_stop_flag = True`, dừng toàn bộ hàng đợi |
| `422` | Vi phạm chính sách Google | Đánh dấu `"vi phạm cs"`, tag vàng `⚠️` |
| `429` | Rate Limit | Backoff: `wait = min(20 * (attempt + 1), 60)s` |
| `500/502/504` | Lỗi server | Thử lại tối đa 5 lần, mỗi lần cách 4s |
| `not_found` | Google task dropped | Credit được hoàn, tự động retry |
| `generation_failed` | Veo 3.1 bị chặn Safety | Retry, kiểm tra prompt có từ cấm |

### 4.3 Vi Phạm Chính Sách (Rule #3 AGENTS.md)
- Nhận diện: `PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED`, `PUBLIC_ERROR_AUDIO_FILTERED`.
- Chuyển trạng thái: `prod["_status"] = "vi phạm cs"`.
- Icon cảnh báo vàng `⚠️ vi phạm cs`.
- Nút xóa chuyên dụng: **`🗑 Xóa Vi Phạm CS`** (màu đỏ nhạt `#E57373`).

---

## 5. HỆ THỐNG BẢO VỆ KHI CHẠY 24/7

### 5.1 Minimize to Tray (pystray)
- Bấm `X` → ẩn cửa sổ (`withdraw()`), hiện icon khay hệ thống.
- Menu: **"Hiển thị cửa sổ"** / **"Thoát hoàn toàn"**.
- Tránh tắt nhầm phần mềm khi chạy 24/7.

### 5.2 Giải phóng Job khi Tắt
- Khi chọn **"Thoát hoàn toàn"**:
  1. Lưu cài đặt (`_save_settings()`).
  2. Gọi API `POST /api/thinaptm/release-jobs` trả SP về `pending`.
  3. Dọn sạch `temp_render/` (Rule #8).
  4. Hủy cửa sổ (`self.destroy()`).

### 5.3 Dọn Dẹp Tự Động (`_start_temp_cleaner`)
- Thread daemon chạy ngầm, chu kỳ đọc từ `seedvis_clean_interval` (mặc định 60 phút).
- Chỉ xóa file cũ hơn 10 phút (`time.time() - mtime > 600s`) → bảo vệ file đang xử lý.
- Log: `🧹 [Auto-Clean] Đã dọn dẹp {count} file rác trong temp_render.`

### 5.4 Giới hạn Hiệu năng
- **FFmpeg Semaphore**: `max(2, cpu_count // 2)` luồng đồng thời.
- **FFmpeg Threads**: `-threads 2` mỗi tiến trình (chống lag máy).
- **Subprocess**: Luôn dùng `creationflags=0x08000000` để ẩn CMD popup.

---

## 6. BẢNG CẤU HÌNH SETTINGS (`seedvis_settings.json`)

| Khóa | Kiểu | Mặc Định | Ý Nghĩa |
| :--- | :--- | :--- | :--- |
| `sv_server_url` | string | `"http://100.79.170.67:3000"` | Địa chỉ Server Database |
| `sv_api_key` | string | `""` | API Key Server Database |
| `sv_client_id` | string | `"client_seedvis"` | Tên máy client |
| `seedvis_api_key` | string | `""` | API Key Seedvis (`sv_live_...`) |
| `seedvis_model` | string | `"Veo-3.1"` | Model tạo video |
| `seedvis_duration` | string | `"8s"` | Thời lượng 1 clip |
| `seedvis_upscale` | string | `"none"` | Nâng độ phân giải |
| `seedvis_threads` | string | `"12"` | Số luồng worker (1-64) |
| `seedvis_aspect` | string | `"Dọc 9:16"` | Tỉ lệ khung hình |
| `seedvis_scene` | string | `"🎲 Random"` | Khung cảnh bối cảnh |
| `seedvis_total_dur` | string | `"16s"` | Tổng thời lượng video |
| `seedvis_lang` | string | `"Tiếng Philippines"` | Ngôn ngữ thoại |
| `seedvis_review_style` | string | `"🎲 Random"` | Phong cách review |
| `seedvis_ai_prompt` | string | `"Prompt A + B"` | Chế độ sinh prompt |
| `seedvis_del_img` | bool | `true` | Xóa ảnh sau khi xong |
| `seedvis_ghep_anh` | bool | `false` | Ghép outro ảnh 12s |
| `seedvis_naming` | string | `"Theo Item ID"` | Cách đặt tên video |
| `seedvis_out_dir` | string | `"<HERE>/output_seedvis"` | Thư mục xuất video |
| `seedvis_claim_limit` | string | `"20"` | Số SP nhận mỗi lượt |
| `seedvis_sort_by` | string | `"Số bán cao nhất"` | Tiêu chí ưu tiên |
| `seedvis_market` | string | `"PH"` | Thị trường (`PH/VN/ID/TH/MY/SG/TW`) |
| `seedvis_min_item_id` | string | `"40000000000"` | Lọc item_id nhỏ nhất |
| `seedvis_min_commission` | string | `"1"` | Hoa hồng % nhỏ nhất |
| `seedvis_clean_interval` | string | `"60"` | Phút dọn rác tự động |
| `gemini_keys` | list[str] | `[]` | Danh sách Gemini API Key |
| `groq_api_key` | string | `""` | Groq API Key |

---

## 7. MODULE HỖ TRỢ: `shopeevideo.py`

### 7.1 Hằng số
- **`DURATION_MAP`**: `{8: [0], 16: [0,1], 24: [2,3,4]}` — Mapping thời lượng → số segment.
- **`SCENES`**: 13 bối cảnh preset (Kho hàng, Siêu thị, Studio, Phòng khách, Văn phòng, Công viên, Photo Studio, Showroom, Quán café, Bàn unboxing, Bàn so sánh, Livestream studio, Nhà máy).
- **`CONTENT_OPTIONS`**: Review kho hàng, POV, UGC, Unboxing, Demo công dụng, Review tự nhiên, So sánh.

### 7.2 Hàm Quan trọng

| Hàm | Chức năng |
| :--- | :--- |
| `build_tvc_prompt(name, lang, style)` | Sinh prompt TVC 8s tinh gọn |
| `build_video_prompts_fallback(...)` | Sinh chuỗi prompt multi-segment với handoff pose |
| `clean_product_title(title)` | Lọc từ khóa rủi ro chính sách, cắt gọn 4 từ |
| `concat_videos(paths, output)` | Ghép nối video (stream copy → fallback re-encode) |
| `remove_veo_watermark(path)` | Khử logo Seedvis/Veo góc phải dưới |
| `generate_audio_file(text, path, voice)` | TTS miễn phí qua `edge-tts` |
| `generate_gemini_audio_file(...)` | TTS cao cấp qua Google GenAI SDK |
| `_apply_pov_or_unbox_transform(prompt)` | Biến đổi prompt sang POV/Unboxing |
| `_get_my_character_style()` | Trả về `"male"` cho thị trường Malaysia (MY) |

### 7.3 Làm sạch Tên Sản Phẩm (`clean_product_title`)
- Bóc tách thẻ ngoặc: `【 】 [ ] ( )`.
- Lọc từ rủi ro: `100%`, `chính hãng`, `replica`, `fake`, `iphone`, `nike`, `bra`, `bikini`, `nude`, `medicine`, `knife`, `whitening`, `weight loss`...
- Cắt gọn tối đa 4 từ cô đọng nhất.

---

## 8. GIAO DIỆN NGƯỜI DÙNG (UI)

### 8.1 Layout Architecture
- **Nền**: `BG = "#f5f7fb"`, Font mặc định hệ thống.
- **Card 1 — Kết nối Server**: URL Server (260), API Key (180), Client ID (160).
- **Card 2 — Seedvis API**: API Key (380, che `*`), Model, Thời lượng clip, Upscale, Luồng.
- **Card 3 — Cài đặt Video**:
  - Hàng 1: Tỉ lệ, Khung cảnh, Độ dài, Ngôn ngữ.
  - Hàng 2: Kiểu review, AI Prompt, `🧪 Test Prompt`, `🔑 AI Keys`, Checkbox Xóa ảnh, Checkbox Ghép ảnh 12s, Ô nhập phút dọn rác.
  - Hàng 3: Đặt tên video, Đường dẫn lưu video.
- **Card 4 — Nhận Lô SP**: Số lượng, Ưu tiên, Thị trường, ItemID min, Hoa hồng min, `📥 Nhận SP`, `🔄 Giải phóng SP kẹt`, `🗑 Xóa Vi Phạm CS`.
- **Phần Thân — 2 cột 50:50**:
  - Trái: Danh sách SP + tag màu (xanh/đỏ/cam/vàng) + tốc độ rolling `⚡ X.X video/phút`.
  - Phải: Nhật ký log (tự cuộn, tối đa 1000 dòng).
- **Phần Đáy**: Progress bar + `▶ Bắt đầu tạo video` + `⏹ Dừng` + `📂 Mở thư mục`.

### 8.2 Tag Màu Trạng thái
| Tag | Màu | Ý nghĩa |
| :--- | :--- | :--- |
| `seed_success` | `#1B7D2C` (Xanh lá) | `✅` Video tạo thành công |
| `seed_error` | `#D32F2F` (Đỏ) | `❌` Lỗi không thể sửa |
| `seed_running` | `#E65100` (Cam) | `⏳` Đang xử lý |
| `seed_violation` | `#F57F17` (Vàng cam) | `⚠️` Vi phạm chính sách |

---

## 9. API ENDPOINTS SERVER DATABASE

| Method | Endpoint | Body | Mô tả |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/thinaptm/claim-jobs` | `{market, clientId, limit, sortBy, min_item_id, min_commission}` | Nhận lô SP |
| `POST` | `/api/thinaptm/release-jobs` | `{clientId}` | Trả SP chưa xử lý về pending |
| `POST` | `/api/thinaptm/auto-release-stuck` | `{hours: 2}` | Giải phóng SP kẹt >2 giờ |
| `POST` | `/api/thinaptm/complete-job` | `{itemId, status, tool, videoFile}` | Báo cáo hoàn tất/lỗi/vi phạm |
| `POST` | `/api/thinaptm/release-single-job` | `{itemId}` | Trả 1 SP cụ thể về pending |

---

## 10. CÁC VẤN ĐỀ ĐÃ PHÁT HIỆN VÀ KHẮC PHỤC

### 10.1 Lỗi SyntaxError dòng 1448 (NGHIÊM TRỌNG)
- **Vấn đề**: Dấu `"` bên trong f-string xung đột với dấu `"` bọc ngoài.
- **Biểu hiện**: Phần mềm không thể khởi động.
- **Khắc phục**: Chuyển thành dấu nháy đơn `'...'` cho các cụm từ bên trong.

### 10.2 Lỗi `generation_failed` liên tục
- **Vấn đề**: Prompt chứa Negative Directives (`extra limbs, mutated, deformed...`) kích hoạt Safety Filter của Google Veo 3.1.
- **Khắc phục**: Chuyển sang mô tả tích cực (Positive Reinforcement).

### 10.3 Lỗi 3 tay / dị tật bàn tay
- **Vấn đề**: Ảnh gốc POV + Prompt yêu cầu người mẫu → Veo vẽ thêm cánh tay.
- **Khắc phục**: Tích hợp Gemini Vision soi ảnh gốc + Anatomy Lock.

### 10.4 Phần mềm tự tắt khi chạy 24/7
- **Vấn đề**: `CHAY.bat` chứa `taskkill /f /im pythonw.exe` giết nhầm Seedvis.
- **Khắc phục**: Tách Seedvis thành bản độc lập, chạy bằng `pythonw` ẩn CMD.

### 10.5 Race Condition file tạm trùng tên
- **Vấn đề**: Nhiều luồng cùng dùng `{item_id}.jpg` → luồng này xóa file của luồng kia.
- **Khắc phục**: Đổi sang `{item_id}_{queue_index}` cho tất cả file tạm.

---

## 11. THƯ VIỆN PYTHON CẦN THIẾT

| Thư viện | Phiên bản | Chức năng |
| :--- | :--- | :--- |
| `customtkinter` | latest | Giao diện Desktop hiện đại |
| `pillow` | latest | Xử lý ảnh + tạo icon tray |
| `pystray` | latest | Icon khay hệ thống (minimize to tray) |
| `edge-tts` | latest | Text-to-Speech miễn phí (Microsoft Edge) |
| `google-genai` | latest | Google Gemini SDK (Vision + TTS) |
| `google-generativeai` | latest | Google Generative AI SDK |
| `groq` | latest | Groq Cloud API (Llama 3) |

**Công cụ hệ thống**: Python 3.10+, FFmpeg (ghép video, khử watermark).

---

*Tài liệu được cập nhật lần cuối: 2026-09-21 01:27 — Seedvis Standalone v1.0.1*
