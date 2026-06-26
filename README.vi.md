# DeepWhale — Cầu Nối DeepSeek Web sang API

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker)](https://hub.docker.com/)

> [English](README.md) | **Tiếng Việt**

**DeepWhale** chuyển đổi giao diện web của [DeepSeek Chat](https://chat.deepseek.com) thành một **điểm cuối API tương thích OpenAI** hoàn chỉnh, kèm theo **bảng điều khiển quản trị** để quản lý, kiểm tra và giám sát theo thời gian thực.

Công cụ sử dụng kỹ thuật lấy dấu vân tay trình duyệt qua `cloakbrowser` (Playwright) để vượt qua Cloudflare và các hệ thống chống bot, cho phép truy cập lập trình đáng tin cậy vào các mô hình của DeepSeek.  

**LƯU Ý**:Tôi không biết bằng cách nào nó lại không thể sài đc trên OpenClaude,khi hỏi nó tạo file hay viết code,nó sẽ bị ngắt đoạn và ko thực hiện hành động,tôi chỉ mới test trên Cline,Roo Code,Continue.dev và OpenClaude,và những CLI khác như OpenCode,Blackbox,... thì tôi chưa test,nhưng lỗi đã kể trên xuất hiện rõ nhất ở OpenClaude,còn những CLI khác thì có vẻ vẫn bình thường.Nếu bạn biết lí do hãy trả lời ở phần Issues

---

## Tính Năng

- **API Tương Thích OpenAI** — Thay thế trực tiếp cho `https://api.openai.com/v1`. Hoạt động với mọi OpenAI client (Cline, Roo Code, Continue.dev, OpenRouter, v.v.).
- **Bảng Điều Khiển Quản Trị** — Giao diện web hiện đại với chuyển đổi ngôn ngữ (Tiếng Việt / English), nhật ký thời gian thực, trò chuyện đa lượt, kiểm tra API tương tác và quản lý máy chủ/tài khoản.
- **Vượt Cloudflare** — Sử dụng `cloakbrowser` với kỹ thuật lấy dấu vân tay Chromium thực. Không cần trích xuất cookie thủ công hay giải CAPTCHA.
- **Giải PoW Tự Động** — Tự động giải các thử thách PoW của DeepSeek bằng Web Workers trong trình duyệt, với phương án dự phòng Python thuần túy.
- **Luân Chuyển Tài Khoản** — Cấu hình nhiều tài khoản DeepSeek; máy chủ luân chuyển theo vòng tròn, tự động bỏ qua các lần đăng nhập thất bại.
- **Tự Phục Hồi** — Phát hiện token hết hạn hoặc không hợp lệ và tự động xác thực lại.
- **Streaming & Không Streaming** — Hỗ trợ SSE streaming và JSON tiêu chuẩn. Tự động tiếp tục cho phản hồi dài (tới 8 lượt).
- **Hỗ Trợ Suy Nghĩ/Lý Luận** — Các mô hình như `deepseek-reasoner` hiển thị nội dung suy nghĩ trong phản hồi.
- **Bí Danh Mô Hình** — Ánh xạ bất kỳ tên mô hình nào (`gpt-4o`, `o1`, `qwen-plus`, v.v.) sang mô hình DeepSeek.
- **Trò Chuyện Đa Lượt** — Giao diện trò chuyện tích hợp với lựa chọn mô hình và chế độ suy nghĩ.
- **Nhật Ký Thời Gian Thực** — Luồng nhật ký SSE trực tiếp với mã màu theo danh mục và tự động cuộn.
- **Hỗ Trợ CORS** — Truy cập API từ các công cụ và giao diện web.

---

## Khởi Động Nhanh (Docker)

```bash
# Sao chép và vào thư mục
git clone https://github.com/bchhngsaygez/deepwhale.git
cd deepwhale

# Tạo file .env
cp .env.example .env
# Chỉnh sửa .env với email/mật khẩu DeepSeek của bạn

# Khởi động với Docker Compose
docker compose up -d
```

Mở `http://localhost:5001/admin/login` (mật khẩu mặc định: `admin`).

---

## Cài Đặt Thủ Công

### Yêu Cầu

- Python 3.11+
- pip
- ~2 GB dung lượng ổ đĩa trống (cho Chromium)

### Cài Đặt

```bash
pip install -r requirements.txt
```

Tải bản dựng Chromium cloakbrowser cho nền tảng của bạn từ [trang phát hành CloakBrowser](https://github.com/CloakHQ/cloakbrowser/releases).

### Cấu Hình

```ini
# .env
DEEPSEEK_EMAIL=email_cua_ban@example.com
DEEPSEEK_PASSWORD=mat_khau_cua_ban
API_KEY=sk-my-secret-key-1
PORT=5001
HOST=0.0.0.0
ADMIN_PASSWORD=admin
FLASK_SECRET=bi-mat-ngau-nhien-cua-ban
```

### Khởi Động Máy Chủ

```bash
python server.py
```

### Kiểm Tra Qua Dòng Lệnh

```bash
curl http://localhost:5001/v1/models \
  -H "Authorization: Bearer sk-my-secret-key-1"

curl http://localhost:5001/v1/chat/completions \
  -H "Authorization: Bearer sk-my-secret-key-1" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Xin chào!"}]
  }'
```

---

## Các Điểm Cuối API

| Điểm Cuối | Phương Thức | Xác Thực | Mô Tả |
|---|---|---|---|
| `/v1/models` | GET | Có | Danh sách mô hình |
| `/v1/chat/completions` | POST | Có | Trò chuyện (tương thích OpenAI) |
| `/chat/completions` | POST | Có | Bí danh không có tiền tố phiên bản |
| `/healthz`, `/readyz` | GET | Không | Kiểm tra sức khỏe |
| `/admin/login` | GET/POST | Không | Xác thực quản trị |
| `/admin/dashboard` | GET | Quản trị | Bảng điều khiển web |
| `/admin/api/config` | GET/POST | Quản trị | Cấu hình máy chủ |
| `/admin/api/logs` | GET | Quản trị | Nhật ký đã ghi lại |
| `/admin/api/logs/stream` | GET | Quản trị | Luồng nhật ký trực tiếp (SSE) |
| `/admin/api/accounts-status` | GET | Quản trị | Trạng thái xác thực tài khoản |

---

## Bảng Điều Khiển Quản Trị

Bảng điều khiển có năm phần truy cập từ thanh bên:

| Phần | Mô Tả |
|---|---|
| **Tổng Quan** | Trạng thái máy chủ, số lượng mô hình, trạng thái tài khoản, thời gian hoạt động |
| **Trò Chuyện** | Đối thoại đa lượt với DeepSeek, chọn mô hình, chế độ suy nghĩ |
| **Kiểm Tra** | Lệnh curl có sẵn với nút sao chép + trình xây dựng yêu cầu HTTP tương tác |
| **Nhật Ký** | Xem nhật ký thời gian thực qua SSE, mã màu, tự động cuộn |
| **Cài Đặt** | Cấu hình máy chủ (API key, cổng, địa chỉ, mật khẩu) và quản lý tài khoản |

Chuyển đổi ngôn ngữ giữa **Tiếng Việt** và **English** có sẵn ở góc trên bên phải của bảng điều khiển.

---

## Mô Hình Hỗ Trợ

| ID Mô Hình | Loại | Mô Tả |
|---|---|---|
| `deepseek-v4-flash` | Mặc định | Mô hình đa năng nhanh |
| `deepseek-v4-pro` | Chuyên gia | Suy luận chất lượng cao hơn |
| `deepseek-chat` | Mặc định | Mô hình trò chuyện kế thừa |
| `deepseek-reasoner` | Chuyên gia | Có đầu ra suy nghĩ/lý luận |
| `deepseek-r1` | Chuyên gia | DeepSeek R1 (bật suy nghĩ) |
| `deepseek-v3` | Mặc định | DeepSeek V3 |

Bí danh tích hợp: `gpt-4o`, `gpt-4`, `gpt-3.5-turbo` → `deepseek-v4-flash`; `o3` → `deepseek-v4-pro`; `o1` → `deepseek-reasoner`; `qwen-plus`, `qwen-turbo`, v.v. → `deepseek-v4-flash`.

---

## Cấu Trúc Dự Án

```
deepwhale/
├── server.py              # Flask API + bảng điều khiển quản trị
├── deepseek_client.py     # Phiên trình duyệt, đăng nhập, gọi API
├── pow_solver.py          # Trình giải thử thách PoW
├── utils.py               # Tiện ích dùng chung (UTF-8, tải env)
├── test_client.py         # Kịch bản kiểm tra
├── templates/
│   ├── login.html         # Đăng nhập quản trị (giao diện tối, i18n)
│   └── dashboard.html     # Bảng điều khiển (i18n VI/EN)
├── Dockerfile             # Triển khai container
├── docker-compose.yml     # Thiết lập Docker Compose
├── requirements.txt       # Phụ thuộc Python
├── .env.example           # Mẫu biến môi trường
└── README.md              # Tài liệu (Tiếng Anh)
```

---

## Giấy Phép

[MIT](LICENSE)  

>⭐Nếu bạn thấy kho lưu trữ này hữu ích, vui lòng tặng nó một dấu sao (star).Cảm ơn vì bạn đã sử dụng!⭐
