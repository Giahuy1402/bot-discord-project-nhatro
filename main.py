import os
import sys
import asyncio
import logging
import time
from typing import List, Optional, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import discord

# Add current folder to path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import database as database
from bot import create_bot, broadcast_saved_message

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logging.getLogger("anyio").setLevel(logging.WARNING)
logger = logging.getLogger("railway_api")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Remaining connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        logger.info(f"Broadcasting message to {len(self.active_connections)} client(s): {message.get('type')}")
        # Loop through a copy of the list because elements can be removed on disconnect
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending WebSocket message, disconnecting: {e}")
                self.disconnect(connection)

manager = ConnectionManager()

# Verify API Key dependency
def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    expected_key = os.environ.get("SYNC_API_KEY", "my_secret_api_key_2026")
    if x_api_key != expected_key:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")
    return x_api_key

app = FastAPI(title="Gia Huy Home Sync Server")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

bot_client = create_bot()
bot_client.ws_manager = manager

def cleanup_old_uploads(directory: str, max_age_days: int = 30):
    try:
        now = time.time()
        cutoff = now - (max_age_days * 86400)
        if os.path.exists(directory):
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):
                    if os.path.getmtime(file_path) < cutoff:
                        os.remove(file_path)
                        logger.info(f"Cleaned up old uploaded file: {filename}")
    except Exception as e:
        logger.error(f"Error during old uploads cleanup: {e}")

@app.on_event("startup")
async def startup_event():
    # Run database initialization
    database.init_db()
    
    # Run background cleanup of old uploads
    cleanup_old_uploads(UPLOAD_DIR)
    
    # Start Discord Bot client in a background thread/task
    token = os.environ.get("DISCORD_TOKEN")
    if token:
        asyncio.create_task(bot_client.start(token))
        logger.info("Discord Bot background task scheduled successfully.")
    else:
        logger.error("DISCORD_TOKEN not set in environment variables. Bot will not start.")

@app.on_event("shutdown")
async def shutdown_event():
    if not bot_client.is_closed():
        await bot_client.close()
        logger.info("Discord Bot client closed.")

@app.get("/health")
def health_check():
    rooms_count = database.get_linked_rooms_count()
    is_bot_online = bot_client.is_ready()
    return {
        "status": "Online" if is_bot_online else "Offline",
        "ping": bot_client.latency * 1000 if is_bot_online else 0.0,
        "guilds_count": len(bot_client.guilds) if is_bot_online else 0,
        "users_count": len(bot_client.users) if is_bot_online else 0,
        "uptime": "Active",
        "bot_id": bot_client.user.id if is_bot_online else None,
        "username": bot_client.user.name if is_bot_online else "Offline",
        "guilds_list": [g.name for g in bot_client.guilds] if is_bot_online else [],
        "rooms_count": rooms_count
    }

# Sync endpoints for table insertions/replacements
@app.post("/sync/rooms")
def sync_room(room: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_room(room)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing room: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/users")
def sync_user(user: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_user(user)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing user: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/tenants")
def sync_tenant(tenant: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_tenant(tenant)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing tenant: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/contracts")
def sync_contract(contract: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_contract(contract)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing contract: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/invoices")
def sync_invoice(invoice: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_invoice(invoice)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing invoice: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/payments")
def sync_payment(payment: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_payment(payment)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing payment: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/messages")
async def sync_message(msg: dict, api_key: str = Depends(verify_api_key)):
    try:
        # Save outgoing landlord message to Railway CSDL
        database.save_message_from_desktop(msg)
        
        # Trigger actual send to Discord if linked
        receiver = msg["receiver_username"]
        conn = database.get_connection()
        try:
            res = conn.execute("""
                SELECT discord_user_id, discord_link_status FROM rooms 
                WHERE ('phong_' || room_number) = ? OR room_code = ?;
            """, (receiver, receiver)).fetchone()
            
            if res and res[1] == 'Linked' and res[0]:
                uid = int(res[0])
                user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
                if user:
                    # check message content type
                    m_type = msg.get("message_type", "text")
                    m_content = msg.get("message_content", "")
                    
                    if m_type == "text":
                        await user.send(content=m_content)
                        logger.info(f"Forwarded DM to tenant user {uid}: {m_content}")
                    elif m_type in ['file', 'image']:
                        # File path on Desktop must be served relative/absolute on server
                        # In normal setup, the desktop app uploads the file to Railway first,
                        # but in simple websocket setup, let's assume it's uploaded via /sync/upload endpoint
                        # or we directly send the file from server local uploads directory
                        filename = os.path.basename(m_content)
                        file_path = os.path.join(UPLOAD_DIR, filename)
                        if os.path.exists(file_path):
                            disc_file = discord.File(file_path, filename=filename)
                            await user.send(file=disc_file)
                            logger.info(f"Forwarded attachment to tenant user {uid}: {filename}")
                        else:
                            logger.warning(f"File not found on server for WebSocket message: {file_path}")
            return {"status": "success"}
        except Exception as err:
            logger.error(f"Error forwarding message to Discord user: {err}")
            return {"status": "success"} # Still return success to prevent sync retries
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"Error syncing message: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Sync deletions
@app.delete("/sync/{table}/{item_id}")
def sync_delete(table: str, item_id: int, api_key: str = Depends(verify_api_key)):
    try:
        if table == "rooms":
            database.delete_room(item_id)
        elif table == "users":
            database.delete_user(item_id)
        elif table == "tenants":
            database.delete_tenant(item_id)
        elif table == "contracts":
            database.delete_contract(item_id)
        elif table == "invoices":
            database.delete_invoice(item_id)
        elif table == "payments":
            database.delete_payment(item_id)
        else:
            raise HTTPException(status_code=400, detail="Unknown table name")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error executing sync deletion: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# File uploads endpoint
@app.post("/sync/upload")
async def sync_upload(
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key)
):
    try:
        # Save file to upload directory
        dest_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(dest_path, "wb") as f:
            f.write(await file.read())
        logger.info(f"Uploaded file saved to {dest_path}")
        return {"status": "success", "url": f"/files/{file.filename}"}
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/send_chat")
async def send_chat_api(payload: dict, api_key: str = Depends(verify_api_key)):
    try:
        uid = int(payload["discord_user_id"])
        content = payload["content"]
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if not user:
            raise HTTPException(status_code=404, detail="Discord user not found")
        await user.send(content=content)
        logger.info(f"Forwarded direct send_chat to user {uid}: {content}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in send_chat API: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/send_notification")
async def send_notification_api(payload: dict, api_key: str = Depends(verify_api_key)):
    try:
        uid = int(payload["discord_user_id"])
        title = payload["title"]
        content = payload["content"]
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if not user:
            raise HTTPException(status_code=404, detail="Discord user not found")
        
        from bot import build_base_embed
        embed = build_base_embed(title=title, description=content)
        await user.send(embed=embed)
        logger.info(f"Forwarded notification embed to user {uid}: {title}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in send_notification API: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Direct send endpoint for invoices
@app.post("/sync/send_invoice")
async def send_invoice(
    discord_user_id: str = Form(...),
    room_dict_json: str = Form(...),
    file: Optional[UploadFile] = File(None),
    api_key: str = Depends(verify_api_key)
):
    import json
    try:
        uid = int(discord_user_id)
        room_dict = json.loads(room_dict_json)
        
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if not user:
            raise HTTPException(status_code=404, detail="Discord user not found or not in shared guilds")
            
        # Parse invoice details
        invoice = database.get_latest_invoice_by_room(room_dict["id"])
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice details not synced yet for this room")
            
        # Render embed
        from bot import build_invoice_embed
        embed = build_invoice_embed(room_dict)
        
        # Save attachment file if uploaded
        disc_file = None
        if file:
            dest_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(dest_path, "wb") as f:
                f.write(await file.read())
            disc_file = discord.File(dest_path, filename=file.filename)
            
        # Send
        await user.send(embed=embed, file=disc_file)
        logger.info(f"Invoice notification sent directly to tenant {uid}.")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error sending invoice notification: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Send file directly
@app.post("/sync/send_file")
async def send_file_api(
    discord_user_id: str = Form(...),
    text_content: Optional[str] = Form(None),
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key)
):
    try:
        uid = int(discord_user_id)
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        dest_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(dest_path, 'wb') as f:
            f.write(await file.read())
            
        disc_file = discord.File(dest_path, filename=file.filename)
        await user.send(content=text_content if text_content else None, file=disc_file)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in send_file API: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Pulling / syncing tenant messages back to desktop
@app.get("/sync/messages/pending")
def get_pending_messages(api_key: str = Depends(verify_api_key)):
    try:
        return database.get_pending_messages()
    except Exception as e:
        logger.error(f"Error getting pending messages: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/messages/acknowledge")
def acknowledge_messages(payload: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.acknowledge_messages(payload["ids"])
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error acknowledging messages: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Pulling / syncing room link updates back to desktop
@app.get("/sync/rooms/pending")
def get_pending_rooms(api_key: str = Depends(verify_api_key)):
    try:
        return database.get_pending_rooms()
    except Exception as e:
        logger.error(f"Error getting pending rooms: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/rooms/acknowledge")
def acknowledge_rooms(payload: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.acknowledge_rooms(payload["ids"])
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error acknowledging rooms: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, x_api_key: Optional[str] = None):
    # Verify API Key
    expected_key = os.environ.get("SYNC_API_KEY", "my_secret_api_key_2026")
    if x_api_key != expected_key:
        logger.warning("WebSocket connection rejected: Invalid API Key")
        await websocket.close(code=4003)
        return
        
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for any messages from client (optional)
            data = await websocket.receive_text()
            logger.debug(f"Received text via WebSocket: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

@app.get("/sync/bot_invite_url")
def get_bot_invite_url():
    # Try to resolve bot client's user ID, fallback to standard environment variable or default client ID
    client_id = bot_client.user.id if (bot_client and bot_client.user) else os.environ.get("DISCORD_CLIENT_ID", "1219662706307399750")
    # OAuth2 permissions: Administrator (8)
    invite_url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot%20applications.commands"
    return {"url": invite_url}
