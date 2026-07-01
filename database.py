import sqlite3
import os
import threading
from datetime import datetime

DB_FILE = "railway_bot.db"
db_lock = threading.Lock()

def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=15.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY,
                room_code VARCHAR(50) UNIQUE NOT NULL,
                room_number VARCHAR(50) NOT NULL,
                floor INTEGER NOT NULL,
                room_type VARCHAR(50),
                area NUMERIC(10, 2),
                price NUMERIC(15, 2) NOT NULL,
                address VARCHAR(255),
                status VARCHAR(50),
                discord_user_id VARCHAR(50),
                discord_username VARCHAR(100),
                discord_link_date DATE,
                discord_link_status VARCHAR(50) DEFAULT 'Unlinked',
                discord_link_code VARCHAR(50)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                role VARCHAR(20) NOT NULL,
                status VARCHAR(20),
                room_id INTEGER
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY,
                full_name VARCHAR(100) NOT NULL,
                gender VARCHAR(10),
                birth_date DATE,
                hometown VARCHAR(150),
                cccd VARCHAR(20),
                phone VARCHAR(20),
                email VARCHAR(100),
                job VARCHAR(100),
                address VARCHAR(255),
                checkin_date DATE,
                deposit NUMERIC(15, 2),
                note TEXT
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY,
                contract_code VARCHAR(50) UNIQUE NOT NULL,
                tenant_id INTEGER,
                room_id INTEGER,
                start_date DATE,
                end_date DATE,
                deposit NUMERIC(15, 2),
                terms TEXT,
                status VARCHAR(50)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY,
                room_id INTEGER,
                contract_id INTEGER,
                invoice_date DATE,
                due_date DATE,
                room_fee NUMERIC(15, 2),
                electricity_fee NUMERIC(15, 2),
                electricity_consumption NUMERIC(10, 2),
                water_fee NUMERIC(15, 2),
                water_consumption NUMERIC(10, 2),
                internet_fee NUMERIC(15, 2),
                garbage_fee NUMERIC(15, 2),
                other_services_fee NUMERIC(15, 2),
                total_amount NUMERIC(15, 2),
                status VARCHAR(50)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY,
                invoice_id INTEGER,
                payment_date DATE,
                amount NUMERIC(15, 2),
                confirmed_by VARCHAR(100),
                status VARCHAR(50),
                notes TEXT
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_message_id INTEGER, -- Maps to Desktop's message id if synced from desktop
                sender_username VARCHAR(50) NOT NULL,
                receiver_username VARCHAR(50) NOT NULL,
                message_type VARCHAR(20) DEFAULT 'text',
                message_content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN DEFAULT FALSE,
                discord_message_id VARCHAR(50) UNIQUE,
                pending_desktop_sync BOOLEAN DEFAULT FALSE
            );
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rooms_discord_user_id ON rooms(discord_user_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_room_id ON invoices(room_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_pending_sync ON messages(pending_desktop_sync);")
            
            conn.commit()
            print("Railway SQLite database schema initialized.")
        except Exception as e:
            conn.rollback()
            print(f"Error initializing Railway DB: {e}")
            raise e
        finally:
            conn.close()

# Synchronizer helpers
def save_room(room: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO rooms (id, room_code, room_number, floor, room_type, area, price, address, status, 
                                            discord_user_id, discord_username, discord_link_status, discord_link_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (room['id'], room['room_code'], room['room_number'], room['floor'], room['room_type'], room['area'], room['price'], 
                  room['address'], room['status'], room['discord_user_id'], room['discord_username'], room['discord_link_status'], room['discord_link_code']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_room(room_id: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM rooms WHERE id = ?;", (room_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_user(user: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO users (id, username, role, status, room_id)
                VALUES (?, ?, ?, ?, ?);
            """, (user['id'], user['username'], user['role'], user['status'], user['room_id']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_user(user_id: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM users WHERE id = ?;", (user_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_tenant(tenant: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO tenants (id, full_name, gender, birth_date, hometown, cccd, phone, email, job, address, checkin_date, deposit, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (tenant['id'], tenant['full_name'], tenant['gender'], tenant['birth_date'], tenant['hometown'], tenant['cccd'], 
                  tenant['phone'], tenant['email'], tenant['job'], tenant['address'], tenant['checkin_date'], tenant['deposit'], tenant['note']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_tenant(tenant_id: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM tenants WHERE id = ?;", (tenant_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_contract(contract: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO contracts (id, contract_code, tenant_id, room_id, start_date, end_date, deposit, terms, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (contract['id'], contract['contract_code'], contract['tenant_id'], contract['room_id'], contract['start_date'], 
                  contract['end_date'], contract['deposit'], contract['terms'], contract['status']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_contract(contract_id: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM contracts WHERE id = ?;", (contract_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_invoice(invoice: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO invoices (id, room_id, contract_id, invoice_date, due_date, room_fee, electricity_fee, electricity_consumption, 
                                               water_fee, water_consumption, internet_fee, garbage_fee, other_services_fee, total_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (invoice['id'], invoice['room_id'], invoice['contract_id'], invoice['invoice_date'], invoice['due_date'], invoice['room_fee'], 
                  invoice['electricity_fee'], invoice['electricity_consumption'], invoice['water_fee'], invoice['water_consumption'], 
                  invoice['internet_fee'], invoice['garbage_fee'], invoice['other_services_fee'], invoice['total_amount'], invoice['status']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_invoice(invoice_id: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM invoices WHERE id = ?;", (invoice_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_payment(payment: dict):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO payments (id, invoice_id, payment_date, amount, confirmed_by, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (payment['id'], payment['invoice_id'], payment['payment_date'], payment['amount'], payment['confirmed_by'], 
                  payment['status'], payment['notes']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_payment(payment_id: int):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM payments WHERE id = ?;", (payment_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

# Messages (Chat) Sync
def save_message_from_desktop(msg: dict):
    with db_lock:
        conn = get_connection()
        try:
            # First check if discord_message_id exists
            res = conn.execute("SELECT id FROM messages WHERE discord_message_id = ?;", (msg['discord_message_id'],)).fetchone()
            if res:
                conn.execute("""
                    UPDATE messages 
                    SET local_message_id = ?, sender_username = ?, receiver_username = ?, 
                        message_type = ?, message_content = ?, timestamp = ?, is_read = ?
                    WHERE id = ?;
                """, (msg['id'], msg['sender_username'], msg['receiver_username'], msg['message_type'], 
                      msg['message_content'], msg['timestamp'], msg['is_read'], res[0]))
            else:
                conn.execute("""
                    INSERT INTO messages (local_message_id, sender_username, receiver_username, message_type, message_content, timestamp, is_read, discord_message_id, pending_desktop_sync)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0);
                """, (msg['id'], msg['sender_username'], msg['receiver_username'], msg['message_type'], 
                      msg['message_content'], msg['timestamp'], msg['is_read'], msg['discord_message_id']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_message_from_tenant(sender_username: str, receiver_username: str, message_content: str, message_type: str, discord_message_id: str) -> bool:
    with db_lock:
        conn = get_connection()
        try:
            res = conn.execute("SELECT id FROM messages WHERE discord_message_id = ?;", (discord_message_id,)).fetchone()
            if not res:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    INSERT INTO messages (sender_username, receiver_username, message_type, message_content, timestamp, is_read, discord_message_id, pending_desktop_sync)
                    VALUES (?, ?, ?, ?, ?, 0, ?, 1);
                """, (sender_username, receiver_username, message_type, message_content, now_str, discord_message_id))
                conn.commit()
                return True
            return False
        except Exception as e:
            conn.rollback()
            print(f"Error saving tenant message: {e}")
            return False
        finally:
            conn.close()

def get_pending_messages():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sender_username, receiver_username, message_type, message_content, timestamp, discord_message_id
            FROM messages
            WHERE pending_desktop_sync = 1 AND sender_username != 'admin'
            ORDER BY id ASC;
        """)
        rows = cursor.fetchall()
        messages = []
        for r in rows:
            messages.append({
                "id": r[0],
                "sender_username": r[1],
                "receiver_username": r[2],
                "message_type": r[3],
                "message_content": r[4],
                "timestamp": r[5],
                "discord_message_id": r[6],
                # If attachment, extract basename
                "filename": os.path.basename(r[4]) if r[3] in ['file', 'image'] else None
            })
        return messages
    finally:
        conn.close()

def acknowledge_messages(msg_ids: list):
    with db_lock:
        conn = get_connection()
        try:
            placeholders = ",".join(["?"] * len(msg_ids))
            conn.execute(f"UPDATE messages SET pending_desktop_sync = 0 WHERE id IN ({placeholders});", msg_ids)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

# Bot operations
def get_room_by_discord_id(discord_user_id: int):
    conn = get_connection()
    try:
        res = conn.execute("SELECT id, room_code, room_number, floor, price, status, discord_username FROM rooms WHERE discord_user_id = ?;", (str(discord_user_id),)).fetchone()
        if res:
            return {
                "id": res[0],
                "room_code": res[1],
                "room_number": res[2],
                "floor": res[3],
                "price": res[4],
                "status": res[5],
                "discord_username": res[6]
            }
        return None
    finally:
        conn.close()

def get_room_by_code(room_code: str):
    conn = get_connection()
    try:
        res = conn.execute("SELECT id, room_code, room_number, floor, price, status, discord_user_id, discord_username, discord_link_status FROM rooms WHERE room_code = ?;", (room_code,)).fetchone()
        if res:
            return {
                "id": res[0],
                "room_code": res[1],
                "room_number": res[2],
                "floor": res[3],
                "price": res[4],
                "status": res[5],
                "discord_user_id": res[6],
                "discord_username": res[7],
                "discord_link_status": res[8]
            }
        return None
    finally:
        conn.close()

def get_linked_rooms_count() -> int:
    conn = get_connection()
    try:
        res = conn.execute("SELECT COUNT(*) FROM rooms;").fetchone()
        return res[0] if res else 0
    finally:
        conn.close()

def link_room_discord(room_code: str, discord_user_id: int, discord_username: str, link_code: str) -> tuple[bool, str]:
    conn = get_connection()
    try:
        room = get_room_by_code(room_code)
        if not room:
            return False, "Mã phòng không tồn tại trên hệ thống."
        
        if room["discord_user_id"]:
            return False, "Phòng này đã liên kết với một tài khoản Discord khác."
        
        # Verify link code
        res_code = conn.execute("SELECT discord_link_code FROM rooms WHERE id = ?;", (room["id"],)).fetchone()
        if not res_code or res_code[0] != link_code.strip():
            return False, "Mã liên kết xác minh không chính xác."
        
        # Verify user not already linked
        already_linked = conn.execute("SELECT room_code FROM rooms WHERE discord_user_id = ?;", (str(discord_user_id),)).fetchone()
        if already_linked:
            return False, f"Tài khoản Discord của bạn đã được liên kết với phòng {already_linked[0]}."
        
        # Do Link
        with db_lock:
            conn2 = get_connection()
            try:
                conn2.execute("""
                    UPDATE rooms 
                    SET discord_user_id = ?, 
                        discord_username = ?, 
                        discord_link_date = ?, 
                        discord_link_status = 'Linked' 
                    WHERE id = ?;
                """, (str(discord_user_id), discord_username, datetime.now().strftime("%Y-%m-%d"), room["id"]))
                conn2.commit()
            except Exception as e:
                conn2.rollback()
                raise e
            finally:
                conn2.close()
                
        return True, "Liên kết tài khoản Discord thành công!"
    except Exception as e:
        return False, f"Lỗi kết nối CSDL: {e}"
    finally:
        conn.close()

def get_latest_invoice_by_room(room_id: int):
    conn = get_connection()
    try:
        res = conn.execute("""
            SELECT id, invoice_date, due_date, room_fee, electricity_fee, electricity_consumption, 
                   water_fee, water_consumption, internet_fee, garbage_fee, other_services_fee, total_amount, status
            FROM invoices 
            WHERE room_id = ? 
            ORDER BY id DESC LIMIT 1;
        """, (room_id,)).fetchone()
        if res:
            return {
                "id": res[0],
                "invoice_date": res[1],
                "due_date": res[2],
                "room_fee": res[3],
                "electricity_fee": res[4],
                "electricity_consumption": res[5],
                "water_fee": res[6],
                "water_consumption": res[7],
                "internet_fee": res[8],
                "garbage_fee": res[9],
                "other_services_fee": res[10],
                "total_amount": res[11],
                "status": res[12]
            }
        return None
    finally:
        conn.close()

def get_tenant_profile_by_room(room_id: int):
    conn = get_connection()
    try:
        res = conn.execute("""
            SELECT t.full_name, t.phone, t.email, t.checkin_date, c.start_date, c.end_date, c.deposit
            FROM tenants t
            JOIN contracts c ON c.tenant_id = t.id
            WHERE c.room_id = ? AND c.status = 'Hiệu lực';
        """, (room_id,)).fetchone()
        if res:
            return {
                "full_name": res[0],
                "phone": res[1],
                "email": res[2] or "Chưa cập nhật",
                "checkin_date": res[3],
                "start_date": res[4],
                "end_date": res[5],
                "deposit": res[6]
            }
        return None
    finally:
        conn.close()

def get_room_username_by_discord_id(discord_user_id: int) -> str:
    room = get_room_by_discord_id(discord_user_id)
    if room:
        conn = get_connection()
        try:
            user_res = conn.execute("SELECT username FROM users WHERE room_id = ? LIMIT 1;", (room["id"],)).fetchone()
            if user_res:
                return user_res[0]
            else:
                return f"phong_{room['room_number']}"
        finally:
            conn.close()
    return f"discord_{discord_user_id}"
