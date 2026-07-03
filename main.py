import os
import json
import time
import logging
import asyncio
from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

import database as database
import discord
from bot import create_bot, logger as bot_logger

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("railway_api")

class ConnectionManager:
    def __init__(self):
        # Maps api_key to a List[WebSocket]
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, api_key: str, websocket: WebSocket):
        await websocket.accept()
        if api_key not in self.active_connections:
            self.active_connections[api_key] = []
        self.active_connections[api_key].append(websocket)
        logger.info(f"WebSocket client connected for landlord {api_key[:8]}... Total connections for landlord: {len(self.active_connections[api_key])}")

    def disconnect(self, api_key: str, websocket: WebSocket):
        if api_key in self.active_connections and websocket in self.active_connections[api_key]:
            self.active_connections[api_key].remove(websocket)
            if not self.active_connections[api_key]:
                del self.active_connections[api_key]
        logger.info(f"WebSocket client disconnected for landlord {api_key[:8]}.")

    async def send_to_landlord(self, api_key: str, message: dict):
        connections = self.active_connections.get(api_key, [])
        if not connections:
            logger.info(f"No active WebSocket connections for landlord {api_key[:8]}... Message stored in Server DB.")
            return
        logger.info(f"Pushing message to {len(connections)} active client(s) of landlord {api_key[:8]}: {message.get('type')}")
        for connection in list(connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending WebSocket message to client of landlord {api_key[:8]}, disconnecting: {e}")
                self.disconnect(api_key, connection)

manager = ConnectionManager()

# Verify API Key dependency
def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    expected_keys = [k.strip() for k in os.environ.get("SYNC_API_KEY", "my_secret_api_key_2026").split(",")]
    if x_api_key not in expected_keys:
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
            count = 0
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):
                    file_mtime = os.path.getmtime(file_path)
                    if file_mtime < cutoff:
                        os.remove(file_path)
                        count += 1
            if count > 0:
                logger.info(f"Cleaned up {count} cached upload files older than {max_age_days} days.")
    except Exception as e:
        logger.error(f"Error during uploads cleanup: {e}")

@app.on_event("startup")
async def startup_event():
    database.init_db()
    cleanup_old_uploads(UPLOAD_DIR, 30)
    token = os.environ.get("DISCORD_TOKEN")
    if token:
        # Start bot as background task in the event loop
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
def health_check(api_key: str = Depends(verify_api_key)):
    guild_id = database.get_guild_id_by_api_key(api_key)
    matching_guild = bot_client.get_guild(int(guild_id)) if (guild_id and bot_client.is_ready()) else None
    
    rooms_count = database.get_linked_rooms_count(api_key)
    is_bot_online = bot_client.is_ready()
    return {
        "status": "Online" if is_bot_online else "Offline",
        "ping": bot_client.latency * 1000 if is_bot_online else 0.0,
        "guilds_count": 1 if matching_guild else 0,
        "users_count": len(matching_guild.members) if matching_guild else 0,
        "uptime": "Active",
        "bot_id": bot_client.user.id if is_bot_online else None,
        "username": bot_client.user.name if is_bot_online else "Offline",
        "guilds_list": [matching_guild.name] if matching_guild else [],
        "rooms_count": rooms_count
    }

# Sync endpoints for table insertions/replacements
@app.post("/sync/rooms")
def sync_room(room: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_room(room, api_key)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing room: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/users")
def sync_user(user: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_user(user, api_key)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing user: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/tenants")
def sync_tenant(tenant: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_tenant(tenant, api_key)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing tenant: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/contracts")
def sync_contract(contract: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_contract(contract, api_key)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing contract: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/invoices")
def sync_invoice(invoice: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_invoice(invoice, api_key)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing invoice: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/payments")
def sync_payment(payment: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.save_payment(payment, api_key)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing payment: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/messages")
async def sync_message(msg: dict, api_key: str = Depends(verify_api_key)):
    try:
        # Save outgoing landlord message to Railway CSDL
        database.save_message_from_desktop(msg, api_key)
        
        # Trigger actual send to Discord if linked
        receiver = msg["receiver_username"]
        conn = database.get_connection()
        try:
            res = conn.execute("""
                SELECT discord_user_id, discord_link_status FROM rooms 
                WHERE api_key = ? AND (('phong_' || room_number) = ? OR room_code = ?);
            """, (api_key, receiver, receiver)).fetchone()
            
            if res and res[1] == 'Linked' and res[0]:
                uid = int(res[0])
                user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
                if user:
                    await user.send(msg["message_content"])
        finally:
            conn.close()
            
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing message: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Sync endpoint for files / attachments from desktop
@app.post("/sync/file")
async def sync_file(
    file: UploadFile = File(...),
    message_id: str = Form(...),
    sender_username: str = Form(...),
    receiver_username: str = Form(...),
    message_type: str = Form(...),
    timestamp: str = Form(...),
    api_key: str = Depends(verify_api_key)
):
    try:
        dest_filename = f"{int(time.time())}_{file.filename}"
        dest_path = os.path.join(UPLOAD_DIR, dest_filename)
        with open(dest_path, 'wb') as f:
            f.write(await file.read())
            
        # File URL served by FastAPI
        server_url = os.environ.get("SYNC_SERVER_URL", "http://localhost:5000").rstrip('/')
        file_url = f"{server_url}/files/{dest_filename}"
        
        msg_dict = {
            "id": int(message_id),
            "sender_username": sender_username,
            "receiver_username": receiver_username,
            "message_type": message_type,
            "message_content": file_url,
            "timestamp": timestamp,
            "is_read": 1,
            "discord_message_id": f"sync_file_{message_id}"
        }
        database.save_message_from_desktop(msg_dict)
        
        # Send to Discord
        conn = database.get_connection()
        try:
            res = conn.execute("""
                SELECT discord_user_id, discord_link_status FROM rooms 
                WHERE ('phong_' || room_number) = ? OR room_code = ?;
            """, (receiver_username, receiver_username)).fetchone()
            
            if res and res[1] == 'Linked' and res[0]:
                uid = int(res[0])
                user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
                if user:
                    disc_file = discord.File(dest_path, filename=file.filename)
                    caption = f"🖼️ Admin gửi ảnh đính kèm: {file.filename}" if message_type == 'image' else f"📄 Admin gửi tệp đính kèm: {file.filename}"
                    await user.send(content=caption, file=disc_file)
        finally:
            conn.close()
            
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error syncing file: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Communication endpoints triggered directly by Desktop GUI calls
@app.post("/sync/send_chat")
async def send_chat(data: dict, api_key: str = Depends(verify_api_key)):
    try:
        uid = int(data["discord_user_id"])
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if user:
            await user.send(data["content"])
            
            # Save it locally on server
            sender = "admin"
            receiver = database.get_room_username_by_discord_id(uid)
            database.save_message_from_tenant(sender, receiver, data["content"], "text", f"send_chat_{int(time.time())}")
            
            return {"status": "success"}
        return JSONResponse(status_code=404, content={"detail": "Discord user not found"})
    except Exception as e:
        logger.error(f"Error in send_chat API: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/send_invoice")
async def send_invoice(request: Request, api_key: str = Depends(verify_api_key)):
    content_type = request.headers.get("content-type", "")
    pdf_path = None
    
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            discord_user_id = int(form["discord_user_id"])
            room_dict = json.loads(form["room_dict_json"])
            file = form.get("file")
            if file:
                filename = file.filename
                pdf_path = os.path.join(UPLOAD_DIR, f"invoice_{int(time.time())}_{filename}")
                with open(pdf_path, 'wb') as f:
                    f.write(await file.read())
        else:
            data = await request.json()
            discord_user_id = int(data["discord_user_id"])
            room_dict = data["room_dict"]
            
        user = bot_client.get_user(discord_user_id) or await bot_client.fetch_user(discord_user_id)
        if not user:
            return JSONResponse(status_code=404, content={"detail": "Discord user not found"})
            
        from bot import build_invoice_embed, build_bank_embed
        invoice_embed = build_invoice_embed(room_dict)
        bank_embed, _ = build_bank_embed(room_dict)
        
        if pdf_path and os.path.exists(pdf_path):
            file_obj = discord.File(pdf_path, filename=os.path.basename(pdf_path))
            await user.send(embed=invoice_embed)
            await user.send(embed=bank_embed, file=file_obj)
        else:
            await user.send(embed=invoice_embed)
            await user.send(embed=bank_embed)
            
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in send_invoice API: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/send_notification")
async def send_notification(data: dict, api_key: str = Depends(verify_api_key)):
    try:
        uid = int(data["discord_user_id"])
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if not user:
            return JSONResponse(status_code=404, content={"detail": "Discord user not found"})
            
        from bot import build_base_embed, COLOR_WARNING
        embed = build_base_embed(
            title=f"📢 THÔNG BÁO: {data['title']}",
            description=data['content'],
            color=COLOR_WARNING
        )
        await user.send(embed=embed)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error in send_notification API: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/send_file")
async def send_file(
    file: UploadFile = File(...),
    discord_user_id: str = Form(...),
    text_content: str = Form(""),
    api_key: str = Depends(verify_api_key)
):
    try:
        uid = int(discord_user_id)
        user = bot_client.get_user(uid) or await bot_client.fetch_user(uid)
        if not user:
            return JSONResponse(status_code=404, content={"detail": "Discord user not found"})
            
        dest_path = os.path.join(UPLOAD_DIR, f"file_{int(time.time())}_{file.filename}")
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
        return database.get_pending_messages(api_key)
    except Exception as e:
        logger.error(f"Error getting pending messages: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/messages/acknowledge")
def acknowledge_messages(payload: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.acknowledge_messages(api_key, payload["ids"])
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error acknowledging messages: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

# Pulling / syncing room link updates back to desktop
@app.get("/sync/rooms/pending")
def get_pending_rooms(api_key: str = Depends(verify_api_key)):
    try:
        return database.get_pending_rooms(api_key)
    except Exception as e:
        logger.error(f"Error getting pending rooms: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.post("/sync/rooms/acknowledge")
def acknowledge_rooms(payload: dict, api_key: str = Depends(verify_api_key)):
    try:
        database.acknowledge_rooms(api_key, payload["ids"])
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error acknowledging rooms: {e}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, x_api_key: Optional[str] = None):
    # Verify API Key
    expected_keys = [k.strip() for k in os.environ.get("SYNC_API_KEY", "my_secret_api_key_2026").split(",")]
    if not x_api_key or x_api_key not in expected_keys:
        logger.warning("WebSocket connection rejected: Invalid API Key")
        await websocket.close(code=4003)
        return
        
    await manager.connect(x_api_key, websocket)
    try:
        while True:
            # Keep connection alive, listen for any messages from client (optional)
            data = await websocket.receive_text()
            logger.debug(f"Received text via WebSocket from {x_api_key[:8]}: {data}")
    except WebSocketDisconnect:
        manager.disconnect(x_api_key, websocket)
    except Exception as e:
        logger.error(f"WebSocket error for landlord {x_api_key[:8]}: {e}")
        manager.disconnect(x_api_key, websocket)

@app.get("/sync/bot_invite_url")
def get_bot_invite_url():
    # Try to resolve bot client's user ID, fallback to standard environment variable or default client ID
    client_id = bot_client.user.id if (bot_client and bot_client.user) else os.environ.get("DISCORD_CLIENT_ID", "1219662706307399750")
    # OAuth2 permissions: Administrator (8)
    invite_url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot%20applications.commands"
    return {"url": invite_url}


