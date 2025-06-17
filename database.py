import sqlite3
from collections import deque
import logging

logger = logging.getLogger(__name__)

# Tên file database. Dùng .db cho rõ ràng.
DATABASE_NAME = 'taixiu_data.db' 
# Độ dài lịch sử cần lưu và lấy ra
HISTORY_LENGTH = 13 

def init_db():
    """Khởi tạo cơ sở dữ liệu và các bảng cần thiết."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Bảng lưu lịch sử kết quả Tài Xỉu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS taixiu_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phien INTEGER UNIQUE,
            ketqua TEXT NOT NULL, -- 'Tài' hoặc 'Xỉu' (nguyên văn)
            ketqua_char TEXT NOT NULL, -- 'T' hoặc 'X' (chuẩn hóa cho AI)
            tong INTEGER,
            xucxac1 INTEGER,
            xucxac2 INTEGER,
            xucxac3 INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Bảng lưu điểm/trọng số của mỗi AI
    # Mức điểm khởi đầu là 100, sẽ thay đổi dựa trên hiệu suất
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_scores (
            ai_name TEXT PRIMARY KEY,
            score REAL NOT NULL
        )
    ''')
    # Khởi tạo điểm cho các AI nếu chưa có
    # Sử dụng INSERT OR IGNORE để không tạo lại nếu đã tồn tại
    for ai_name in ['ai1_trend', 'ai2_defensive', 'ai3_pattern']:
        cursor.execute("INSERT OR IGNORE INTO ai_scores (ai_name, score) VALUES (?, ?)", (ai_name, 100.0))

    # Bảng lưu trạng thái riêng của AI2 (số lần sai liên tiếp)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_states (
            ai_name TEXT PRIMARY KEY,
            consecutive_errors INTEGER DEFAULT 0
        )
    ''')
    # Khởi tạo trạng thái cho AI2 nếu chưa có
    cursor.execute("INSERT OR IGNORE INTO ai_states (ai_name, consecutive_errors) VALUES (?, ?)", ('ai2_defensive', 0))

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")


def add_result(phien, ketqua, ketqua_char, tong, xucxac1, xucxac2, xucxac3):
    """Thêm kết quả phiên Tài Xỉu mới vào lịch sử."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO taixiu_history (phien, ketqua, ketqua_char, tong, xucxac1, xucxac2, xucxac3) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (phien, ketqua, ketqua_char, tong, xucxac1, xucxac2, xucxac3)
        )
        # Giữ lại chỉ HISTORY_LENGTH bản ghi gần nhất dựa trên số phiên
        # (Để đảm bảo chuỗi liên tục theo thời gian)
        cursor.execute(
            "DELETE FROM taixiu_history WHERE id NOT IN (SELECT id FROM taixiu_history ORDER BY phien DESC LIMIT ?)",
            (HISTORY_LENGTH,)
        )
        conn.commit()
        logger.info(f"Added result for phien {phien} ({ketqua_char}) to DB.")
    except sqlite3.IntegrityError:
        logger.warning(f"Result for phien {phien} already exists. Skipping.")
    except Exception as e:
        logger.error(f"Error adding result to DB: {e}")
    finally:
        conn.close()

def get_latest_history():
    """Lấy 13 phiên kết quả gần nhất (dạng 'T' hoặc 'X') từ lịch sử."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    # Sắp xếp theo phiên giảm dần (mới nhất đầu tiên), sau đó đảo ngược để có chuỗi từ cũ đến mới
    cursor.execute("SELECT ketqua_char FROM taixiu_history ORDER BY phien ASC LIMIT ?", (HISTORY_LENGTH,))
    history = deque([row[0] for row in cursor.fetchall()], maxlen=HISTORY_LENGTH)
    conn.close()
    return history

def get_ai_scores():
    """Lấy điểm hiện tại của tất cả các AI."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT ai_name, score FROM ai_scores")
    scores = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return scores

def update_ai_score(ai_name, new_score):
    """Cập nhật điểm cho một AI cụ thể."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE ai_scores SET score = ? WHERE ai_name = ?", (new_score, ai_name))
    conn.commit()
    conn.close()

def get_ai_state(ai_name):
    """Lấy trạng thái của một AI (ví dụ: số lỗi liên tiếp của AI2)."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT consecutive_errors FROM ai_states WHERE ai_name = ?", (ai_name,))
    state = cursor.fetchone()
    conn.close()
    return state[0] if state else 0 # Trả về 0 nếu chưa có trạng thái

def update_ai_state(ai_name, consecutive_errors):
    """Cập nhật trạng thái của một AI (ví dụ: số lỗi liên tiếp của AI2)."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE ai_states SET consecutive_errors = ? WHERE ai_name = ?", (consecutive_errors, ai_name))
    conn.commit()
    conn.close()
