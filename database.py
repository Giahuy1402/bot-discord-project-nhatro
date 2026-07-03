import sqlite3
from typing import Optional
import os
import threading
from datetime import datetime

DB_FILE = os.environ.get("DB_PATH", "railway_bot.db")
db_dir = os.path.dirname(DB_FILE)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)
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
                api_key VARCHAR(100) NOT NULL,
                id INTEGER NOT NULL,
                room_code VARCHAR(50) NOT NULL,
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
                discord_link_code VARCHAR(50),
                pending_desktop_sync BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (api_key, id),
                UNIQUE (api_key, room_code)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                api_key VARCHAR(100) NOT NULL,
                id INTEGER NOT NULL,
                username VARCHAR(50) NOT NULL,
                role VARCHAR(20) NOT NULL,
                status VARCHAR(20),
                room_id INTEGER,
                PRIMARY KEY (api_key, id),
                UNIQUE (api_key, username)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                api_key VARCHAR(100) NOT NULL,
                id INTEGER NOT NULL,
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
                note TEXT,
                PRIMARY KEY (api_key, id)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                api_key VARCHAR(100) NOT NULL,
                id INTEGER NOT NULL,
                contract_code VARCHAR(50) NOT NULL,
                tenant_id INTEGER,
                room_id INTEGER,
                start_date DATE,
                end_date DATE,
                deposit NUMERIC(15, 2),
                terms TEXT,
                status VARCHAR(50),
                PRIMARY KEY (api_key, id),
                UNIQUE (api_key, contract_code)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                api_key VARCHAR(100) NOT NULL,
                id INTEGER NOT NULL,
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
                status VARCHAR(50),
                PRIMARY KEY (api_key, id)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                api_key VARCHAR(100) NOT NULL,
                id INTEGER NOT NULL,
                invoice_id INTEGER,
                payment_date DATE,
                amount NUMERIC(15, 2),
                confirmed_by VARCHAR(100),
                status VARCHAR(50),
                notes TEXT,
                PRIMARY KEY (api_key, id)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key VARCHAR(100) NOT NULL,
                local_message_id INTEGER, -- Maps to Desktop's message id if synced from desktop
                sender_username VARCHAR(50) NOT NULL,
                receiver_username VARCHAR(50) NOT NULL,
                message_type VARCHAR(20) DEFAULT 'text',
                message_content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN DEFAULT FALSE,
                discord_message_id VARCHAR(50),
                pending_desktop_sync BOOLEAN DEFAULT FALSE,
                UNIQUE (api_key, discord_message_id)
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS landlord_guilds (
                api_key VARCHAR(100) PRIMARY KEY,
                guild_id VARCHAR(50) UNIQUE,
                guild_name VARCHAR(100),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rooms_discord_user_id ON rooms(api_key, discord_user_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_room_id ON invoices(api_key, room_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_pending_sync ON messages(api_key, pending_desktop_sync);")
            
            conn.commit()
            print("Railway SQLite database schema initialized (SaaS Multi-Tenant).")
        except Exception as e:
            conn.rollback()
            print(f"Error initializing Railway DB: {e}")
            raise e
        finally:
            conn.close()

# Synchronizer helpers
def save_room(room: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO rooms (api_key, id, room_code, room_number, floor, room_type, area, price, address, status, 
                                            discord_user_id, discord_username, discord_link_status, discord_link_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (api_key, room['id'], room['room_code'], room['room_number'], room['floor'], room['room_type'], room['area'], room['price'], 
                  room['address'], room['status'], room['discord_user_id'], room['discord_username'], room['discord_link_status'], room['discord_link_code']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_room(room_id: int, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM rooms WHERE api_key = ? AND id = ?;", (api_key, room_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_user(user: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO users (api_key, id, username, role, status, room_id)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (api_key, user['id'], user['username'], user['role'], user['status'], user['room_id']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_user(user_id: int, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM users WHERE api_key = ? AND id = ?;", (api_key, user_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_tenant(tenant: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO tenants (api_key, id, full_name, gender, birth_date, hometown, cccd, phone, email, job, address, checkin_date, deposit, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (api_key, tenant['id'], tenant['full_name'], tenant['gender'], tenant['birth_date'], tenant['hometown'], tenant['cccd'], 
                  tenant['phone'], tenant['email'], tenant['job'], tenant['address'], tenant['checkin_date'], tenant['deposit'], tenant['note']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_tenant(tenant_id: int, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM tenants WHERE api_key = ? AND id = ?;", (api_key, tenant_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_contract(contract: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO contracts (api_key, id, contract_code, tenant_id, room_id, start_date, end_date, deposit, terms, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (api_key, contract['id'], contract['contract_code'], contract['tenant_id'], contract['room_id'], contract['start_date'], 
                  contract['end_date'], contract['deposit'], contract['terms'], contract['status']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_contract(contract_id: int, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM contracts WHERE api_key = ? AND id = ?;", (api_key, contract_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_invoice(invoice: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO invoices (api_key, id, room_id, contract_id, invoice_date, due_date, room_fee, electricity_fee, electricity_consumption, 
                                               water_fee, water_consumption, internet_fee, garbage_fee, other_services_fee, total_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (api_key, invoice['id'], invoice['room_id'], invoice['contract_id'], invoice['invoice_date'], invoice['due_date'], invoice['room_fee'], 
                  invoice['electricity_fee'], invoice['electricity_consumption'], invoice['water_fee'], invoice['water_consumption'], 
                  invoice['internet_fee'], invoice['garbage_fee'], invoice['other_services_fee'], invoice['total_amount'], invoice['status']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_invoice(invoice_id: int, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM invoices WHERE api_key = ? AND id = ?;", (api_key, invoice_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_payment(payment: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO payments (api_key, id, invoice_id, payment_date, amount, confirmed_by, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (api_key, payment['id'], payment['invoice_id'], payment['payment_date'], payment['amount'], payment['confirmed_by'], 
                  payment['status'], payment['notes']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def delete_payment(payment_id: int, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM payments WHERE api_key = ? AND id = ?;", (api_key, payment_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

# Messages (Chat) Sync
def save_message_from_desktop(msg: dict, api_key: str):
    with db_lock:
        conn = get_connection()
        try:
            # First check if discord_message_id exists
            res = conn.execute("SELECT id FROM messages WHERE api_key = ? AND discord_message_id = ?;", (api_key, msg['discord_message_id'])).fetchone()
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
                    INSERT INTO messages (api_key, local_message_id, sender_username, receiver_username, message_type, message_content, timestamp, is_read, discord_message_id, pending_desktop_sync)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
                """, (api_key, msg['id'], msg['sender_username'], msg['receiver_username'], msg['message_type'], 
                      msg['message_content'], msg['timestamp'], msg['is_read'], msg['discord_message_id']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def save_message_from_tenant(api_key: str, sender_username: str, receiver_username: str, message_content: str, message_type: str, discord_message_id: str) -> bool:
    with db_lock:
        conn = get_connection()
        try:
            res = conn.execute("SELECT id FROM messages WHERE api_key = ? AND discord_message_id = ?;", (api_key, discord_message_id)).fetchone()
            if not res:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    INSERT INTO messages (api_key, sender_username, receiver_username, message_type, message_content, timestamp, is_read, discord_message_id, pending_desktop_sync)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1);
                """, (api_key, sender_username, receiver_username, message_type, message_content, now_str, discord_message_id))
                conn.commit()
                return True
            return False
        except Exception as e:
            conn.rollback()
            print(f"Error saving tenant message: {e}")
            return False
        finally:
            conn.close()

def get_pending_messages(api_key: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sender_username, receiver_username, message_type, message_content, timestamp, discord_message_id
            FROM messages
            WHERE api_key = ? AND pending_desktop_sync = 1 AND sender_username != 'admin'
            ORDER BY id ASC;
        """, (api_key,))
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

def acknowledge_messages(api_key: str, msg_ids: list):
    with db_lock:
        conn = get_connection()
        try:
            placeholders = ",".join(["?"] * len(msg_ids))
            params = [api_key] + msg_ids
            conn.execute(f"UPDATE messages SET pending_desktop_sync = 0 WHERE api_key = ? AND id IN ({placeholders});", params)
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
        res = conn.execute("SELECT api_key, id, room_code, room_number, floor, price, status, discord_username FROM rooms WHERE discord_user_id = ?;", (str(discord_user_id),)).fetchone()
        if res:
            return {
                "api_key": res[0],
                "id": res[1],
                "room_code": res[2],
                "room_number": res[3],
                "floor": res[4],
                "price": res[5],
                "status": res[6],
                "discord_username": res[7]
            }
        return None
    finally:
        conn.close()

def get_room_by_code(api_key: str, room_code: str):
    conn = get_connection()
    try:
        res = conn.execute("SELECT api_key, id, room_code, room_number, floor, price, status, discord_user_id, discord_username, discord_link_status FROM rooms WHERE api_key = ? AND room_code = ?;", (api_key, room_code)).fetchone()
        if res:
            return {
                "api_key": res[0],
                "id": res[1],
                "room_code": res[2],
                "room_number": res[3],
                "floor": res[4],
                "price": res[5],
                "status": res[6],
                "discord_user_id": res[7],
                "discord_username": res[8],
                "discord_link_status": res[9]
            }
        return None
    finally:
        conn.close()

def get_linked_rooms_count(api_key: str = None) -> int:
    conn = get_connection()
    try:
        if api_key:
            res = conn.execute("SELECT COUNT(*) FROM rooms WHERE api_key = ? AND discord_user_id IS NOT NULL;", (api_key,)).fetchone()
        else:
            res = conn.execute("SELECT COUNT(*) FROM rooms WHERE discord_user_id IS NOT NULL;").fetchone()
        return res[0] if res else 0
    finally:
        conn.close()

def link_room_discord(room_code: str, discord_user_id: int, discord_username: str, link_code: str, guild_id: str = None, guild_name: str = None) -> tuple[bool, str, Optional[str]]:
    conn = get_connection()
    try:
        # Search globally by room_code and discord_link_code to find api_key and room ID
        res = conn.execute("SELECT api_key, id, discord_user_id FROM rooms WHERE room_code = ? AND discord_link_code = ?;", (room_code, link_code.strip())).fetchone()
        if not res:
            return False, "Mã phòng hoặc mã liên kết xác minh không chính xác.", None
            
        api_key, room_id, existing_discord_user_id = res
        if existing_discord_user_id:
            return False, "Phòng này đã liên kết với một tài khoản Discord khác.", api_key
            
        # Verify user not already linked to another room of this landlord
        already_linked = conn.execute("SELECT room_code FROM rooms WHERE api_key = ? AND discord_user_id = ?;", (api_key, str(discord_user_id))).fetchone()
        if already_linked:
            return False, f"Tài khoản Discord của bạn đã được liên kết với phòng {already_linked[0]} của nhà trọ này.", api_key
            
        # Perform Link
        with db_lock:
            conn2 = get_connection()
            try:
                conn2.execute("""
                    UPDATE rooms 
                    SET discord_user_id = ?, 
                        discord_username = ?, 
                        discord_link_date = ?, 
                        discord_link_status = 'Linked',
                        pending_desktop_sync = 1
                    WHERE api_key = ? AND id = ?;
                """, (str(discord_user_id), discord_username, datetime.now().strftime("%Y-%m-%d"), api_key, room_id))
                
                # Auto-Register landlord guild mapping if not present
                if guild_id:
                    conn2.execute("""
                        INSERT OR REPLACE INTO landlord_guilds (api_key, guild_id, guild_name, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP);
                    """, (api_key, str(guild_id), guild_name))
                conn2.commit()
            except Exception as e:
                conn2.rollback()
                raise e
            finally:
                conn2.close()
                
        return True, "Liên kết tài khoản Discord thành công!", api_key
    except Exception as e:
        return False, f"Lỗi kết nối CSDL: {e}", None
    finally:
        conn.close()


def get_latest_invoice_by_room(api_key: str, room_id: int):
    conn = get_connection()
    try:
        res = conn.execute("""
            SELECT id, invoice_date, due_date, room_fee, electricity_fee, electricity_consumption, 
                   water_fee, water_consumption, internet_fee, garbage_fee, other_services_fee, total_amount, status
            FROM invoices 
            WHERE api_key = ? AND room_id = ? 
            ORDER BY id DESC LIMIT 1;
        """, (api_key, room_id)).fetchone()
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

def get_tenant_profile_by_room(api_key: str, room_id: int):
    conn = get_connection()
    try:
        res = conn.execute("""
            SELECT t.full_name, t.phone, t.email, t.checkin_date, c.start_date, c.end_date, c.deposit
            FROM tenants t
            JOIN contracts c ON c.api_key = t.api_key AND c.tenant_id = t.id
            WHERE c.api_key = ? AND c.room_id = ? AND c.status = 'Hiệu lực';
        """, (api_key, room_id)).fetchone()
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
            user_res = conn.execute("SELECT username FROM users WHERE api_key = ? AND room_id = ? LIMIT 1;", (room["api_key"], room["id"])).fetchone()
            if user_res:
                return user_res[0]
            else:
                return f"phong_{room['room_number']}"
        finally:
            conn.close()
    return f"discord_{discord_user_id}"

def get_pending_rooms(api_key: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, room_code, discord_user_id, discord_username, discord_link_status, discord_link_date FROM rooms WHERE api_key = ? AND pending_desktop_sync = 1;", (api_key,))
        rows = cursor.fetchall()
        rooms = []
        for r in rows:
            rooms.append({
                "id": r[0],
                "room_code": r[1],
                "discord_user_id": r[2],
                "discord_username": r[3],
                "discord_link_status": r[4],
                "discord_link_date": str(r[5])
            })
        return rooms
    finally:
        conn.close()

def acknowledge_rooms(api_key: str, room_ids: list):
    with db_lock:
        conn = get_connection()
        try:
            placeholders = ",".join(["?"] * len(room_ids))
            params = [api_key] + room_ids
            conn.execute(f"UPDATE rooms SET pending_desktop_sync = 0 WHERE api_key = ? AND id IN ({placeholders});", params)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

# Landlord Guild mappings
def register_landlord_guild(api_key: str, guild_id: str, guild_name: str):
    if not guild_id:
        return
    with db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO landlord_guilds (api_key, guild_id, guild_name, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP);
            """, (api_key, str(guild_id), guild_name))
            conn.commit()
            print(f"Registered landlord guild mapping: {guild_id} -> {api_key[:8]}...")
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def get_guild_id_by_api_key(api_key: str) -> Optional[str]:
    conn = get_connection()
    try:
        res = conn.execute("SELECT guild_id FROM landlord_guilds WHERE api_key = ?;", (api_key,)).fetchone()
        return res[0] if res else None
    finally:
        conn.close()

def get_api_key_by_guild_id(guild_id: str) -> Optional[str]:
    if not guild_id:
        return None
    conn = get_connection()
    try:
        res = conn.execute("SELECT api_key FROM landlord_guilds WHERE guild_id = ?;", (str(guild_id),)).fetchone()
        return res[0] if res else None
    finally:
        conn.close()

def get_api_key_by_discord_user_id(discord_user_id: int) -> Optional[str]:
    conn = get_connection()
    try:
        res = conn.execute("SELECT api_key FROM rooms WHERE discord_user_id = ? LIMIT 1;", (str(discord_user_id),)).fetchone()
        return res[0] if res else None
    finally:
        conn.close()


