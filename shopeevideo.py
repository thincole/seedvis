"""
Shopee Video Creator v3 — Tạo video review sản phẩm từ ảnh SP + ảnh người mẫu + Google Flow AI.
Luồng: Ảnh SP + Ảnh mẫu + Khung cảnh → Google Flow tạo ảnh hoàn thiện
       → Sinh N prompt liền mạch → N video thành phần (i2v) → FFmpeg concat → 1 video hoàn chỉnh.
Không cần scrape Shopee — user cung cấp ảnh + tên SP trực tiếp.
"""
import os, json, time, threading, re, traceback, random, base64, subprocess, tempfile

# ==================== KHUNG CẢNH PRESET ====================
# Mỗi tuple: (tên hiển thị, mô tả tiếng Anh, mô tả tiếng Việt)
SCENES = [
    ("📦 Tổng kho hàng hóa",
     "in a large organized warehouse with neatly stacked product shelves behind, bright industrial lighting",
     "trong nhà kho lớn ngăn nắp với các kệ sản phẩm xếp gọn phía sau, ánh sáng công nghiệp sáng rõ"),
    ("🛒 Siêu thị hiện đại",
     "inside a bright modern supermarket with shiny product displays, spacious shopping environment",
     "bên trong siêu thị hiện đại sáng sủa với các gian hàng trưng bày sản phẩm bóng loáng, không gian mua sắm rộng rãi"),
    ("🎥 Phòng review chuyên nghiệp",
     "in a professional product review studio with clean white background and softbox lighting setup",
     "trong phòng quay đánh giá sản phẩm chuyên nghiệp với phông nền trắng sạch và hệ thống đèn softbox"),
    ("🛋 Phòng khách sang trọng",
     "in a luxurious modern living room with leather sofa, warm golden ambient lighting, elegant decor",
     "trong phòng khách hiện đại sang trọng với sofa da, ánh sáng vàng ấm áp, nội thất thanh lịch"),
    ("💼 Văn phòng hiện đại",
     "in a stylish modern office with glass desk, ergonomic chair, minimalist decor and green plants",
     "trong văn phòng hiện đại phong cách với bàn kính, ghế công thái học, trang trí tối giản và cây xanh"),
    ("🌳 Ngoài trời công viên",
     "outdoors in a beautiful green park with natural sunlight filtering through tree canopy",
     "ngoài trời trong công viên xanh mát với ánh nắng tự nhiên xuyên qua tán cây"),
    ("📸 Studio chụp ảnh",
     "in a professional photo studio with grey backdrop, ring light, clean minimal setup",
     "trong studio chụp ảnh chuyên nghiệp với phông nền xám, đèn ring light, bố trí gọn gàng tối giản"),
    ("🏬 Showroom trưng bày",
     "in an upscale product showroom with glass display shelves and LED spotlight illumination",
     "trong showroom trưng bày sản phẩm cao cấp với kệ kính và đèn LED chiếu điểm"),
    ("☕ Quán café hiện đại",
     "in a stylish modern cafe with wooden table, warm ambient light, cozy relaxing atmosphere",
     "trong quán café hiện đại phong cách với bàn gỗ, ánh sáng ấm áp, không gian thư giãn ấm cúng"),
    ("� Bàn unboxing",
     "at a clean unboxing desk with brown kraft paper, scissors, and packaging materials, bright overhead lighting",
     "tại bàn unboxing gọn gàng với giấy kraft nâu, kéo và vật liệu đóng gói, ánh sáng trên đầu sáng rõ"),
    ("⚖ Bàn so sánh sản phẩm",
     "at a product comparison table with clean white surface, multiple items neatly arranged side by side, professional overhead lighting",
     "tại bàn so sánh sản phẩm với mặt bàn trắng sạch, nhiều sản phẩm xếp gọn cạnh nhau, ánh sáng chuyên nghiệp từ trên"),
    ("📱 Studio livestream",
     "in a professional livestream studio with ring light, camera tripod, colorful LED backdrop, and product display shelf",
     "trong studio livestream chuyên nghiệp với đèn ring light, chân tripod camera, phông nền LED nhiều màu, và kệ trưng bày sản phẩm"),
    ("🏭 Nhà máy sản xuất",
     "inside the actual factory or manufacturing facility where THIS SPECIFIC product is made — "
     "the factory type MUST match the product category: if skincare/cosmetics then a clean sterile cosmetics lab with stainless steel mixing tanks and filling machines; "
     "if electronics/tech then a modern electronics assembly line with circuit boards and robotic arms; "
     "if food/beverage then a hygienic food processing plant with conveyor belts and packaging machines; "
     "if fashion/clothing then a textile factory with sewing machines and fabric rolls; "
     "if household/cleaning then a chemical plant with large vats and bottling lines. "
     "Workers in professional uniforms and hairnets, bright industrial fluorescent lighting, quality control stations visible, "
     "conveyor belts with products being packaged, large-scale production atmosphere proving product authenticity and scale",
     "bên trong nhà máy sản xuất thực tế nơi chính sản phẩm này được làm ra — "
     "loại nhà máy PHẢI khớp với ngành hàng: nếu mỹ phẩm thì phòng lab sạch với bồn trộn inox và máy chiết rót; "
     "nếu điện tử thì dây chuyền lắp ráp hiện đại với bo mạch và cánh tay robot; "
     "nếu thực phẩm thì nhà máy chế biến vệ sinh với băng chuyền và máy đóng gói; "
     "nếu thời trang thì xưởng may với máy khâu và cuộn vải; "
     "nếu gia dụng/tẩy rửa thì nhà máy hóa chất với bồn lớn và dây chuyền đóng chai. "
     "Công nhân mặc đồng phục chuyên nghiệp và đội mũ lưới, ánh sáng huỳnh quang công nghiệp sáng rõ, "
     "trạm kiểm tra chất lượng, băng chuyền với sản phẩm đang được đóng gói, không khí sản xuất quy mô lớn chứng minh tính chân thực"),
]

SCENE_NAMES = [s[0] for s in SCENES]
SCENE_MAP_EN = {s[0]: s[1] for s in SCENES}
SCENE_MAP_VI = {s[0]: s[2] for s in SCENES}
SCENE_MAP = SCENE_MAP_EN  # backward compat
SCENE_OPTIONS = ["🎲 Random"] + SCENE_NAMES

DURATION_OPTIONS = ["16s", "24s"]

# ==================== ĐỊNH DẠNG NỘI DUNG (CONTENT FORMATS) ====================
CONTENT_OPTIONS = ["Review kho hàng", "POV", "UGC", "Unboxing", "Demo công dụng"]

CONTENT_MAP_VI = {
    "Review kho hàng": "[ĐỊNH DẠNG NỘI DUNG - REVIEW KHO HÀNG: Góc quay vừa/rộng trong tổng kho ngăn nắp với các kệ hàng xếp cao đằng sau. Người mẫu đứng tự tin giữa kho hàng, vừa cầm sản phẩm vừa chỉ tay tự hào giới thiệu số lượng lớn hàng sẵn có.]\n\n",
    "POV": "[ĐỊNH DẠNG NỘI DUNG - POV GÓC NHÌN THỨ NHẤT: Góc quay từ tầm mắt người xem nhìn xuống bàn. Không hiện mặt người mẫu mà chỉ tập trung cận cảnh đôi tay đang cầm, xoay lật và thao tác trực tiếp trên sản phẩm. Camera chuyển động theo sát thao tác bàn tay.]\n\n",
    "UGC": "[ĐỊNH DẠNG NỘI DUNG - UGC KHÁCH HÀNG TỰ QUAY: Phong cách máy quay điện thoại cầm tay gia đình tự nhiên, không gian góc phòng ngủ/bàn học ấm áp gần gũi. Người mẫu đưa sản phẩm sát camera với nụ cười thân thiện, mang lại cảm giác đánh giá chân thực như bạn bè chia sẻ với nhau.]\n\n",
    "Unboxing": "[ĐỊNH DẠNG NỘI DUNG - UNBOXING ĐẬP HỘP: Góc máy từ trên xuống mặt bàn. Đôi tay tỉ mỉ bóc gói hàng kraft, tháo lớp bọc chống sốc và hé lộ sản phẩm cùng phụ kiện nguyên vẹn bên trong. Ánh sáng nét rõ, tập trung vào trải nghiệm đập hộp.]\n\n",
    "Demo công dụng": "[ĐỊNH DẠNG NỘI DUNG - DEMO CÔNG DỤNG THỰC TẾ: Camera cận cảnh Macro tập trung 100% vào việc thử nghiệm tính năng, độ bền, kết cấu và hiệu quả sử dụng thực tế của sản phẩm. Thao tác dứt khoát, hình ảnh cực kỳ sắc nét.]\n\n",
    "Review tự nhiên": "[ĐỊNH DẠNG NỘI DUNG - REVIEW TỰ NHIÊN: Người mẫu đứng tự nhiên cầm sản phẩm, di chuyển thoải mái trong khung cảnh. Camera handheld có rung nhẹ tự nhiên, góc medium shot. Ánh sáng tự nhiên từ cửa sổ hoặc ngoài trời, không dàn dựng studio. Phong cách đời thường, năng động, chân thực như đang chia sẻ với bạn bè.]\n\n",
    "So Sánh/Đánh Giá": "[ĐỊNH DẠNG NỘI DUNG - SO SÁNH ĐÁNH GIÁ: Người mẫu cầm sản phẩm đặt cạnh các vật tham chiếu để so sánh kích thước, chất lượng. Camera chuyển đổi giữa góc rộng (thấy cả hai) và cận cảnh (chi tiết từng sản phẩm). Ánh sáng đều, trung tính. Biểu cảm phân tích, suy nghĩ chân thực — gật đầu hài lòng hoặc nhăn mặt nhẹ khi so sánh.]\n\n",
}
# Alias: tên dropdown mới → key cũ trong CONTENT_MAP
_CONTENT_STYLE_ALIAS_VI = {
    "POV (Góc nhìn thứ nhất)": "POV",
    "UGC Authentic": "UGC",
    "Demo Công Dụng": "Demo công dụng",
    "Ngồi Review": "Review tự nhiên",  # Ngồi Review xử lý riêng bằng constraint, content dùng tự nhiên
}
for _alias, _target in _CONTENT_STYLE_ALIAS_VI.items():
    CONTENT_MAP_VI[_alias] = CONTENT_MAP_VI[_target]

CONTENT_MAP_EN = {
    "Review kho hàng": "[CONTENT FORMAT - WAREHOUSE REVIEW: Wide medium shot inside a clean, massive industrial warehouse with neatly organized product shelves stacked high in the background. Presenter stands confidently in the warehouse, holding the product while proudly gesturing toward the bulk inventory.]\n\n",
    "POV": "[CONTENT FORMAT - POV FIRST PERSON: First-person POV camera angle from reviewer's eye level looking down at desk. Focus strictly on smooth natural hands holding, turning, and operating the product. No face shown. Camera follows hand movements closely.]\n\n",
    "UGC": "[CONTENT FORMAT - UGC USER GENERATED: Handheld smartphone camera aesthetic, relatable cozy bedroom/desk setting. Presenter holds product close to camera with a warm friendly smile, authentic candid review atmosphere like a friend sharing a recommendation.]\n\n",
    "Unboxing": "[CONTENT FORMAT - UNBOXING: Top-down desk camera angle. Hands carefully opening kraft cardboard package, unwrapping protective bubble wrap, and revealing the pristine product and accessories inside. Crisp clear lighting focused on the unboxing experience.]\n\n",
    "Demo công dụng": "[CONTENT FORMAT - FEATURE DEMO: Extreme close-up macro shots focusing 100% on testing the product's features, material durability, texture, and immediate functional performance. Precise movements with sharp focus on immediate results.]\n\n",
    "Review tự nhiên": "[CONTENT FORMAT - NATURAL REVIEW: Presenter stands naturally holding the product, moves freely around the scene. Handheld camera with subtle natural shake, medium shot framing. Natural window or outdoor lighting, no studio setup. Casual, energetic, authentic style — like genuinely sharing with friends.]\n\n",
    "So Sánh/Đánh Giá": "[CONTENT FORMAT - COMPARISON REVIEW: Presenter holds product alongside reference items for size/quality comparison. Camera alternates between wide shots (both items visible) and close-ups (detail on each). Even, neutral lighting. Analytical, thoughtful expressions — satisfied nods or slight skeptical frowns when comparing.]\n\n",
}
_CONTENT_STYLE_ALIAS_EN = {
    "POV (Góc nhìn thứ nhất)": "POV",
    "UGC Authentic": "UGC",
    "Demo Công Dụng": "Demo công dụng",
    "Ngồi Review": "Review tự nhiên",
}
for _alias, _target in _CONTENT_STYLE_ALIAS_EN.items():
    CONTENT_MAP_EN[_alias] = CONTENT_MAP_EN[_target]


# ==================== CHỌN KHUNG CẢNH ====================

def pick_scene(user_choice, lang="en"):
    """Trả (scene_name, scene_desc) dựa trên lựa chọn user + ngôn ngữ.
    Nếu '🎲 Random' → random từ SCENES pool.
    Nếu user chọn preset cụ thể → dùng preset đó.
    lang='vi' → trả mô tả tiếng Việt, lang='en' → tiếng Anh.
    """
    smap = SCENE_MAP_VI if lang == "vi" else SCENE_MAP_EN
    default = "trong phòng quay đánh giá chuyên nghiệp" if lang == "vi" else "in a professional review studio"
    if user_choice == "🎲 Random":
        scene = random.choice(SCENES)
        idx = 2 if lang == "vi" else 1
        return scene[0], scene[idx]
    return user_choice, smap.get(user_choice, default)


# ==================== SEGMENT POOL — ENGLISH ====================
# Mỗi clip từ API Google Flow dài ~8 giây.
# → 16s = 2 clip × ~8s, 24s = 3 clip × ~8s
#
# CẤU TRÚC 16s (2 CLIP):
#   Clip 1 (0-8s):  HOOK + DEMO/PAIN — Thu hút + Trình diễn sản phẩm
#   Clip 2 (8-16s): BENEFIT/CLOSE + CTA — Lợi ích + Kêu gọi mua hàng
#
# CẤU TRÚC 24s (3 CLIP):
#   Clip 1 (0-8s):  REVIEW — Đánh giá tổng quan
#   Clip 2 (8-16s): ADVANTAGES — Ưu điểm nổi bật
#   Clip 3 (16-24s): TARGET AUDIENCE + CTA — Đối tượng + Kêu gọi hành động
#
# {lang_instruction} sẽ được thay bằng "The model speaks English" hoặc
# "Người mẫu nói tiếng Việt" tùy ngôn ngữ khi build prompt.

_CONT_EN = (
    "=== SECTION 1: GENERAL RULES & NEGATIVE CONSTRAINTS ===\n"
    "[DIRECTIVES & PROMPT LOCKS]\n"
    "- The video structure must strictly follow the Timeline Action descriptions with clean continuity.\n"
    "- Ensure perfect temporal consistency — the character's face, body, clothing, and the product must remain 100% identical and stable across all frames with no morphing, no identity drift, and no sudden changes.\n"
    "- The product is the primary focal point: It must remain clearly visible, properly framed, and in sharp focus throughout the entire video. Maintain its real-world proportions, colors, textures, and details.\n"
    "- FRAMING LOCK: Generate a full-frame vertical 9:16 portrait video. The reference image must fill the entire frame edge-to-edge with NO letterboxing, NO pillarboxing, NO black bars, NO white borders, NO frame-within-frame effect, and NO empty side margins.\n"
    "- PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Its color, shape, size, material texture, and all distinguishing features must NOT change, swap, or gradually transform at any point in the video — especially in the final 1-2 seconds.\n"
    "- The character naturally and fluidly interacts with the product as described in the Timeline Action. Movements must be smooth, realistic, and human — no robotic or unnatural motion, no slow-motion effects.\n"
    "- ITEM PERSISTENCE & HAND LOCK: Any object the character holds or wears at the start must remain naturally present throughout. The character has exactly TWO normal human hands with five fingers each. Do NOT generate extra hands, extra arms, extra fingers, or limb deformations.\n"
    "\n"
    "[NEGATIVE PROMPTS]\n"
    "- No chaotic or unintended rapid morphing. Any camera transitions must feel deliberate, clean, and highly professional.\n"
    "- ABSOLUTELY NO text, NO letters, NO numbers, NO subtitles, NO captions, NO titles, NO watermarks, NO logo overlays, NO HUD, NO UI graphics or artificial text overlays on screen.\n"
    "- ABSOLUTELY NO gibberish, floating symbols, distorted text fonts, alien characters, or random numbers anywhere in the video frame.\n"
    "- No letterbox, no pillarbox, no black bars, no white borders, no side margins, no divider lines, no collage layout, no storyboard layout, no comic-strip layout.\n"
    "- No cartoon, anime, illustration, sketch, storyboard art, hand-drawn look, vector graphics, or stylized CGI. The output must stay natural photorealistic live-action footage.\n"
    "- Color grading is strictly neutral and true-to-life, maintaining a clean white balance without unwanted color tints.\n"
    "- No anatomical anomalies, no extra limbs, no extra hands, no extra fingers, no weird hand deformations.\n"
    "- Do NOT remove, hide, or make any accessory disappear during the video.\n"
    "\n"
    "=== SECTION 2: PRODUCT TO ADVERTISE ===\n"
    "- Product: {name}\n"
    "- If the attached image includes multiple objects, select ONLY ONE (1) main product as the focal item and ignore all other items.\n"
    "\n"
    "=== SECTION 3: SUBJECT & CHARACTER CONSISTENCY ===\n"
    "- Character: A 22-year-old {country_en} woman with a bright, cheerful face and natural beauty.\n"
    "- Face & Features: Soft oval face shape, dark brown almond eyes, clear smooth skin, natural rosy blush.\n"
    "- CRITICAL IDENTITY & OUTFIT LOCK: The presenter MUST be the EXACT SAME person matching the attached reference image with the EXACT SAME face structure, hairstyle, and exact clothing outfit across ALL segments. DO NOT change her identity, hair style, or clothing between clips.\n"
    "- Voice & Tone: Standard {country_en} tone, lively, energetic, clear articulation, youthful.\n"
    "\n"
    "=== SECTION 4: SCENE & ACTION SEQUENCE ===\n"
    "- Environment: {scene}\n"
)

SEGMENT_POOL_EN = [
    # ──── 16s FORMAT: 2 CLIPS ────
    # 0: CLIP 1 — HOOK + DEMO/PAIN (0-8s)
    (
        _CONT_EN +
        "- Timeline Action for Segment 1 (0-8 seconds):\n"
        "  * The character is a professional product reviewer, speaking confidently and engagingly with a cheerful expression.\n"
        "  * Seconds 0-1 (ANCHOR FRAME): Start from the attached reference image as the anchor frame. Apply only a simple fade-in/brightness change. Preserve the reviewer identity, clothing, pose, hand placement, product, and background exactly; only minimal natural motion may begin (blink/breath).\n"
        "  * Seconds 1-3 (PRODUCT INTRO): Front-facing camera. The character holds or gently touches '{name}' and begins speaking naturally. Keep the product fully visible in the frame.\n"
        "  * Seconds 3-7 (FEATURE SHOWCASE): Still front-facing. The character highlights key details using subtle gestures: slight tilting/rotating of the product or a gentle pointing motion. Maintain stable framing.\n"
        "  * Seconds 7-8 (CRITICAL RETURN TO REFERENCE & FREEZE): Front-facing camera. Cease all motion; the character and product must hold a completely static pose with zero movement. Both the reviewer and the product must remain in sharp focus and clearly visible within the frame. No morphing, no drifting of details.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Style: Professional product-review video with smooth camera movement and realistic smartphone-style material reproduction.\n"
        "- Camera: Shot on a professional cinema/mirrorless camera, 4K UHD, 30fps, high dynamic range, tripod-stable with subtle gimbal stabilization.\n"
        "- Color & Grading: Neutral color calibration, natural skin tones, crisp details, clean white balance, realistic optical depth of field.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} throughout the video. The model must speak this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # 1: CLIP 2 — BENEFIT/CLOSE-UP + CTA (8-16s)
    (
        _CONT_EN +
        "- Timeline Action for Segment 2 (8-16 seconds):\n"
        "  * This is a flawless, seamless continuation of the previous video. Start exactly from the static pose of the reference image.\n"
        "  * The character remains generally in place, performing subtle, natural movements. Maintain character and setting consistency.\n"
        "  * Seconds 8-10 (SEAMLESS RESUME): Maintain the camera angle from the attached image. Front view, focusing tightly on the character and the product '{name}'. The character speaks naturally.\n"
        "  * Seconds 10-14 (CLOSE-UP DETAILS): Professional close-up shots of '{name}': texture, materials, buttons, detailed components.\n"
        "  * Seconds 14-16 (CLOSING RECOMMENDATION): Return to the final front-facing shot with high clarity, where the product '{name}' and the reviewer appear sharp, clean, and well-lit. End with a confident, persuasive smile and recommendation.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Style: Professional product-review video with smooth camera movement and realistic smartphone-style material reproduction.\n"
        "- Camera: Shot on a professional cinema/mirrorless camera, 4K UHD, 30fps, high dynamic range, tripod-stable with subtle gimbal stabilization.\n"
        "- Color & Grading: Neutral color calibration, natural skin tones, crisp details, clean white balance, realistic optical depth of field.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} throughout the video. The model must speak this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # ──── 24s FORMAT: 3 CLIPS (SEAMLESS HANDOFF) ────
    # 2: CLIP 1 — REVIEW (0-8s)
    (
        _CONT_EN +
        "- Timeline Action for Segment 1 of 3 (0-8 seconds):\n"
        "  * Product review opening. CRITICAL: DO NOT start with greeting, waving, welcoming, or introduction gesture.\n"
        "  * The person from the reference image is ALREADY holding '{name}' with both hands at chest level and carefully examining it from multiple angles — turning it over, inspecting the build quality, running fingers along the surface with a thoughtful, analytical expression.\n"
        "  * They look at the camera and begin sharing honest first impressions with natural speaking gestures.\n"
        "  * ENDING POSE (CRITICAL HANDOFF): The clip MUST END with the person holding '{name}' with BOTH HANDS at CHEST LEVEL, facing the camera, mouth slightly open as if mid-sentence — this exact pose will be the starting point of the next segment.\n"
        "  * Seconds 7-8: Freeze into static handoff pose with zero motion drift.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Steady medium shot (waist-up framing), gentle subtle orbit, 35mm lens feel, natural soft lighting.\n"
        "- Color & Grading: Neutral calibration, natural skin tones, sharp focus on product, clean background bokeh.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The model speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # 3: CLIP 2 — DEMO/TEST HANDS-ON (8-16s)
    (
        _CONT_EN +
        "- Timeline Action for Segment 2 of 3 (8-16 seconds):\n"
        "  * Hands-on product demo — seamless continuation. CRITICAL: NO 'hello', NO waving, NO welcome pose.\n"
        "  * STARTING POSE (MUST MATCH): The person is ALREADY holding '{name}' with BOTH HANDS at CHEST LEVEL, facing camera, mid-sentence — continuing directly from where they left off.\n"
        "  * From this pose, the person actively DEMONSTRATES '{name}' in action — flipping it around, pressing buttons or opening compartments, running fingers along the surface to show texture and craftsmanship, bringing it close to camera for a detailed view.\n"
        "  * Their expression shows genuine satisfaction and pleasant surprise at the quality.\n"
        "  * ENDING POSE (CRITICAL HANDOFF): The clip MUST END with the person holding '{name}' UP with ONE HAND near FACE level, the other hand pointing at the product — this exact pose will be the starting point of segment 3.\n"
        "  * Seconds 15-16: Freeze into static handoff pose with zero motion drift.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Smooth push-in for tight close-ups of product details and texture, then medium shot, 50mm lens feel.\n"
        "- Color & Grading: Consistent warm cinematic daylight matching segment 1 perfectly.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The model speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # 4: CLIP 3 — TARGET AUDIENCE + CTA (16-24s)
    (
        _CONT_EN +
        "- Timeline Action for Segment 3 of 3 (16-24 seconds):\n"
        "  * Final call to action — seamless continuation to the end. CRITICAL: NO 'hello', NO waving, NO welcome pose.\n"
        "  * STARTING POSE (MUST MATCH): The person is ALREADY holding '{name}' UP with ONE HAND near FACE level — continuing directly from where they left off.\n"
        "  * From this pose, the person smoothly transitions to speaking directly to camera with a warm, relatable tone, using inclusive hand gestures — open palm gestures, pointing toward viewer, personally recommending the product.\n"
        "  * Then they hold '{name}' up prominently with both hands, looking directly into camera with a confident, persuasive smile and double thumbs-up.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Medium shot with gentle push-in, then slow cinematic zoom out to wide shot, warm trustworthy lighting.\n"
        "- Color & Grading: Clean white balance, sharp subject separation, professional commercial finish.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The model speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
]



TTS_MIDDLES_VI = [
    "Nhìn thiết kế quá mượt mà, đường nét vô cùng tinh xảo, cầm rất chắc tay.",
    "Chất liệu của nó xịn xò lắm, sờ vào cảm giác cao cấp khác bọt hẳn.",
    "Khi dùng thử tôi mới thấy nó đa năng và vi diệu hơn quảng cáo rất nhiều.",
    "Hàng chuẩn từng centimet, màu sắc thì đẹp y hệt hình mẫu, quá mãn nhãn.",
    "Càng nhìn kỹ càng thấy độ tinh tế, nhà sản xuất chăm chút từng tiểu tiết.",
    "Không chỉ đẹp mã, mà công dụng của nó thực sự giải quyết bao rắc rối cho tôi.",
    "Nó hoạt động cực êm ái, nhẹ nhàng mà lại rất chắc chắn và an toàn nha.",
    "Tôi test đủ kiểu rồi, xài vẫn siêu bền, xứng đáng từng đồng mình bỏ ra.",
    "Form dáng hoàn hảo, màu sắc bắt mắt, nói chung không có điểm nào để chê.",
    "Phải công nhận là từ khi xài nó, tôi thấy tiện lợi và tiết kiệm bao thời gian.",
    "Để gần soi kỹ thì chẳng thấy lỗi nhỏ nào, độ hoàn thiện xứng đáng 10 điểm.",
    "Trải nghiệm thực tế mới hiểu tại sao ai cũng săn lùng cái này nhiệt tình vậy.",
    "Công năng thì tuyệt hảo, kích thước lại nhỏ gọn không chiếm nhiều diện tích.",
    "Điều tôi ưng nhất là độ nhẹ nhàng êm ái khi tương tác, rất thư giãn.",
    "Từ độ bền đến thẩm mỹ đều làm tôi phải trầm trồ ngạc nhiên luôn đấy."
]

TTS_ENDINGS_VI = [
    "Chốt lại là quá hời! Các bà nhấp ngay vào giỏ hàng dốt đơn nhé.",
    "Không mua sớm là tiếc hùi hụi đó, link gốc tôi để ở góc trái màn hình nha.",
    "Shop đang có flash sale cực hời, tranh thủ chốt đơn kẻo hết nha mọi người.",
    "Túm lại là nên mua! Xứng đáng 100 điểm, ấn ngay biểu tượng giỏ hàng nhé.",
    "Cầm trên tay là ưng ngay, các tình yêu ấn ngay vào giỏ vàng nha.",
    "Ai cũng cần một em như này, tôi gắn link giỏ hàng bên dưới góc trái rồi đó.",
    "Nghe mị đi, bấm mua liền đi, chắc chắn sẽ không làm bạn thất vọng đâu.",
    "Shop đang hỗ trợ freeship nữa, ngại gì không nhấp vào giỏ hàng chốt đơn.",
    "Quá ngon bổ rẻ, hàng hiếm đó! Múc lẹ múc lẹ kẻo cháy hàng mấy bà ơi.",
    "Đừng lăn tăn nữa, ấn ngay giỏ hàng xách liền môt em về dùng thử xem.",
    "Khách quen nhà tôi đều khen nức nở, link uy tín nằm dưới góc trái màn hình nha.",
    "Tiền nào của nấy mà em này lại quá rẻ so với chất lượng, quất ngay đi!",
    "Bảo bối thần thánh nằm trong giỏ hàng góc trái, nhanh tay kẻo muộn nha mấy bồ.",
    "Nhanh tay thì còn, chậm tay thì hết. Tôi mua rồi còn các bà thì sao?",
    "Mọi người ấn ngay nút mua góc dưới nhé, hàng chuẩn Auth không lo gì luôn!"
]

TTS_MIDDLES_ID = [
    "Desainnya sangat mulus, detailnya rapi, dan nyaman digenggam.",
    "Bahannya sangat berkualitas, terasa premium saat disentuh.",
    "Setelah mencoba, ternyata fiturnya jauh lebih canggih daripada iklannya.",
    "Sangat presisi, warnanya persis seperti di foto, sangat memuaskan.",
    "Melihat lebih dekat, detailnya sangat diperhatikan oleh produsen.",
    "Tidak hanya bagus penampilannya, tapi sangat membantu menyelesaikan masalah saya.",
    "Kerjanya sangat halus, ringan tapi tetap kokoh dan aman.",
    "Saya sudah tes berkali-kali, terbukti awet dan sangat bernilai.",
    "Bentuknya sempurna, warnanya menarik, tidak ada kekurangan.",
    "Sangat praktis dan menghemat banyak waktu saya sejak menggunakannya.",
    "Dilihat dari dekat pun tidak ada cacat, kualitasnya bintang sepuluh.",
    "Sekarang saya paham kenapa produk ini sangat viral dan banyak dicari.",
    "Fungsinya luar biasa, ukurannya ringkas tidak memakan tempat.",
    "Yang paling saya suka adalah sensasi nyaman saat menggunakannya.",
    "Daya tahan dan estetikanya benar-benar membuat saya kagum."
]

TTS_ENDINGS_ID = [
    "Kesimpulannya ini sangat menguntungkan! Buruan klik keranjang kuning ya.",
    "Jangan sampai menyesal, link pembelian ada di sudut kiri bawah layar.",
    "Toko lagi ada flash sale besar, langsung checkout sebelum kehabisan.",
    "Sangat direkomendasikan! Nilai 100, klik ikon keranjang sekarang.",
    "Begitu dipegang langsung suka, yuk klik keranjang kuning.",
    "Semua orang butuh ini, link toko ada di bawah kiri.",
    "Percayalah, langsung beli sekarang, dijamin tidak menyesal.",
    "Ada promo gratis ongkir juga, tunggu apa lagi, langsung checkout.",
    "Murah tapi berkualitas, stok terbatas, langsung beli sekarang.",
    "Jangan ragu lagi, klik keranjang sekarang dan cobain sendiri."
]

TTS_MIDDLES_MY = [
    "Reka bentuknya sangat kemas, perinciannya halus dan selesa dipegang.",
    "Kualiti bahannya memang terbaik, rasa sangat premium bila disentuh.",
    "Bila cuba sendiri, baru tahu fungsinya jauh lebih hebat daripada iklan.",
    "Saiznya sangat tepat, warna sebiji macam dalam gambar, memang puas hati.",
    "Tengok dari dekat nampak kualiti buatannya sangat teliti dan kukuh.",
    "Bukan sahaja cantik dipandang, tapi betul-betul memudahkan kerja harian saya.",
    "Ia berfungsi dengan sangat lancar, ringan tapi tahan lasak dan selamat.",
    "Saya dah uji banyak kali, memang tahan lama dan sangat berbaloi.",
    "Bentuknya sempurna, warna menarik, memang tiada cacat cela.",
    "Sangat praktikal dan menjimatkan banyak masa sejak saya menggunakannya.",
    "Tengok dari dekat pun tiada kecacatan, kemasan dia bagi 10 per 10.",
    "Sekarang baru faham kenapa produk ini viral dan ramai orang cari.",
    "Fungsi dia sangat mantap, saiz padat tak makan ruang langsung.",
    "Paling saya suka rasa selesa dan mudah bila digunakan.",
    "Ketahanan dan estetik dia memang buat saya kagum sangat."
]

TTS_ENDINGS_MY = [
    "Pendek kata memang berbaloi! Cepat tekan beg kuning sekarang ya.",
    "Jangan sampai terlepas, pautan ada di sudut bawah kiri skrin.",
    "Kedai tengah ada jualan kilat hebat, cepat checkout sebelum habis.",
    "Sangat disyorkan! Memang 100 markah, klik ikon beg sekarang.",
    "Pegang je terus jatuh hati, jom tekan beg kuning sekarang.",
    "Semua orang patut ada satu, pautan kedai ada kat bawah kiri.",
    "Percayalah, beli sekarang dan pasti anda takkan menyesal.",
    "Ada baucar penghantaran percuma juga, tunggu apa lagi, jom checkout.",
    "Murah tapi kualiti padu, stok terhad, dapatkan sekarang juga.",
    "Jangan fikir panjang lagi, klik beg kuning dan cuba sendiri."
]

TTS_MIDDLES_PH = [
    "Napakaganda ng disenyo, napakapino ng mga detalye, at napakasarap hawakan.",
    "Napakaganda ng kalidad ng materyal, premium ang pakiramdam kapag hinawakan.",
    "Nang subukan ko, mas maganda at advanced ang mga feature kaysa sa nakikita sa ad.",
    "Eksakto ang sukat, parehong-pareho ang kulay sa larawan, napakasiya ko.",
    "Kapag tiningnan nang malapitan, makikitang pulido ang pagkakagawa sa bawat detalye."
]

TTS_MIDDLES_EN = [
    "It is incredibly designed with premium materials, making it feel very high-quality.",
    "The overall build is sturdy and highly functional, perfect for daily usage.",
    "It exceeded all my expectations with its outstanding design and usability.",
    "This product is a game-changer for me and has solved so many of my problems.",
    "The shape is elegant and the color is gorgeous, absolutely no flaws to complain about.",
    "Even when inspected closely, there are no defects whatsoever, 10 out of 10.",
    "It is lightweight yet very durable, making it highly portable and convenient.",
    "I highly recommend this to everyone looking for a reliable and stylish solution."
]

TTS_ENDINGS_EN = [
    "You definitely need this, I put the purchase link in the bottom left corner.",
    "Don't miss this opportunity, grab yours now before the sale ends.",
    "Click the yellow cart below to checkout right now, you won't regret it.",
    "It is very affordable yet high quality, limited stock, so buy it now.",
    "There is also free shipping available, checkout immediately to save big."
]

TTS_ENDINGS_PH = [
    "Sa pangkalahatan, sulit na sulit! I-click na ang dilaw na cart ngayon.",
    "Huwag nang mag-atubili, ang link ng produkto ay nasa ibabang kaliwang bahagi.",
    "May malaking flash sale ngayon, mag-checkout na bago maubusan.",
    "Dapat itong bilhin! 100 points, i-click ang icon ng cart.",
    "Magugustuhan mo kapag hinawakan mo, i-click ang dilaw na cart.",
    "Kailangan ito ng lahat, inilagay ko ang link sa ibabang kaliwa.",
    "Maniwala ka sa index, bilhin mo na ngayon, hindi ka magsisi.",
    "May libreng shipping din ang shop, i-checkout na ang order mo.",
    "Mura at magandang kalidad, limited stock lang, bili na ngayon.",
    "Huwag nang magdalawang-isip, i-click ang cart ngayon at subukan."
]

def generate_tts_script(product_name, segment_index, total_segments, lang="vi"):
    import random
    seed_val = sum(ord(c) for c in product_name)
    rng = random.Random(seed_val)
    
    if lang == "vi":
        middles_pool = TTS_MIDDLES_VI
        endings_pool = TTS_ENDINGS_VI
        prefix_format = "Đối với {name}, "
        prefix_format_24s = "Về {name}, "
    elif lang == "id":
        middles_pool = TTS_MIDDLES_ID
        endings_pool = TTS_ENDINGS_ID
        prefix_format = "Untuk {name}, "
        prefix_format_24s = "Mengenai {name}, "
    elif lang in ("my", "ms"):
        middles_pool = TTS_MIDDLES_MY
        endings_pool = TTS_ENDINGS_MY
        prefix_format = "Untuk {name}, "
        prefix_format_24s = "Mengenai {name}, "
    elif lang == "ph":  # Tagalog (Philippines)
        middles_pool = TTS_MIDDLES_PH
        endings_pool = TTS_ENDINGS_PH
        prefix_format = "Para sa {name}, "
        prefix_format_24s = "Tungkol sa {name}, "
    else:  # en (English default)
        middles_pool = TTS_MIDDLES_EN
        endings_pool = TTS_ENDINGS_EN
        prefix_format = "For {name}, "
        prefix_format_24s = "About {name}, "
        
    middles = rng.sample(middles_pool, 2)
    ending = rng.choice(endings_pool)
    
    if total_segments == 2:
        if segment_index == 0:
            feat1 = middles[0]
            prefix = prefix_format.format(name=product_name)
            return prefix + feat1[0].lower() + feat1[1:]
        else:
            feat2 = middles[1]
            return feat2 + " " + ending
    else:
        if segment_index == 0:
            feat1 = middles[0]
            prefix = prefix_format_24s.format(name=product_name)
            return prefix + feat1[0].lower() + feat1[1:]
        elif segment_index == 1:
            return middles[1]
        else:
            return ending

def generate_audio_file(text, output_path, voice="vi-VN-HoaiMyNeural"):
    """Sử dụng subprocess để gọi edge-tts (chặn cmd window) nhằm tạo file .wav miễn phí"""
    import subprocess, os
    cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", output_path]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        if res.returncode == 0 and os.path.exists(output_path):
            return True
        return False
    except Exception as e:
        print(f"generate_audio_file exception: {e}")
        return False

def generate_gemini_audio_file(text, output_path, voice="Achernar", keys=None):
    """Sử dụng Google Gemini API để tạo audio TTS (cần cài google-genai)"""
    import os, time, wave
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Lỗi: Cần cài đặt thư viện google-genai (pip install google-genai) để dùng Gemini TTS.")
        return False
    
    if not keys: return False
    
    import random
    for k in keys:
        try:
            client = genai.Client(api_key=k)
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        )
                    )
                )
            )
            data = response.candidates[0].content.parts[0].inline_data.data
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(data)
            return True
        except Exception as e:
            print(f"Lỗi Gemini TTS với key {k[:6]}... : {e}")
            time.sleep(2)
            continue
    return False

# ==================== SEGMENT POOL — TIẾNG VIỆT ====================

_CONT_VI = (
    "=== SECTION 1: GENERAL RULES & NEGATIVE CONSTRAINTS ===\n"
    "[CHỈ THỊ CỐT LÕI & CÁC KHÓA BẢO VỆ]\n"
    "- Cấu trúc video phải tuân thủ nghiêm ngặt mô tả Timeline Action với sự tiếp nối liền mạch.\n"
    "- ĐỒNG BỘ THỜI GIAN TUYỆT ĐỐI: Khuôn mặt, vóc dáng, trang phục của nhân vật và sản phẩm phải giữ nguyên vẹn 100% qua mọi khung hình, không bị trôi danh tính hay biến dạng.\n"
    "- SẢN PHẨM LÀ TRỌNG TÂM: Sản phẩm phải luôn hiển thị rõ ràng, lấy nét sắc nét và giữ đúng tỷ lệ, màu sắc, chi tiết thực tế.\n"
    "- KHÓA KHUNG HÌNH (FRAMING LOCK): Tạo video định dạng dọc full-frame 9:16 tràn viền (edge-to-edge). Hình ảnh lấp đầy toàn bộ khung hình, TUYỆT ĐỐI KHÔNG viền đen (letterbox), KHÔNG viền trắng (pillarbox), KHÔNG lề phụ, KHÔNG chia ô collage/storyboard/comic-strip.\n"
    "- KHÓA TOÀN VẸN SẢN PHẨM (PRODUCT CONSISTENCY LOCK): Sản phẩm xuất hiện ở khung hình đầu tiên phải CHÍNH XÁC LÀ CÙNG MỘT SẢN PHẨM trong mọi khung hình tiếp theo. Màu sắc, hình dáng, kích thước, logo, nhãn mác, chất liệu KHÔNG được thay đổi, tráo đổi hay biến dạng ở bất kỳ thời điểm nào — đặc biệt là trong 1-2 giây cuối cùng.\n"
    "- Nhân vật tương tác tự nhiên, mượt mà và linh hoạt với sản phẩm theo Timeline Action. Chuyển động người thật tự nhiên, không giật cục, không slow-motion.\n"
    "- KHÓA GIẢI PHẪU & BÀN TAY (HAND & ANATOMY LOCK): Nhân vật có đúng HAI bàn tay người bình thường với 5 ngón mỗi bàn tay. TUYỆT ĐỐI KHÔNG sinh thêm tay, không thừa ngón tay, không biến dạng chi, không có bàn tay ma. Đồ vật đang cầm/mặc không được tự ý biến mất.\n"
    "\n"
    "[NEGATIVE PROMPTS / RÀNG BUỘC PHỦ ĐỊNH]\n"
    "- Không chuyển đổi hình khối hỗn loạn. Mọi chuyển cảnh phải tự nhiên, mượt mà và chuyên nghiệp.\n"
    "- Tuyệt đối KHÔNG chèn văn bản (text), chữ, số, phụ đề, tiêu đề, logo, watermark hay các phần tử đồ họa UI lên màn hình.\n"
    "- KHÔNG có viền đen, viền trắng, đường phân cách, bố cục truyện tranh hay khung tranh bên trong video.\n"
    "- KHÔNG phong cách hoạt hình, anime, tranh vẽ minh họa, sketch hay CGI cách điệu. Video phải là cảnh quay người thật sống động chuẩn photorealistic.\n"
    "- Cân bằng trắng trung tính, màu da người thật chuẩn xác, độ sâu trường ảnh quang học tự nhiên.\n"
    "- TUYỆT ĐỐI KHÔNG sinh thêm tay, KHÔNG sinh thêm chi, KHÔNG thừa ngón tay, KHÔNG biến dạng bàn tay.\n"
    "- KHÔNG tráo đổi sản phẩm sang biến thể khác.\n"
    "\n"
    "=== SECTION 2: PRODUCT TO ADVERTISE ===\n"
    "- Tên sản phẩm: {name}\n"
    "- Nếu khung hình có nhiều đồ vật, CHỈ TẬP TRUNG vào một sản phẩm chính duy nhất.\n"
    "\n"
    "=== SECTION 3: SUBJECT & CHARACTER CONSISTENCY ===\n"
    "- Character: Một người phụ nữ trẻ {country_vi} 22 tuổi, khuôn mặt rạng rỡ tươi tắn, vẻ đẹp tự nhiên.\n"
    "- Face & Features: Mặt trái xoan mềm mại, mắt hạnh nhân nâu đen, da sáng khỏe, má hồng ửng nhẹ tự nhiên.\n"
    "- KHÓA DANH TÍNH (CRITICAL IDENTITY LOCK): Khuôn mặt và trang phục người review phải khớp CHÍNH XÁC 100% với ảnh tham chiếu. KHÔNG tự ý đổi lớp trang điểm, độ tuổi, kiểu tóc hay thêm phụ kiện giữa các clip.\n"
    "- Voice & Tone: Giọng nói rõ ràng chuẩn {country_vi}, tự nhiên, trẻ trung, tự tin.\n"
    "\n"
    "=== SECTION 4: SCENE & ACTION SEQUENCE ===\n"
    "- Bối cảnh: {scene}\n"
)

SEGMENT_POOL_VI = [
    # ──── 16s FORMAT: 2 CLIPS ────
    # 0: CLIP 1 — HOOK + DEMO/PAIN (0-8s)
    (
        _CONT_VI +
        "- Timeline Action cho Đoạn 1 (0-8 giây):\n"
        "  * Nhân vật là một reviewer chuyên nghiệp, nói chuyện tự tin, cuốn hút với nét mặt rạng rỡ.\n"
        "  * Giây 0-1 (KHUNG NEO GIỮ): Bắt đầu từ ảnh tham chiếu làm khung neo giữ. Chỉ áp dụng hiệu ứng mờ dần sáng lên. Giữ nguyên 100% người review, trang phục, dáng tay, sản phẩm và cảnh nền; chỉ có chuyển động chớp mắt/thở tự nhiên.\n"
        "  * Giây 1-3 (GIỚI THIỆU SẢN PHẨM): Góc máy trực diện. Nhân vật cầm hoặc chạm nhẹ vào '{name}' và bắt đầu nói chuyện tự nhiên. Giữ sản phẩm luôn rõ ràng trong khung hình.\n"
        "  * Giây 3-7 (TRÌNH DIỄN TÍNH NĂNG): Góc máy giữ nguyên trực diện. Nhân vật nhấn mạnh các chi tiết nổi bật bằng thao tác tay nhẹ nhàng: hơi nghiêng/xoay sản phẩm hoặc chỉ ngón tay tinh tế.\n"
        "  * Giây 7-8 (QUAN TRỌNG: TRỞ LẠI NEO GIỮ & FREEZE): Góc trực diện. BẮT BUỘC DỪNG MỌI CHUYỂN ĐỘNG; nhân vật và sản phẩm chốt thẳng ở một tư thế tĩnh hoàn toàn (Zero movement). Không bị biến dạng vật thể hay dịch chuyển.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Phong cách: Video review sản phẩm chuyên nghiệp với chuyển động mượt mà và vật liệu chân thực kiểu smartphone.\n"
        "- Camera: Quay bằng dòng cinema/mirrorless cao cấp, 4K UHD, 30fps, góc máy ngang tầm mắt, chống rung tripod/gimbal tinh tế.\n"
        "- Màu sắc: Cân bằng màu trung tính, màu da người thật, chi tiết sắc nét, ánh sáng tự nhiên mềm mại.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} trong suốt video. Người mẫu phải nói chính xác đoạn thoại sau: \"{dialogue}\"]\n\n"
    ),
    # 1: CLIP 2 — BENEFIT/CLOSE-UP + CTA (8-16s)
    (
        _CONT_VI +
        "- Timeline Action cho Đoạn 2 (8-16 giây):\n"
        "  * Đây là sự tiếp nối hoàn hảo và liền mạch từ video trước. Bắt đầu CHÍNH XÁC từ tư thế đứng tĩnh của ảnh tham chiếu.\n"
        "  * Nhân vật tiếp tục đứng ở vị trí cũ, thực hiện chuyển động nhẹ nhàng tự nhiên. Duy trì tính đồng nhất nhân vật và bối cảnh.\n"
        "  * Giây 8-10 (TIẾP NỐI LIỀN MẠCH): Giữ nguyên góc máy như ảnh tham chiếu. Ở góc trực diện, tập trung chặt vào nhân vật và sản phẩm '{name}'. Nhân vật đang nói chuyện.\n"
        "  * Giây 10-14 (CẬN CẢNH CHI TIẾT): CAMERA CẬN CẢNH sản phẩm: lướt qua kết cấu vật liệu, nút bấm, chất liệu bên ngoài cực sắc nét.\n"
        "  * Giây 14-16 (KẾT THÚC THUYẾT PHỤC): Camera quay trở lại khuôn mặt trực diện. Sản phẩm '{name}' và người mẫu đều rõ nét, sạch sẽ và bắt sáng hoàn hảo. Kết thúc bằng nụ cười chốt sale tự tin.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Phong cách: Video review sản phẩm chuyên nghiệp với chuyển động mượt mà và vật liệu chân thực kiểu smartphone.\n"
        "- Camera: Quay bằng dòng cinema/mirrorless cao cấp, 4K UHD, 30fps, góc máy ngang tầm mắt, chống rung tripod/gimbal tinh tế.\n"
        "- Màu sắc: Cân bằng màu trung tính, màu da người thật, chi tiết sắc nét, ánh sáng tự nhiên mềm mại.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} trong suốt video. Người mẫu phải nói chính xác đoạn thoại sau: \"{dialogue}\"]\n\n"
    ),
    # ──── 24s FORMAT: 3 CLIPS (LIỀN MẠCH HANDOFF) ────
    # 2: CLIP 1 — ĐÁNH GIÁ (0-8s)
    (
        _CONT_VI +
        "- Timeline Action cho Đoạn 1 trên 3 (0-8 giây):\n"
        "  * Mở đầu đánh giá sản phẩm. QUAN TRỌNG: KHÔNG được bắt đầu bằng lời chào, vẫy tay, chào mừng, hay giới thiệu. Bắt đầu TRỰC TIẾP với hành động sản phẩm.\n"
        "  * Người trong ảnh tham chiếu ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC và quan sát kỹ lưỡng từ nhiều góc — xoay qua xoay lại, kiểm tra chất lượng gia công, lướt ngón tay trên bề mặt với biểu cảm phân tích.\n"
        "  * Nhìn vào camera và bắt đầu chia sẻ cảm nhận ban đầu với cử chỉ nói chuyện tự nhiên.\n"
        "  * TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với người cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC, mặt hướng camera, miệng hơi mở như đang nói dở — tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo.\n"
        "  * Giây 7-8: Chốt lại tư thế tĩnh hoàn toàn, không trôi dạt chuyển động.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Medium shot ổn định (ngang hông trở lên), xoay nhẹ tinh tế, 35mm lens, ánh sáng tự nhiên ấm áp.\n"
        "- Màu sắc: Chuẩn trung tính, màu da tự nhiên, sản phẩm sắc nét nổi bật.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
    # 3: CLIP 2 — DEMO/TEST THỰC TẾ (8-16s)
    (
        _CONT_VI +
        "- Timeline Action cho Đoạn 2 trên 3 (8-16 giây):\n"
        "  * Trình diễn sản phẩm thực tế — tiếp nối liền mạch. QUAN TRỌNG: KHÔNG vẫy tay, KHÔNG chào đón. Đây là ĐOẠN TIẾP NỐI LIỀN MẠCH.\n"
        "  * TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): Người ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC, mặt hướng camera, đang nói dở — tiếp tục trực tiếp từ chỗ dừng.\n"
        "  * Từ tư thế này, người chủ động TRÌNH DIỄN '{name}' thực tế — lật qua lật lại, nhấn nút hoặc mở ngăn, lướt ngón tay cảm nhận chất liệu, đưa sản phẩm gần camera để xem chi tiết.\n"
        "  * Biểu cảm thể hiện sự hài lòng chân thực và ngạc nhiên thú vị về chất lượng.\n"
        "  * TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với người giơ '{name}' LÊN CAO bằng MỘT TAY gần tầm MẶT, tay kia đang chỉ vào sản phẩm — tư thế này sẽ là điểm bắt đầu của đoạn 3.\n"
        "  * Giây 15-16: Chốt lại tư thế tĩnh hoàn toàn, không trôi dạt chuyển động.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Push-in mượt mà cho cận cảnh chi tiết bề mặt, sau đó trở lại medium shot, 50mm lens.\n"
        "- Màu sắc: Đồng bộ tuyệt đối với đoạn trước, ánh sáng ấm áp tự nhiên.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
    # 4: CLIP 3 — ĐỐI TƯỢNG + CTA (16-24s)
    (
        _CONT_VI +
        "- Timeline Action cho Đoạn 3 trên 3 (16-24 giây):\n"
        "  * Kêu gọi hành động cuối cùng — tiếp nối liền mạch đến kết thúc. QUAN TRỌNG: KHÔNG vẫy tay, KHÔNG chào đón.\n"
        "  * TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): Người ĐANG giơ '{name}' LÊN CAO bằng MỘT TAY gần tầm MẶT — tiếp tục trực tiếp từ chỗ dừng.\n"
        "  * Từ tư thế này, người chuyển sang nói trực tiếp vào camera với giọng ấm áp, dùng cử chỉ tay bao quát — chỉ về phía người xem, mở rộng lòng bàn tay giới thiệu.\n"
        "  * Sau đó giơ '{name}' lên nổi bật bằng cả hai tay, nhìn thẳng camera với nụ cười tự tin và giơ hai ngón cái lên nhiệt tình.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Medium shot với push-in nhẹ, sau đó zoom ra điện ảnh chậm sang cảnh rộng, ánh sáng đáng tin cậy.\n"
        "- Màu sắc: Sạch sẽ, tương phản nhẹ nhàng, kết thúc thương mại chuyên nghiệp.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
]

# 8s: index 0 (1 clip), 16s: indices 0-1 (2 clip × ~8s), 24s: indices 2-4 (3 clip × ~8s)
DURATION_MAP = {
    8: [0],         # 8s = 1 clip × ~8s (Hook + Product Action)
    16: [0, 1],     # 16s = 2 clip × ~8s
    24: [2, 3, 4],  # 24s = 3 clip × ~8s
}

LANG_OPTIONS = ["Tiếng Việt", "Tiếng Philippines", "Tiếng Indonesia", "Tiếng Malaysia", "Tiếng Anh"]

_LANG_MAP = {
    "ph": {
        "instruction": "The model speaks Filipino",
        "country_en": "Filipino",
        "country_vi": "Philippines"
    },
    "vi": {
        "instruction": "Người mẫu nói tiếng Việt",
        "country_en": "Vietnamese",
        "country_vi": "Việt Nam"
    },
    "id": {
        "instruction": "The model speaks Indonesian",
        "country_en": "Indonesian",
        "country_vi": "Indonesia"
    },
    "my": {
        "instruction": "The model speaks Malay",
        "country_en": "Malaysian",
        "country_vi": "Malaysia"
    },
    "en": {
        "instruction": "The model speaks English",
        "country_en": "American",
        "country_vi": "Mỹ"
    }
}


# ==================== PROMPT BUILDERS ====================

def _apply_pov_or_unbox_transform(prompt, review_style, lang="en"):
    """Nếu review_style là POV hoặc Unboxing, loại bỏ hoàn toàn mô tả người mẫu nữ / khuôn mặt,
    thay bằng chỉ thị POV chỉ quay bàn tay và sản phẩm trên mặt bàn."""
    style_str = str(review_style or "").lower()
    if not any(k in style_str for k in ("pov", "unbox", "đập hộp", "góc nhìn thứ nhất")):
        return prompt

    import re as _re

    # 1. Thay thế hoàn toàn SECTION 3 (Xóa bỏ khuôn mặt / người mẫu nữ)
    if lang == "vi":
        pov_sec3 = (
            "=== SECTION 3: ĐẶC TẢ GÓC NHÌN POV & BÀN TAY (TUYỆT ĐỐI KHÔNG LỘ MẶT) ===\n"
            "- TUYỆT ĐỐI KHÔNG quay khuôn mặt, KHÔNG đầu người, KHÔNG thân người mẫu trong bất kỳ khung hình nào.\n"
            "- GÓC NHÌN: Góc nhìn thứ nhất POV hoặc góc máy từ trên cao nhìn xuống bàn (top-down desk view).\n"
            "- CHỈ CÓ BÀN TAY: Đúng hai bàn tay người bình thường với 5 ngón mỗi bàn tay, thao tác nhẹ nhàng trên mặt bàn.\n"
            "- SẢN PHẨM LÀ TRỌNG TÂM: Sản phẩm là tâm điểm duy nhất trên mặt bàn sạch sẽ.\n"
            "- Giọng đọc thuyết minh ngoài màn hình (voiceover) trong khi đôi bàn tay thao tác trên sản phẩm.\n"
            "\n"
        )
    else:
        pov_sec3 = (
            "=== SECTION 3: SUBJECT & HANDS CONSISTENCY (POV / UNBOXING - NO FACE) ===\n"
            "- ABSOLUTELY NO human face, NO head, NO body, NO presenter shown in any frame.\n"
            "- SUBJECT: First-person POV (Point of View) or top-down desk perspective looking directly at the workspace.\n"
            "- HANDS ONLY: Exactly two natural human hands with five normal fingers each, holding, operating, or unboxing the product on the desk.\n"
            "- PRODUCT FOCAL POINT: The product is the central hero item on the table surface.\n"
            "- Audio Narration / Voiceover speaks off-camera while hands demonstrate the product.\n"
            "\n"
        )

    prompt = _re.sub(r'=== SECTION 3:.*?=== SECTION 4:', pov_sec3 + '=== SECTION 4:', prompt, count=1, flags=_re.DOTALL)

    # 2. Thay thế các cụm từ mâu thuẫn trong Timeline Action & Camera
    if lang == "vi":
        replacements = [
            ("Góc máy trực diện", "Góc quay POV từ trên nhìn xuống bàn"),
            ("Góc trực diện", "Góc nhìn POV trên bàn"),
            ("Góc máy giữ nguyên trực diện", "Góc máy POV giữ nguyên vị trí trên bàn"),
            ("Nhân vật là một reviewer chuyên nghiệp, nói chuyện tự tin, cuốn hút với nét mặt rạng rỡ", "Đôi bàn tay khéo léo cầm, kiểm tra và giới thiệu sản phẩm trên bàn theo góc nhìn POV"),
            ("Người review", "Đôi bàn tay"),
            ("người review", "đôi bàn tay"),
            ("nhân vật và sản phẩm", "đôi bàn tay và sản phẩm"),
            ("Nhân vật cầm hoặc chạm", "Đôi bàn tay cầm hoặc chạm"),
            ("ngang tầm ngực, đối diện camera", "ngay trên mặt bàn"),
            ("ngang tầm ngực", "trên mặt bàn"),
            ("ngang tầm mặt", "ngay trên mặt bàn"),
            ("nhìn thẳng vào camera với nụ cười tự tin", "giơ ngón tay cái tán thưởng bên cạnh sản phẩm trên bàn"),
            ("nói chuyện trực tiếp với camera", "thao tác nhẹ nhàng trên sản phẩm"),
            ("hướng về phía camera", "hướng về phía sản phẩm"),
            ("đối diện camera", "trên mặt bàn"),
            ("nhìn vào camera", "nhìn xuống sản phẩm"),
        ]
    else:
        replacements = [
            ("Still front-facing", "Still in POV desk view"),
            ("still front-facing", "still in POV desk view"),
            ("Front-facing camera", "First-person POV desk camera looking down"),
            ("front-facing camera", "first-person POV desk camera looking down"),
            ("Front-facing", "POV desk angle"),
            ("front-facing", "POV desk angle"),
            ("Front view, focusing tightly on the character and the product", "Top-down view, focusing tightly on hands operating the product on the desk"),
            ("Front view", "Top-down desk view"),
            ("Return to the final front-facing shot", "Return to the clean top-down desk shot"),
            ("The character is a professional product reviewer, speaking confidently and engagingly with a cheerful expression", "First-person POV product review, hands carefully and neatly presenting the product on the desk"),
            ("The character remains generally in place, performing subtle, natural movements. Maintain character and setting consistency.", "Hands remain in place on the desk, performing smooth natural unboxing and testing movements."),
            ("The person from the reference image is ALREADY holding '{name}' with both hands at chest level and carefully examining it from multiple angles", "Hands are ALREADY holding and inspecting '{name}' on the desk from multiple angles"),
            ("The person from the reference image is ALREADY holding", "Hands are ALREADY holding"),
            ("The character highlights key details", "Hands highlight key details"),
            ("The character holds or gently touches", "Hands hold or gently touch"),
            ("The character", "Hands"),
            ("the character", "the hands"),
            ("They look at the camera and begin sharing honest first impressions with natural speaking gestures.", "Hands gently turn the product over to show all sides while off-camera voiceover shares honest impressions."),
            ("The person is ALREADY holding '{name}' with BOTH HANDS at CHEST LEVEL, facing camera, mid-sentence", "Hands are ALREADY holding '{name}' neatly on the desk"),
            ("The person is ALREADY holding", "Hands are ALREADY holding"),
            ("facing camera, mid-sentence", "at desk level"),
            ("facing the camera, mouth slightly open as if mid-sentence", "on the desk smoothly"),
            ("facing the camera", "on the desk"),
            ("with ONE HAND near FACE level", "above desk level for close-up view"),
            ("near FACE level", "above desk level"),
            ("looking directly into camera with a confident, persuasive smile and double thumbs-up", "resting the product neatly on the table with a reassuring thumbs-up gesture next to the product"),
            ("looking directly into camera with a confident, persuasive smile", "giving a subtle thumbs-up gesture next to the product on the desk"),
            ("End with a confident, persuasive smile and recommendation", "End with a clean macro close-up of the product and an approving thumbs-up gesture on the desk"),
            ("where the product '{name}' and the reviewer appear sharp", "where the product '{name}' and hands appear sharp"),
            ("where the product and the reviewer appear sharp", "where the product and hands appear sharp"),
            ("reviewer and the product", "hands and the product"),
            ("look at the camera and begin", "focus on the product and begin"),
            ("look at the camera", "focus on the product"),
            ("looking directly into camera", "focusing on the product on the desk"),
        ]

    for old, new in replacements:
        prompt = prompt.replace(old, new)

    return prompt


def build_image_prompt(product_name, scene_en, lang="en", review_style=None):
    """Tạo prompt cho Google Flow generate_image.
    Kết hợp: người mẫu (từ ảnh tham chiếu) + sản phẩm (từ ảnh SP) + khung cảnh.
    Tích hợp FRAMING LOCK 9:16 tràn viền và bảo tồn chi tiết sản phẩm tuyệt đối.
    Hỗ trợ POV / Unboxing: loại bỏ hoàn toàn người mẫu, chỉ lấy bàn tay thao tác trên bàn.
    """
    style_str = str(review_style or "").lower()
    is_pov = any(k in style_str for k in ("pov", "unbox", "đập hộp", "góc nhìn thứ nhất"))

    if is_pov:
        if lang == "vi":
            prompt = (
                f"Ảnh chụp đánh giá sản phẩm thương mại điện tử chuyên nghiệp theo góc nhìn thứ nhất POV, giới thiệu '{product_name}', {scene_en}.\n"
                f"FRAMING LOCK: Ảnh chân dung dọc full-frame 9:16 tràn viền, ảnh chụp máy ảnh thật edge-to-edge, TUYỆT ĐỐI KHÔNG viền đen, KHÔNG viền trắng, KHÔNG lề phụ, KHÔNG chia ô collage/storyboard, KHÔNG frame-within-frame.\n"
                f"QUAN TRỌNG NHẤT: Sản phẩm '{product_name}' phải là bản sao CHÍNH XÁC PIXEL-PERFECT từ ảnh sản phẩm tham chiếu — giữ nguyên 100% hình dạng, màu sắc, logo, nhãn mác, bao bì, chất liệu và tỷ lệ thực tế.\n"
                f"TẤT CẢ chữ viết, ký tự, tên thương hiệu in trên sản phẩm phải giữ nguyên TỪNG KÝ TỰ — cùng font, cùng kích cỡ, cùng vị trí. KHÔNG được bịa, thay thế, làm mờ, hay biến dạng chữ trên SP.\n"
                f"BỐ CỤC & CHỦ THỂ: Góc nhìn thứ nhất POV nhìn xuống mặt bàn sạch sẽ. TUYỆT ĐỐI KHÔNG có khuôn mặt, KHÔNG đầu người, KHÔNG thân người mẫu. CHỈ CÓ đôi bàn tay người thật tự nhiên đang cầm, mở hộp hoặc thao tác nhẹ nhàng trên '{product_name}'.\n"
                f"Bàn tay có đúng 5 ngón bình thường, màu da tự nhiên, không che khuất logo hay nhãn mác chính.\n"
                f"Ánh sáng tự nhiên mềm mại, bối cảnh chân thực như chụp bằng smartphone đời thực, không có cảm giác AI giả tạo. Bố cục thương mại cao cấp, độ phân giải cao 8K."
            )
        else:
            prompt = (
                f"Professional e-commerce product review photography in first-person POV perspective, naturally showcasing '{product_name}', {scene_en}.\n"
                f"FRAMING LOCK: Full-frame vertical 9:16 portrait image, edge-to-edge real camera photo, ABSOLUTELY NO borders, NO black bars, NO white margins, NO gutters, NO divider lines, NO frame-within-frame, NO storyboard or collage layout.\n"
                f"MOST CRITICAL: The product '{product_name}' must be a PIXEL-PERFECT, EXACT DUPLICATE from the product reference image — preserve 100% of its shape, colors, logos, labels, textures, materials, and real-world proportions.\n"
                f"ALL text, letters, brand names, logos, and printed info on the product MUST be reproduced CHARACTER-BY-CHARACTER exactly as they appear — same font, size, position. DO NOT invent, replace, blur, or distort any text.\n"
                f"COMPOSITION & SUBJECT: First-person POV looking down at a clean minimalist tabletop. ABSOLUTELY NO human face, NO head, NO human body visible. ONLY a pair of neat, realistic human hands naturally interacting with, holding, or unboxing '{product_name}' on the desk.\n"
                f"Hands have normal five fingers each, natural realistic skin tone, holding the product cleanly without obscuring key logos or labels.\n"
                f"Natural soft lighting, realistic smartphone camera realism, authentic lived-in environment. Photorealistic, ultra high resolution 8K commercial quality."
            )
        return prompt

    if lang == "vi":
        prompt = (
            f"Ảnh chụp đánh giá sản phẩm thương mại điện tử chuyên nghiệp của người mẫu đang cầm và giới thiệu tự nhiên sản phẩm '{product_name}', {scene_en}.\n"
            f"FRAMING LOCK: Ảnh chân dung dọc full-frame 9:16 tràn viền, ảnh chụp máy ảnh thật edge-to-edge, TUYỆT ĐỐI KHÔNG viền đen, KHÔNG viền trắng, KHÔNG lề phụ, KHÔNG chia ô collage/storyboard, KHÔNG frame-within-frame.\n"
            f"QUAN TRỌNG NHẤT: Sản phẩm '{product_name}' phải là bản sao CHÍNH XÁC PIXEL-PERFECT từ ảnh sản phẩm tham chiếu — giữ nguyên 100% hình dạng, màu sắc, logo, nhãn mác, bao bì, chất liệu và tỷ lệ thực tế.\n"
            f"TẤT CẢ chữ viết, ký tự, tên thương hiệu in trên sản phẩm phải giữ nguyên TỪNG KÝ TỰ — cùng font, cùng kích cỡ, cùng vị trí. KHÔNG được bịa, thay thế, làm mờ, hay biến dạng chữ trên SP.\n"
            f"NGƯỜI MẪU: Giữ nguyên hình dáng khuôn mặt, đặc điểm gương mặt, màu da và vóc dáng từ ảnh người mẫu tham chiếu. Trang phục lịch sự, trang nhã, không hở hang, phù hợp với sản phẩm.\n"
            f"Ngón tay cầm/chạm sản phẩm tự nhiên, không che khuất logo hay nhãn mác chính.\n"
            f"Ánh sáng tự nhiên mềm mại, bối cảnh chân thực như chụp bằng smartphone đời thực, không có cảm giác AI giả tạo. Bố cục thương mại cao cấp, độ phân giải cao 8K."
        )
    else:
        prompt = (
            f"Professional e-commerce product review photography of the model naturally holding and presenting '{product_name}', {scene_en}.\n"
            f"FRAMING LOCK: Full-frame vertical 9:16 portrait image, edge-to-edge real camera photo, ABSOLUTELY NO borders, NO black bars, NO white margins, NO gutters, NO divider lines, NO frame-within-frame, NO storyboard or collage layout.\n"
            f"MOST CRITICAL: The product '{product_name}' must be a PIXEL-PERFECT, EXACT DUPLICATE from the product reference image — preserve 100% of its shape, colors, logos, labels, textures, materials, and real-world proportions.\n"
            f"ALL text, letters, brand names, logos, and printed info on the product MUST be reproduced CHARACTER-BY-CHARACTER exactly as they appear — same font, size, position. DO NOT invent, replace, blur, or distort any text.\n"
            f"MODEL: Preserve the exact face shape, facial features, skin tone, and body build from the character reference image. Outfit is elegant, tasteful, modest, and complementary to the product.\n"
            f"Fingers wrap around the product naturally without obscuring key logos or labels.\n"
            f"Natural soft lighting, realistic smartphone camera realism, authentic lived-in environment. Photorealistic, ultra high resolution 8K commercial quality."
        )
    return prompt


def build_tvc_prompt(product_name, lang="en", review_style="Random"):
    """Tạo 1 prompt TVC 8s chuẩn cho video quảng cáo / review sản phẩm.
    Hỗ trợ đầy đủ phong cách:
    - POV / Góc nhìn thứ nhất: TUYỆT ĐỐI KHÔNG có mặt người mẫu, chỉ có 2 bàn tay thao tác trên mặt bàn.
    - Unboxing / Đập hộp: Góc máy từ trên xuống, chỉ có 2 bàn tay bóc hộp / giới thiệu.
    - Demo Công Dụng: Cận cảnh macro 100% vào tính năng sản phẩm, không quay mặt.
    - Các phong cách có MC (Review tự nhiên, Ngồi Review, UGC, v.v.):
        + Malaysia ('my'): 100% Mẫu Nam (handsome Malay male model) an toàn chính sách.
        + Thị trường khác: Mẫu Nữ đẹp thanh lịch theo quốc gia.
    Trả về tuple: (tvc_prompt, label)
    """
    _tvc_lang_map = {
        "en": {"nationality": "American", "language": "English"},
        "vi": {"nationality": "Việt Nam", "language": "tiếng Việt"},
        "id": {"nationality": "Indonesian", "language": "tiếng Indonesia"},
        "my": {"nationality": "Malaysian", "language": "tiếng Malaysia (Bahasa Melayu)"},
        "ph": {"nationality": "Filipino", "language": "Filipino"},
    }
    _tvc = _tvc_lang_map.get(lang, _tvc_lang_map["en"])
    short_name = (product_name or "").strip()[:80].strip()

    style_raw = str(review_style or "").strip()
    if not style_raw or "random" in style_raw.lower() or "🎲" in style_raw:
        style_raw = random.choice([
            "Review tự nhiên", "Ngồi Review", "POV (Góc nhìn thứ nhất)",
            "Unboxing", "UGC Authentic", "Demo Công Dụng", "So Sánh/Đánh Giá"
        ])

    style_lower = style_raw.lower()
    is_pov = any(k in style_lower for k in ("pov", "góc nhìn thứ nhất"))
    is_unbox = any(k in style_lower for k in ("unbox", "đập hộp"))
    is_demo = any(k in style_lower for k in ("demo", "công dụng", "feature"))

    if is_pov:
        prompt = (
            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
            f'A first-person point of view (POV) shot looking down at a clean minimalist tabletop surface. '
            f'ABSOLUTELY NO human face, NO head, NO presenter body visible. '
            f'Only two clean, natural hands are visible holding, rotating, demonstrating, and interacting with the product. '
            f'The hands smoothly showcase the key features, texture, and quality of the product. '
            f'Voiceover speaks in {_tvc["language"]} explaining the product benefits right away without any introduction; no text is displayed in the video. '
            f'The product is accurately sized. '
            f'The product price is not mentioned in the video.'
        )
        return prompt, "POV"

    if is_unbox:
        prompt = (
            f'Create a product advertisement video (TVC) unboxing the product "{short_name}". '
            f'A top-down desk camera angle looking down at a clean tabletop. '
            f'ABSOLUTELY NO human face, NO head, NO presenter body visible. '
            f'Only two clean, natural hands are visible carefully opening packaging, unboxing, and presenting the product. '
            f'The hands smoothly showcase the product details, packaging, and craftsmanship. '
            f'Voiceover speaks in {_tvc["language"]} explaining the product benefits right away without any introduction; no text is displayed in the video. '
            f'The product is accurately sized. '
            f'The product price is not mentioned in the video.'
        )
        return prompt, "Unboxing"

    if is_demo:
        prompt = (
            f'Create a product advertisement video (TVC) demonstrating the product "{short_name}". '
            f'Extreme close-up macro shots focusing 100% on demonstrating and testing the product features, durability, and practical utility on a clean surface. '
            f'ABSOLUTELY NO human face visible. Only clean hands interacting with and testing the product. '
            f'Voiceover speaks in {_tvc["language"]} explaining the product benefits right away without any introduction; no text is displayed in the video. '
            f'The product is accurately sized. '
            f'The product price is not mentioned in the video.'
        )
        return prompt, "Demo Công Dụng"

    if lang == "my":
        prompt = (
            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
            f'A handsome Malay male model, modest clothing (clean long-sleeve shirt, dark trousers), about 25 years old, '
            f'holds the product and introduces its key benefits. '
            f'He states the benefits right away without any introduction. '
            f'He speaks {_tvc["language"]}; no text is displayed in the video. '
            f'The product is accurately sized. '
            f'The product price is not mentioned in the video.'
        )
        return prompt, "Mẫu Nam"
    else:
        prompt = (
            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
            f'A beautiful {_tvc["nationality"]} woman, about 20 years old, holds the product and introduces its key benefits. '
            f'She states the benefits right away without any introduction. '
            f'She speaks {_tvc["language"]}; no text is displayed in the video. '
            f'The product is accurately sized. '
            f'Her outfit is modest and appropriate, not revealing or offensive. '
            f'The product price is not mentioned in the video.'
        )
        return prompt, "Mẫu Nữ"


def build_video_prompts(product_name, scene_en, duration_sec=16, lang="en", review_style="Random", content_style="Review kho hàng"):
    """Sinh list prompt liền mạch dựa trên độ dài video (16s hoặc 24s).
    Tất cả prompt dùng CÙNG khung cảnh + trang phục + ánh sáng
    → đảm bảo đồng bộ visual giữa các đoạn.
    Ngôn ngữ nói được đồng bộ qua {lang_instruction} placeholder.
    """
    # Chuẩn hóa tên style từ dropdown → key trong CONTENT_MAP
    _style_alias = {
        "POV (Góc nhìn thứ nhất)": "POV",
        "UGC Authentic": "UGC",
        "Demo Công Dụng": "Demo công dụng",
    }
    review_style = _style_alias.get(review_style, review_style)

    if review_style in ("🎲 Random", "Random") or not review_style or "random" in str(review_style).lower():
        review_style = random.choice(["Review kho hàng", "Ngồi Review", "POV", "UGC", "Unboxing", "Demo công dụng", "Review tự nhiên", "So Sánh/Đánh Giá"])

    pool = SEGMENT_POOL_VI if lang == "vi" else SEGMENT_POOL_EN
    indices = DURATION_MAP.get(duration_sec, DURATION_MAP[16])
    lang_info = _LANG_MAP.get(lang, _LANG_MAP["en"])
    n_segments = len(indices)
    
    prompts = []
    # Malaysia: random style cho non-fallback
    _my_nf_style = _get_my_character_style() if lang == "my" else None

    for i, idx in enumerate(indices):
        dialogue = generate_tts_script(product_name, i, n_segments, lang=lang)
        prompt = pool[idx].format(
            name=product_name,
            scene=scene_en,
            lang_instruction=lang_info["instruction"],
            country_en=lang_info["country_en"],
            country_vi=lang_info["country_vi"],
            dialogue=dialogue
        )

        # --- Malaysia: thay đổi SECTION 3 theo phương án an toàn ---
        if lang == "my" and _my_nf_style:
            import re as _re
            if _my_nf_style == "product_only":
                product_only_sec3 = (
                    "=== SECTION 3: PRODUCT SHOWCASE (NO HUMAN MODEL) ===\n"
                    "- NO human model, NO presenter in this video.\n"
                    "- Product showcase on clean white/marble background with soft studio lighting.\n"
                    "- Smooth camera rotation around the product, close-up shots from multiple angles.\n"
                    "- Professional e-commerce commercial style.\n"
                    "\n"
                )
                prompt = _re.sub(r'=== SECTION 3:.*?=== SECTION 4:', product_only_sec3 + '=== SECTION 4:', prompt, count=1, flags=_re.DOTALL)
            elif _my_nf_style == "male":
                prompt = prompt.replace("A 22-year-old Malaysian woman", "A 25-year-old Malay male model, modest clothing")
                prompt = prompt.replace("her identity", "his identity")
                prompt = prompt.replace("her outfit", "his outfit")
                prompt = prompt.replace("her face", "his face")
                prompt = prompt.replace("her hairstyle", "his hairstyle")
                prompt = prompt.replace("her clothing", "his clothing")
                prompt = prompt.replace("Keep her seated", "Keep him seated")
                prompt = prompt.replace("Do not show her", "Do not show him")
                prompt = prompt.replace("She states", "He states")
                prompt = prompt.replace("She speaks", "He speaks")
                prompt = prompt.replace("she is", "he is")
                prompt = prompt.replace("She is", "He is")
                prompt = prompt.replace("she ", "he ")
                prompt = prompt.replace("She ", "He ")
                prompt = prompt.replace("her ", "his ")
                prompt = prompt.replace("Her ", "His ")
            elif _my_nf_style == "hijabi":
                prompt = prompt.replace(
                    "A 22-year-old Malaysian woman with a bright, cheerful face and natural beauty",
                    "A Malay hijabi woman, wearing hijab that fully covers ALL hair neck and chest (NO hair visible at all), modest long-sleeve clothing covering arms to wrists, long pants/skirt, no skin showing except face and hands, smiling, approximately 22-28 years old"
                )

        target_style = review_style if review_style in (CONTENT_MAP_VI if lang == "vi" else CONTENT_MAP_EN) else content_style
        if target_style and target_style in (CONTENT_MAP_VI if lang == "vi" else CONTENT_MAP_EN):
            content_constraint = (CONTENT_MAP_VI if lang == "vi" else CONTENT_MAP_EN)[target_style]
            prompt = content_constraint + prompt
        if review_style == "Ngồi Review":
            if lang == "vi":
                sitting_constraint = "[ĐIỀU CHỈNH BỐ CỤC: Người dẫn/reviewer ngồi lịch sự phía sau một chiếc bàn gỗ tối giản trong suốt video. Mọi hành động diễn ra tại bàn này. Không đứng hoặc đi lại. Luôn giữ tư thế ngồi sau bàn. Sản phẩm được đặt trên bàn hoặc được cầm trên tay phía trên mặt bàn.]\n\n"
            else:
                sitting_constraint = "[LAYOUT CONSTRAINT: The presenter is sitting politely behind a clean, minimalist wooden desk throughout the video. All actions are performed while seated at this desk. Do not show the presenter standing or walking. Keep her seated behind the desk. The product is either placed on the desk or held above it.]\n\n"
            prompt = sitting_constraint + prompt

        # Áp dụng chuẩn hóa POV / Unboxing (loại bỏ khuôn mặt, sửa timeline action thành bàn tay trên bàn)
        prompt = _apply_pov_or_unbox_transform(prompt, target_style or review_style, lang=lang)
        prompts.append(prompt)
    return prompts


# ==================== FALLBACK PROMPTS (khi hết quota tạo ảnh) ====================
# Dùng khi TẤT CẢ account hết quota generate_image → không tạo được ảnh composite.
# Ảnh reference CHỈ CÓ sản phẩm → prompt phải MÔ TẢ MC bằng text.
# Vẫn dùng I2V (image-to-video) với ảnh SP làm reference.
# Handoff pose: cuối clip N = đầu clip N+1 → liền mạch khi ghép.
# {hair} và {outfit} được random mỗi sản phẩm → video luôn mới mẻ.

_HAIR_POOL_EN = [
    "long straight black hair",
    "shoulder-length wavy brown hair",
    "short bob cut with dark hair",
    "long curly dark brown hair",
    "medium-length straight hair with subtle highlights",
    "ponytail with bangs, dark hair",
    "long flowing hair with soft waves",
    "elegant updo hairstyle with loose strands",
]

_HAIR_POOL_VI = [
    "tóc đen dài thẳng",
    "tóc nâu ngang vai hơi xoăn",
    "tóc ngắn kiểu bob đen",
    "tóc nâu đen dài xoăn tự nhiên",
    "tóc thẳng dài vừa có highlight nhẹ",
    "tóc buộc đuôi ngựa với mái trước, tóc đen",
    "tóc dài bồng bềnh xoăn sóng nhẹ",
    "tóc búi cao thanh lịch với vài lọn rơi",
]

_OUTFIT_POOL_EN = [
    "a crisp white blouse tucked into high-waisted beige trousers",
    "a soft pastel pink knit sweater with dark jeans",
    "a light blue button-down shirt with rolled sleeves and cream skirt",
    "a classic striped navy-and-white top with tailored pants",
    "an elegant sage green midi dress with subtle floral pattern",
    "a warm beige turtleneck with a brown corduroy skirt",
    "a lavender cardigan over a white camisole with light gray trousers",
    "a chic camel blazer over a black turtleneck with dark slacks",
]

_OUTFIT_POOL_VI = [
    "áo sơ mi trắng bỏ trong quần tây beige cạp cao",
    "áo len hồng pastel nhẹ nhàng phối quần jeans đen",
    "áo sơ mi xanh nhạt xắn tay phối chân váy kem",
    "áo kẻ sọc xanh navy-trắng cổ điển phối quần tây",
    "váy midi xanh lá nhạt thanh lịch có họa tiết hoa nhẹ",
    "áo cổ lọ beige ấm áp phối chân váy nhung nâu",
    "áo cardigan tím lavender khoác ngoài áo hai dây trắng phối quần xám nhạt",
    "áo blazer camel lịch lãm khoác ngoài áo cổ lọ đen phối quần tây đen",
]

# ---- Malaysia (MY) — tuân thủ văn hóa/tôn giáo: 3 phương án an toàn ----
# Style 1: Product-Only (RECOMMENDED — no human model)
_MY_PRODUCT_ONLY_CHARACTER = (
    "- NO human model in this video. Focus entirely on the product.\n"
    "- Show the product '{name}' on a clean white/marble background with soft studio lighting.\n"
    "- Camera smoothly rotates around the product, showing close-up details from multiple angles.\n"
)
# Style 2: Male model (100% cho thị trường Malaysia)
_MY_MALE_HAIR_POOL = [
    "short neat black hair with clean side part, well-groomed",
    "medium-length wavy dark hair, well-groomed and professional",
    "short cropped hair with subtle fade, clean and tidy",
    "neatly styled dark hair, professional and fresh look",
    "short classic taper hairstyle, dark hair, very neat and clean",
]
_MY_MALE_OUTFIT_POOL = [
    "a clean white long-sleeve button-down shirt with dark trousers",
    "a navy blue long-sleeve polo shirt with beige chinos",
    "a smart casual light blue long-sleeve oxford shirt with dark pants",
    "a modern olive green long-sleeve shirt with dark trousers",
    "a minimalist charcoal gray long-sleeve shirt with khaki pants",
    "a light gray modest kurta-style long-sleeve shirt with dark trousers",
]
# Style 3: Female hijabi model (dự phòng)
_MY_HIJAB_HAIR_POOL = [
    "wearing a soft cream-colored hijab that fully covers ALL hair neck and chest (NO hair visible at all), neatly draped",
    "wearing an elegant pastel blue hijab that fully covers ALL hair neck and chest (NO hair visible at all), with clean folds",
    "wearing a stylish dusty rose hijab that fully covers ALL hair neck and chest (NO hair visible at all), with neat pleats",
    "wearing a classic black hijab that fully covers ALL hair neck and chest (NO hair visible at all), simple elegant style",
    "wearing a sage green hijab that fully covers ALL hair neck and chest (NO hair visible at all), with soft draping",
]
_MY_HIJAB_OUTFIT_POOL = [
    "a modest long-sleeve white blouse with high neckline and long dark skirt",
    "a modest loose-fit pastel tunic with long sleeves and wide-leg pants",
    "a modest long-sleeve baju kurung in soft blue with matching long skirt",
    "a modest cream-colored long cardigan over a high-neck top with ankle-length pants",
    "a modest long-sleeve floral blouse fully covering arms with a long flowing skirt",
]

def _get_my_character_style():
    """100% Mẫu Nam (Male Model) an toàn tuyệt đối cho thị trường Malaysia."""
    return "male"

_CONT_FALLBACK_EN = (
    "=== SECTION 1: GENERAL RULES & NEGATIVE CONSTRAINTS ===\n"
    "[DIRECTIVES & PROMPT LOCKS]\n"
    "- The video structure must strictly follow the Timeline Action descriptions with clean continuity.\n"
    "- Ensure perfect temporal consistency — the presenter's face, body, clothing, and the product must remain 100% identical and stable across all frames with no morphing, no identity drift, and no sudden changes.\n"
    "- The product in the reference image is the primary focal point: It must remain clearly visible, properly framed, and in sharp focus throughout the entire video. Maintain its real-world proportions, colors, textures, and details.\n"
    "- FRAMING LOCK: Generate a full-frame vertical 9:16 portrait video. The reference image must fill the entire frame edge-to-edge with NO letterboxing, NO pillarboxing, NO black bars, NO white borders, NO frame-within-frame effect, and NO empty side margins.\n"
    "- PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Its color, shape, size, material texture, and all distinguishing features must NOT change, swap, or gradually transform at any point in the video — especially in the final 1-2 seconds.\n"
    "- REALISTIC PRODUCT SIZE (CRITICAL): The product MUST have its REAL-LIFE, NATURAL size proportional to the human body. DO NOT enlarge or exaggerate product size — small items (cosmetics, phone, bottle) should be naturally small in hands, NOT oversized.\n"
    "- ITEM PERSISTENCE & HAND LOCK: Any object the presenter holds or wears at the start must remain naturally present throughout. The presenter has exactly TWO normal human hands with five fingers each. Do NOT generate extra hands, extra arms, extra fingers, or limb deformations.\n"
    "\n"
    "[NEGATIVE PROMPTS]\n"
    "- No chaotic or unintended rapid morphing. Any camera transitions must feel deliberate, clean, and highly professional.\n"
    "- ABSOLUTELY NO text, NO letters, NO numbers, NO subtitles, NO captions, NO titles, NO watermarks, NO logo overlays, NO HUD, NO UI graphics or artificial text overlays on screen.\n"
    "- ABSOLUTELY NO gibberish, floating symbols, distorted text fonts, alien characters, or random numbers anywhere in the video frame.\n"
    "- No letterbox, no pillarbox, no black bars, no white borders, no side margins, no divider lines, no collage layout, no storyboard layout, no comic-strip layout.\n"
    "- No cartoon, anime, illustration, sketch, storyboard art, hand-drawn look, vector graphics, or stylized CGI. The output must stay natural photorealistic live-action footage.\n"
    "- Color grading is strictly neutral and true-to-life, maintaining a clean white balance without unwanted color tints.\n"
    "- No anatomical anomalies, no extra limbs, no extra hands, no extra fingers, no weird hand deformations.\n"
    "\n"
    "=== SECTION 2: PRODUCT TO ADVERTISE ===\n"
    "- Product: {name}\n"
    "- If the attached reference image includes multiple objects, select ONLY ONE (1) main product as the focal item and ignore all other items.\n"
    "\n"
    "=== SECTION 3: SUBJECT & CHARACTER CONSISTENCY ===\n"
    "- Character: A beautiful {country_en} woman, approximately 20-22 years old with a natural, youthful appearance.\n"
    "- Hair: {hair}.\n"
    "- Outfit: {outfit} — elegant, polite, and modest clothing.\n"
    "- CRITICAL IDENTITY & OUTFIT LOCK: The presenter MUST have the EXACT SAME face, facial features, skin tone, hairstyle ({hair}), and outfit ({outfit}) throughout ALL segments — DO NOT change her identity or clothing across clips.\n"
    "- Voice & Tone: Standard {country_en} tone, lively, energetic, clear articulation, youthful.\n"
    "\n"
    "=== SECTION 4: SCENE & ACTION SEQUENCE ===\n"
    "- Environment: {scene}\n"
)

_CONT_FALLBACK_VI = (
    "=== SECTION 1: GENERAL RULES & NEGATIVE CONSTRAINTS ===\n"
    "[CHỈ THỊ CỐT LÕI & CÁC KHÓA BẢO VỆ]\n"
    "- Cấu trúc video phải tuân thủ nghiêm ngặt mô tả Timeline Action với sự tiếp nối liền mạch.\n"
    "- ĐỒNG BỘ THỜI GIAN TUYỆT ĐỐI: Khuôn mặt, vóc dáng, trang phục của người dẫn và sản phẩm phải giữ nguyên vẹn 100% qua mọi khung hình, không bị trôi danh tính hay biến dạng.\n"
    "- SẢN PHẨM LÀ TRỌNG TÂM: Sản phẩm trong ảnh tham chiếu phải luôn hiển thị rõ ràng, lấy nét sắc nét và giữ đúng tỷ lệ, màu sắc, chi tiết thực tế.\n"
    "- KHÓA KHUNG HÌNH (FRAMING LOCK): Tạo video định dạng dọc full-frame 9:16 tràn viền (edge-to-edge). Hình ảnh lấp đầy toàn bộ khung hình, TUYỆT ĐỐI KHÔNG viền đen (letterbox), KHÔNG viền trắng (pillarbox), KHÔNG lề phụ, KHÔNG chia ô collage/storyboard/comic-strip.\n"
    "- KHÓA TOÀN VẸN SẢN PHẨM (PRODUCT CONSISTENCY LOCK): Sản phẩm xuất hiện ở khung hình đầu tiên phải CHÍNH XÁC LÀ CÙNG MỘT SẢN PHẨM trong mọi khung hình tiếp theo. Màu sắc, hình dáng, kích thước, logo, nhãn mác, chất liệu KHÔNG được thay đổi, tráo đổi hay biến dạng ở bất kỳ thời điểm nào — đặc biệt là trong 1-2 giây cuối cùng.\n"
    "- KÍCH THƯỚC SẢN PHẨM THỰC TẾ (CRITICAL): Sản phẩm PHẢI có kích thước chuẩn như đời thật, tỷ lệ tự nhiên so với cơ thể người. Không phóng to hay phóng đại kích thước sản phẩm quá khổ.\n"
    "- KHÓA GIẢI PHẪU & BÀN TAY (HAND & ANATOMY LOCK): Người dẫn có đúng HAI bàn tay người bình thường với 5 ngón mỗi bàn tay. TUYỆT ĐỐI KHÔNG sinh thêm tay, không thừa ngón tay, không biến dạng chi, không có bàn tay ma. Đồ vật đang cầm/mặc không được tự ý biến mất.\n"
    "\n"
    "[NEGATIVE PROMPTS / RÀNG BUỘC PHỦ ĐỊNH]\n"
    "- Không chuyển đổi hình khối hỗn loạn. Mọi chuyển cảnh phải tự nhiên, mượt mà và chuyên nghiệp.\n"
    "- Tuyệt đối KHÔNG chèn văn bản (text), chữ, số, phụ đề, tiêu đề, logo, watermark hay các phần tử đồ họa UI lên màn hình.\n"
    "- KHÔNG có viền đen, viền trắng, đường phân cách, bố cục truyện tranh hay khung tranh bên trong video.\n"
    "- KHÔNG phong cách hoạt hình, anime, tranh vẽ minh họa, sketch hay CGI cách điệu. Video phải là cảnh quay người thật sống động chuẩn photorealistic.\n"
    "- Cân bằng trắng trung tính, màu da người thật chuẩn xác, độ sâu trường ảnh quang học tự nhiên.\n"
    "- TUYỆT ĐỐI KHÔNG sinh thêm tay, KHÔNG sinh thêm chi, KHÔNG thừa ngón tay, KHÔNG biến dạng bàn tay.\n"
    "- KHÔNG tráo đổi sản phẩm sang biến thể khác.\n"
    "\n"
    "=== SECTION 2: PRODUCT TO ADVERTISE ===\n"
    "- Tên sản phẩm: {name}\n"
    "- Nếu khung hình có nhiều đồ vật, CHỈ TẬP TRUNG vào một sản phẩm chính duy nhất.\n"
    "\n"
    "=== SECTION 3: SUBJECT & CHARACTER CONSISTENCY ===\n"
    "- Character: Một người phụ nữ trẻ {country_vi} khoảng 20-22 tuổi, khuôn mặt tươi tắn, thanh lịch.\n"
    "- Hair: {hair}.\n"
    "- Outfit: {outfit} — trang phục lịch sự, trang nhã, không hở hang.\n"
    "- KHÓA DANH TÍNH (CRITICAL IDENTITY LOCK): Người dẫn phải có ĐÚNG khuôn mặt, kiểu tóc ({hair}), vóc dáng và trang phục ({outfit}) GIỐNG HỆT nhau xuyên suốt TẤT CẢ các đoạn — KHÔNG thay đổi danh tính hay quần áo giữa các clip.\n"
    "- Voice & Tone: Giọng nói rõ ràng chuẩn {country_vi}, tự nhiên, trẻ trung, tự tin.\n"
    "\n"
    "=== SECTION 4: SCENE & ACTION SEQUENCE ===\n"
    "- Bối cảnh: {scene}\n"
)

SEGMENT_POOL_FALLBACK_EN = [
    # ──── 16s FORMAT: 2 CLIPS (FALLBACK — ảnh ref chỉ có SP) ────
    # 0: CLIP 1 — HOOK + DEMO (0-8s)
    (
        _CONT_FALLBACK_EN +
        "- Timeline Action for Segment 1 (0-8 seconds):\n"
        "  * HOOK + DEMO: Eye-catching opening with product demonstration. The presenter reveals '{name}' (from reference image) with an excited expression and 'wow' reaction.\n"
        "  * Camera executes dynamic push-in on the product for an impressive reveal moment.\n"
        "  * Then she smoothly demonstrates how '{name}' works with clear hand movements, showing genuine satisfaction.\n"
        "  * ENDING POSE (CRITICAL HANDOFF): The clip MUST END with the woman holding '{name}' with BOTH HANDS at CHEST LEVEL, facing the camera, smiling — this exact pose will be the starting point of the next segment.\n"
        "  * Seconds 7-8: Freeze into static pose with zero movement drift.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Dynamic push-in on reveal, then medium shot, 35mm lens feel, punchy cinematic daylight.\n"
        "- Color & Grading: Neutral color calibration, natural skin tones, ultra sharp focus on product.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The presenter speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # 1: CLIP 2 — BENEFIT + CTA (8-16s)
    (
        _CONT_FALLBACK_EN +
        "- Timeline Action for Segment 2 (8-16 seconds):\n"
        "  * BENEFIT + CTA: Seamless continuation. CRITICAL: NO greeting or introduction.\n"
        "  * STARTING POSE (MUST MATCH): The SAME presenter (SAME face, SAME hair, SAME outfit) is ALREADY holding '{name}' with BOTH HANDS at CHEST LEVEL — continuing from where she left off.\n"
        "  * She holds '{name}' close to camera, pointing at key features with an impressed nod.\n"
        "  * Camera zooms into tight close-up showing product details, then she holds '{name}' up next to her face with a confident smile and thumbs-up.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Macro close-up then slow cinematic zoom out to medium shot, warm trustworthy lighting.\n"
        "- Color & Grading: Clean white balance, sharp subject separation, professional commercial finish.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The presenter speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # ──── 24s FORMAT: 3 CLIPS (FALLBACK — ảnh ref chỉ có SP, HANDOFF POSE) ────
    # 2: CLIP 1 — REVIEW (0-8s)
    (
        _CONT_FALLBACK_EN +
        "- Timeline Action for Segment 1 of 3 (0-8 seconds):\n"
        "  * Product review opening. CRITICAL: DO NOT start with greeting or waving. Start DIRECTLY with product.\n"
        "  * The presenter is ALREADY holding '{name}' (from reference image) with both hands at chest level and carefully inspecting build quality and surface texture.\n"
        "  * She looks at camera and begins sharing honest first impressions naturally.\n"
        "  * ENDING POSE (CRITICAL HANDOFF): The clip MUST END with the woman holding '{name}' with BOTH HANDS at CHEST LEVEL, facing camera, mouth slightly open as if mid-sentence.\n"
        "  * Seconds 7-8: Freeze into static pose with zero movement drift.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Steady medium shot (waist-up), gentle subtle orbit, 35mm lens feel, natural warm lighting.\n"
        "- Color & Grading: Neutral calibration, natural skin tones, product clearly visible.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The presenter speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # 3: CLIP 2 — DEMO HANDS-ON (8-16s)
    (
        _CONT_FALLBACK_EN +
        "- Timeline Action for Segment 2 of 3 (8-16 seconds):\n"
        "  * Hands-on product demo — seamless continuation. CRITICAL: NO greeting or introduction.\n"
        "  * STARTING POSE (MUST MATCH): The SAME presenter is ALREADY holding '{name}' with BOTH HANDS at CHEST LEVEL, mid-sentence — continuing directly from where she left off.\n"
        "  * She actively demonstrates '{name}' in action: showing sides, pressing buttons, bringing it close to camera for macro view.\n"
        "  * ENDING POSE (CRITICAL HANDOFF): The clip MUST END with the woman holding '{name}' UP with ONE HAND near FACE level, the other hand pointing at the product.\n"
        "  * Seconds 15-16: Freeze into static pose with zero movement drift.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Smooth push-in for tight close-ups of product details and craftsmanship, 50mm lens.\n"
        "- Color & Grading: Consistent warm daylight matching segment 1.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The presenter speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
    # 4: CLIP 3 — TARGET + CTA (16-24s)
    (
        _CONT_FALLBACK_EN +
        "- Timeline Action for Segment 3 of 3 (16-24 seconds):\n"
        "  * Final call to action — seamless continuation. CRITICAL: NO greeting or introduction.\n"
        "  * STARTING POSE (MUST MATCH): The SAME presenter is ALREADY holding '{name}' UP with ONE HAND near FACE level — continuing directly from where she left off.\n"
        "  * She speaks directly to camera with warm tone, using inclusive open palm gestures, then holds '{name}' up with both hands, smiling confidently with a double thumbs-up.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Medium shot with gentle push-in, then slow zoom out to wide shot, professional endorsement ending.\n"
        "- Color & Grading: Clean white balance, sharp subject separation, commercial finish.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} naturally. The presenter speaks this exact dialogue: \"{dialogue}\"]\n\n"
    ),
]

SEGMENT_POOL_FALLBACK_VI = [
    # ──── 16s FORMAT: 2 CLIPS (FALLBACK — ảnh ref chỉ có SP) ────
    # 0: CLIP 1 — HOOK + DEMO (0-8s)
    (
        _CONT_FALLBACK_VI +
        "- Timeline Action cho Đoạn 1 (0-8 giây):\n"
        "  * HOOK + DEMO: Mở đầu bắt mắt chuyển sang trình diễn sản phẩm. Cô gái đưa sản phẩm '{name}' (từ ảnh tham chiếu) ra với biểu cảm ngạc nhiên và phấn khích.\n"
        "  * Camera zoom-in nhanh vào sản phẩm tạo khoảnh khắc reveal ấn tượng, sau đó cô trình diễn cách sử dụng '{name}' với cử chỉ tay tự nhiên.\n"
        "  * TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với cô gái cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC, mặt hướng camera, mỉm cười — tư thế này sẽ là điểm bắt đầu của đoạn tiếp theo.\n"
        "  * Giây 7-8: Chốt lại tư thế tĩnh hoàn toàn, không trôi dạt chuyển động.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Zoom-in khi reveal, sau đó medium shot, 35mm lens, ánh sáng điện ảnh sắc nét.\n"
        "- Màu sắc: Cân bằng trung tính, màu da thật, sản phẩm cực kỳ sắc nét.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
    # 1: CLIP 2 — LỢI ÍCH + CTA (8-16s)
    (
        _CONT_FALLBACK_VI +
        "- Timeline Action cho Đoạn 2 (8-16 giây):\n"
        "  * LỢI ÍCH + CTA: Tiếp nối liền mạch. QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào hay giới thiệu.\n"
        "  * TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): CÙNG cô gái (CÙNG khuôn mặt, CÙNG trang phục) ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC — tiếp tục từ chỗ dừng.\n"
        "  * Cô giơ '{name}' sát camera, chỉ tay vào tính năng nổi bật, sau đó giơ '{name}' lên cạnh gương mặt với nụ cười tự tin và giơ ngón cái lên nhiệt tình.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Cận cảnh macro rồi zoom ra điện ảnh, ánh sáng đáng tin cậy.\n"
        "- Màu sắc: Sạch sẽ, tương phản mềm mại, kết thúc thương mại chuyên nghiệp.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
    # ──── 24s FORMAT: 3 CLIPS (FALLBACK — HANDOFF POSE) ────
    # 2: CLIP 1 — ĐÁNH GIÁ (0-8s)
    (
        _CONT_FALLBACK_VI +
        "- Timeline Action cho Đoạn 1 trên 3 (0-8 giây):\n"
        "  * Mở đầu đánh giá sản phẩm. QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào hay vẫy tay. Bắt đầu TRỰC TIẾP với sản phẩm.\n"
        "  * Cô gái ĐANG cầm '{name}' (từ ảnh tham chiếu) bằng HAI TAY ở tầm NGANG NGỰC và quan sát kỹ lưỡng từ nhiều góc, chia sẻ cảm nhận ban đầu.\n"
        "  * TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với cô gái cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC, mặt hướng camera, miệng hơi mở như đang nói dở.\n"
        "  * Giây 7-8: Chốt lại tư thế tĩnh hoàn toàn, không trôi dạt chuyển động.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Medium shot ổn định, xoay nhẹ tinh tế, 35mm lens, ánh sáng ấm tự nhiên.\n"
        "- Màu sắc: Chuẩn trung tính, màu da thật, sản phẩm sắc nét.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
    # 3: CLIP 2 — DEMO THỰC TẾ (8-16s)
    (
        _CONT_FALLBACK_VI +
        "- Timeline Action cho Đoạn 2 trên 3 (8-16 giây):\n"
        "  * Trình diễn sản phẩm thực tế — tiếp nối liền mạch. QUAN TRỌNG: KHÔNG bắt đầu bằng lời chào hay giới thiệu.\n"
        "  * TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): CÙNG cô gái (CÙNG khuôn mặt, CÙNG trang phục) ĐANG cầm '{name}' bằng HAI TAY ở tầm NGANG NGỰC, đang nói dở — tiếp tục từ chỗ dừng.\n"
        "  * Cô chủ động trình diễn '{name}': lật qua lật lại, mở ngăn, lướt ngón tay cảm nhận chất liệu, đưa sản phẩm gần camera xem chi tiết.\n"
        "  * TƯ THẾ KẾT THÚC (QUAN TRỌNG): Clip PHẢI KẾT THÚC với cô gái giơ '{name}' LÊN CAO bằng MỘT TAY gần tầm MẶT, tay kia đang chỉ vào sản phẩm.\n"
        "  * Giây 15-16: Chốt lại tư thế tĩnh hoàn toàn, không trôi dạt chuyển động.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Push-in cho cận cảnh chi tiết bề mặt, sau đó trở lại medium shot, 50mm lens.\n"
        "- Màu sắc: Đồng bộ tuyệt đối với đoạn trước, ánh sáng tự nhiên.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
    # 4: CLIP 3 — ĐỐI TƯỢNG + CTA (16-24s)
    (
        _CONT_FALLBACK_VI +
        "- Timeline Action cho Đoạn 3 trên 3 (16-24 giây):\n"
        "  * Kêu gọi hành động cuối cùng — tiếp nối liền mạch đến kết thúc. QUAN TRỌNG: KHÔNG chào đón hay vẫy tay.\n"
        "  * TƯ THẾ BẮT ĐẦU (PHẢI KHỚP): CÙNG cô gái (CÙNG khuôn mặt, CÙNG trang phục) ĐANG giơ '{name}' LÊN CAO bằng MỘT TAY gần tầm MẶT — tiếp tục từ chỗ dừng.\n"
        "  * Cô chuyển sang nói trực tiếp vào camera với giọng ấm áp, dùng cử chỉ tay bao quát, sau đó giơ '{name}' lên nổi bật bằng cả hai tay với nụ cười tự tin và giơ hai ngón cái lên nhiệt tình.\n"
        "\n"
        "=== SECTION 5: CAMERA & TECHNICAL SPECIFICATIONS ===\n"
        "- Camera: Medium shot với push-in nhẹ, sau đó zoom ra điện ảnh, ánh sáng đáng tin cậy.\n"
        "- Màu sắc: Sạch sẽ, tương phản mềm mại, kết thúc chuyên nghiệp.\n"
        "\n"
        "=== SECTION 6: DIALOGUE & SPOKEN SCRIPT ===\n"
        "- [{lang_instruction} tự nhiên. Người mẫu nói chính xác câu thoại: \"{dialogue}\"]\n\n"
    ),
]


def clean_product_title(name):
    r"""Làm sạch tên sản phẩm trước khi đưa vào prompt:
    1. Gỡ bỏ thẻ ngoặc quảng cáo: 【 】 [ ] ( ) | - * ~ # $ % ^ & _ = { } \ < > / ? : ; "
    2. Gỡ bỏ toàn bộ từ nhạy cảm / nhãn hiệu / y tế dính bộ lọc Google Veo 3 Policy Filter.
    3. Trả về tối đa 4 từ chữ sạch mượt mà (nếu trống -> 'featured item').
    """
    if not name:
        return "featured item"
    import re
    s = str(name).lower()
    s = re.sub(r"[\【\[\(].*?[\】\]\)]", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    
    policy_risk_words = [
        "100%", "chính hãng", "chinh hang", "đặc trị", "dac tri", "chữa khỏi", "chua khoi",
        "dứt điểm", "dut diem", "phục hồi", "phuc hoi", "thần tốc", "than toc", "cam kết",
        "cam ket", "bao hành", "bao hanh", "replica", "fake", "super fake",
        "bra", "underwear", "panties", "bikini", "crop top", "lace", "breast", "nude",
        "sexy", "erotic", "lingerie", "magsafe", "iphone", "apple", "nike", "adidas",
        "bluetooth", "scratch", "remover", "jump starter", "compressor", "gold", "silver",
        "medicine", "cure", "medical", "treatment", "pill", "cream", "whitening", "slim",
        "slimming", "weight loss", "gun", "knife", "blade", "bomb", "chemical", "poison"
    ]
    for w in policy_risk_words:
        s = re.sub(r"\b" + re.escape(w) + r"\b", "", s, flags=re.IGNORECASE)
    
    words = [w.strip() for w in s.split() if len(w.strip()) > 1]
    clean_str = " ".join(words[:4]).strip()
    return clean_str if clean_str else "featured item"


def build_video_prompts_fallback(product_name, scene_en, duration_sec=16, lang="en", review_style="Random", content_style="Review kho hàng"):
    """Sinh list prompt FALLBACK khi hết quota tạo ảnh.
    Ảnh reference chỉ có sản phẩm → prompt MÔ TẢ MC bằng text.
    Vẫn dùng I2V với ảnh SP làm reference.
    Handoff pose liền mạch giữa các đoạn.
    Kiểu tóc + trang phục random mỗi SP → video luôn mới mẻ.
    """
    product_name_clean = clean_product_title(product_name)
    # Chuẩn hóa tên style từ dropdown → key trong CONTENT_MAP
    _style_alias = {
        "POV (Góc nhìn thứ nhất)": "POV",
        "UGC Authentic": "UGC",
        "Demo Công Dụng": "Demo công dụng",
    }
    review_style = _style_alias.get(review_style, review_style)

    if review_style in ("🎲 Random", "Random") or not review_style or "random" in str(review_style).lower():
        review_style = random.choice(["Review kho hàng", "Ngồi Review", "POV", "UGC", "Unboxing", "Demo công dụng", "Review tự nhiên", "So Sánh/Đánh Giá"])

    pool = SEGMENT_POOL_FALLBACK_VI if lang == "vi" else SEGMENT_POOL_FALLBACK_EN
    indices = DURATION_MAP.get(duration_sec, DURATION_MAP[16])
    lang_info = _LANG_MAP.get(lang, _LANG_MAP["en"])

    # --- Malaysia: 3 phương án an toàn ---
    _my_style = None
    if lang == "my":
        _my_style = _get_my_character_style()
        if _my_style == "male":
            hair = random.choice(_MY_MALE_HAIR_POOL)
            outfit = random.choice(_MY_MALE_OUTFIT_POOL)
        elif _my_style == "hijabi":
            hair = random.choice(_MY_HIJAB_HAIR_POOL)
            outfit = random.choice(_MY_HIJAB_OUTFIT_POOL)
        else:  # product_only
            hair = "N/A"
            outfit = "N/A"
    else:
        hair_pool = _HAIR_POOL_VI if lang == "vi" else _HAIR_POOL_EN
        outfit_pool = _OUTFIT_POOL_VI if lang == "vi" else _OUTFIT_POOL_EN
        hair = random.choice(hair_pool)
        outfit = random.choice(outfit_pool)
    n_segments = len(indices)
    
    prompts = []
    for i, idx in enumerate(indices):
        dialogue = generate_tts_script(product_name_clean, i, n_segments, lang=lang)
        prompt = pool[idx].format(
            name=product_name_clean,
            scene=scene_en,
            lang_instruction=lang_info["instruction"],
            country_en=lang_info["country_en"],
            country_vi=lang_info["country_vi"],
            hair=hair,
            outfit=outfit,
            dialogue=dialogue
        )

        # --- Malaysia: Thay đổi SECTION 3 theo phương án an toàn ---
        if lang == "my" and _my_style:
            if _my_style == "product_only":
                # Thay toàn bộ SECTION 3 bằng mô tả product-only
                import re as _re
                product_only_sec3 = (
                    "=== SECTION 3: PRODUCT SHOWCASE (NO HUMAN MODEL) ===\n"
                    "- NO human model, NO presenter in this video.\n"
                    "- Product showcase on clean white/marble background with soft studio lighting.\n"
                    "- Smooth camera rotation around the product, close-up shots from multiple angles.\n"
                    "- Professional e-commerce commercial style.\n"
                    "\n"
                )
                prompt = _re.sub(r'=== SECTION 3:.*?=== SECTION 4:', product_only_sec3 + '=== SECTION 4:', prompt, count=1, flags=_re.DOTALL)
            elif _my_style == "male":
                # Thay "A beautiful Malaysian woman" → "A Malay male model"
                prompt = prompt.replace("A beautiful Malaysian woman", "A Malay male model, modest clothing")
                prompt = prompt.replace("approximately 20-22 years old with a natural, youthful appearance", "approximately 25-30 years old with a professional, friendly appearance")
                prompt = prompt.replace("her identity", "his identity")
                prompt = prompt.replace("her outfit", "his outfit")
                prompt = prompt.replace("her face", "his face")
                prompt = prompt.replace("her hairstyle", "his hairstyle")
                prompt = prompt.replace("her clothing", "his clothing")
                prompt = prompt.replace("Keep her seated", "Keep him seated")
                prompt = prompt.replace("Do not show her", "Do not show him")
                prompt = prompt.replace("She states", "He states")
                prompt = prompt.replace("She speaks", "He speaks")
                prompt = prompt.replace("she is", "he is")
                prompt = prompt.replace("She is", "He is")
                prompt = prompt.replace("she ", "he ")
                prompt = prompt.replace("She ", "He ")
                prompt = prompt.replace("her ", "his ")
                prompt = prompt.replace("Her ", "His ")
            elif _my_style == "hijabi":
                # Thay description → Hijabi Malay woman
                prompt = prompt.replace(
                    "A beautiful Malaysian woman, approximately 20-22 years old with a natural, youthful appearance",
                    "A Malay hijabi woman, wearing hijab that fully covers ALL hair neck and chest (NO hair visible at all), modest long-sleeve clothing covering arms to wrists, long pants/skirt, no skin showing except face and hands, smiling, approximately 22-28 years old"
                )

        target_style = review_style if review_style in (CONTENT_MAP_VI if lang == "vi" else CONTENT_MAP_EN) else content_style
        if target_style and target_style in (CONTENT_MAP_VI if lang == "vi" else CONTENT_MAP_EN):
            content_constraint = (CONTENT_MAP_VI if lang == "vi" else CONTENT_MAP_EN)[target_style]
            prompt = content_constraint + prompt
        if review_style == "Ngồi Review":
            if lang == "vi":
                sitting_constraint = "[ĐIỀU CHỈNH BỐ CỤC: Người dẫn/reviewer ngồi lịch sự phía sau một chiếc bàn gỗ tối giản trong suốt video. Mọi hành động diễn ra tại bàn này. Không đứng hoặc đi lại. Luôn giữ tư thế ngồi sau bàn. Sản phẩm được đặt trên bàn hoặc được cầm trên tay phía trên mặt bàn.]\n\n"
            else:
                sitting_constraint = "[LAYOUT CONSTRAINT: The presenter is sitting politely behind a clean, minimalist wooden desk throughout the video. All actions are performed while seated at this desk. Do not show the presenter standing or walking. Keep her seated behind the desk. The product is either placed on the desk or held above it.]\n\n"
            prompt = sitting_constraint + prompt

        # Áp dụng chuẩn hóa POV / Unboxing (loại bỏ khuôn mặt, sửa timeline action thành bàn tay trên bàn)
        prompt = _apply_pov_or_unbox_transform(prompt, target_style or review_style, lang=lang)
        prompts.append(prompt)
    return prompts


# ==================== FFMPEG CONCAT ====================

def concat_videos(clip_paths, output_path, log=None):
    """Ghép nhiều video clip thành 1 video hoàn chỉnh bằng FFmpeg.
    Thử copy trước (nhanh), nếu lỗi → re-encode fallback.
    """
    def _log(m):
        if log: log(m)

    if not clip_paths:
        _log("❌ Không có clip nào để ghép!")
        return False

    if len(clip_paths) == 1:
        # Chỉ 1 clip → copy ra output
        import shutil
        shutil.copy2(clip_paths[0], output_path)
        return True

    # Tạo file list cho concat demuxer
    list_file = os.path.join(tempfile.gettempdir(), f"concat_{int(time.time())}_{random.randint(100,999)}.txt")
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for p in clip_paths:
                # FFmpeg cần forward slash hoặc escaped backslash
                f.write(f"file '{p.replace(os.sep, '/')}'\n")

        # Thử 1: stream copy (nhanh, cùng codec)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path
        ]
        _log(f"🔧 FFmpeg concat {len(clip_paths)} clip...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))

        if result.returncode != 0:
            # Thử 2: re-encode (chậm hơn, an toàn hơn)
            _log("⚠️ Copy stream lỗi, chuyển sang re-encode...")
            cmd_reencode = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264", "-preset", "superfast", "-crf", "23",
                "-threads", "1",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path
            ]
            result = subprocess.run(cmd_reencode, capture_output=True, text=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000))

        if result.returncode == 0:
            _log(f"✅ Ghép video xong: {os.path.basename(output_path)}")
            return True
        else:
            _log(f"❌ FFmpeg lỗi: {result.stderr[-200:]}")
            return False

    except subprocess.TimeoutExpired:
        _log("❌ FFmpeg timeout!")
        return False
    except Exception as e:
        _log(f"❌ FFmpeg exception: {e}")
        return False
    finally:
        try:
            if os.path.exists(list_file):
                os.remove(list_file)
        except Exception:
            pass


# ==================== XÓA WATERMARK VEO ====================

def remove_veo_watermark(input_path, log=None, model="veo_3_1", mode="crop"):
    """Xóa watermark Veo / Omni Flash bằng watermark_remover (crop Lanczos hoặc delogo).
    Ghi đè file gốc (ghi tạm → replace).
    Trả True nếu thành công.
    """
    def _log(m):
        if log: log(m)

    if not os.path.isfile(input_path):
        return False

    try:
        import watermark_remover
        ok, msg = watermark_remover.remove_watermark_video(input_path, mode=mode, model=model, log_fn=_log)
        if ok:
            _log(f"🧹 {msg}: {os.path.basename(input_path)}")
            return True
        else:
            _log(f"⚠️ {msg}")
    except Exception as e:
        _log(f"⚠️ watermark_remover lỗi: {e}")

    # Fallback delogo truyền thống nếu watermark_remover không dùng được
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", input_path],
            capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
        parts = probe.stdout.strip().split(",")
        w, h = int(parts[0]), int(parts[1])
    except Exception:
        w, h = 720, 1280

    lw = max(int(w * 0.12), 70)
    lh = max(int(h * 0.05), 28)
    lx = w - lw - max(int(w * 0.015), 8)
    ly = h - lh - max(int(h * 0.015), 8)

    tmp_out = input_path + ".nowm.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"delogo=x={lx}:y={ly}:w={lw}:h={lh}",
        "-c:v", "libx264", "-preset", "superfast", "-crf", "18",
        "-threads", "2",
        "-c:a", "copy",
        "-movflags", "+faststart",
        tmp_out
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000))
        if result.returncode == 0 and os.path.isfile(tmp_out) and os.path.getsize(tmp_out) > 1000:
            os.replace(tmp_out, input_path)
            _log(f"🧹 Đã xóa watermark Veo (fallback): {os.path.basename(input_path)}")
            return True
        else:
            _log(f"⚠️ Xóa watermark lỗi: {result.stderr[-150:] if result.stderr else 'unknown'}")
            try: os.remove(tmp_out)
            except Exception: pass
            return False
    except Exception as e:
        _log(f"⚠️ Xóa watermark exception: {e}")
        try: os.remove(tmp_out)
        except Exception: pass
        return False
        return False


# ==================== UTILS ====================

_MODEL_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def pick_random_model(model_folder):
    """Chọn ngẫu nhiên 1 ảnh người mẫu từ thư mục.
    Trả full-path hoặc None nếu thư mục trống / không hợp lệ.
    """
    if not model_folder or not os.path.isdir(model_folder):
        return None
    imgs = [os.path.join(model_folder, f) for f in os.listdir(model_folder)
            if os.path.splitext(f)[1].lower() in _MODEL_EXTS]
    return random.choice(imgs) if imgs else None


def list_model_images(model_folder):
    """Liệt kê tất cả ảnh người mẫu trong thư mục. Trả list full-path."""
    if not model_folder or not os.path.isdir(model_folder):
        return []
    return sorted([os.path.join(model_folder, f) for f in os.listdir(model_folder)
                   if os.path.splitext(f)[1].lower() in _MODEL_EXTS])


def parse_duration(duration_str):
    """Parse '16s' → 16, '24s' → 24. Mặc định 16."""
    try:
        return int(duration_str.replace("s", "").strip())
    except Exception:
        return 16


def clean_filename(s):
    """Tạo tên file an toàn từ string."""
    return re.sub(r'[^\w\s\-]', '', s).strip().replace(' ', '_')[:60]
