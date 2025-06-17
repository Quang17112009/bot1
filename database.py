import sqlite3
from collections import deque
import logging

logger = logging.getLogger(__name__)

DATABASE_NAME = 'taixiu_data.db'
HISTORY_LENGTH = 13 # Cập nhật lịch sử 13 phiên gần nhất

def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Bảng lưu lịch sử kết quả Tài Xỉu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS taixiu_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phien INTEGER UNIQUE,
            ketqua TEXT NOT NULL, -- 'Tài' hoặc 'Xỉu'
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
    for ai_name in ['ai1_trend', 'ai2_defensive', 'ai3_pattern']:
        cursor.execute("INSERT OR IGNORE INTO ai_scores (ai_name, score) VALUES (?, ?)", (ai_name, 100.0))

    # Bảng lưu trạng thái riêng của AI2 (số lần sai liên tiếp)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_states (
            ai_name TEXT PRIMARY KEY,
            consecutive_errors INTEGER DEFAULT 0
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO ai_states (ai_name, consecutive_errors) VALUES (?, ?)", ('ai2_defensive', 0))


    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")


def add_result(phien, ketqua, tong, xucxac1, xucxac2, xucxac3):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO taixiu_history (phien, ketqua, tong, xucxac1, xucxac2, xucxac3) VALUES (?, ?, ?, ?, ?, ?)",
            (phien, ketqua, tong, xucxac1, xucxac2, xucxac3)
        )
        # Giữ lại chỉ HISTORY_LENGTH bản ghi gần nhất
        cursor.execute(
            "DELETE FROM taixiu_history WHERE id NOT IN (SELECT id FROM taixiu_history ORDER BY phien DESC LIMIT ?)",
            (HISTORY_LENGTH,)
        )
        conn.commit()
        logger.info(f"Added result for phien {phien} ({ketqua}) to DB.")
    except sqlite3.IntegrityError:
        logger.warning(f"Result for phien {phien} already exists. Skipping.")
    finally:
        conn.close()

def get_latest_history():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT ketqua FROM taixiu_history ORDER BY phien DESC LIMIT ?", (HISTORY_LENGTH,))
    # Lấy kết quả và đảo ngược thứ tự để có từ cũ nhất đến mới nhất cho phân tích chuỗi
    history = [row[0][0] for row in cursor.fetchall()][::-1] # Lấy 'T' hoặc 'X'
    conn.close()
    return deque(history, maxlen=HISTORY_LENGTH)

def get_ai_scores():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT ai_name, score FROM ai_scores")
    scores = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return scores

def update_ai_score(ai_name, new_score):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE ai_scores SET score = ? WHERE ai_name = ?", (new_score, ai_name))
    conn.commit()
    conn.close()

def get_ai_state(ai_name):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT consecutive_errors FROM ai_states WHERE ai_name = ?", (ai_name,))
    state = cursor.fetchone()
    conn.close()
    return state[0] if state else 0

def update_ai_state(ai_name, consecutive_errors):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE ai_states SET consecutive_errors = ? WHERE ai_name = ?", (consecutive_errors, ai_name))
    conn.commit()
    conn.close()

