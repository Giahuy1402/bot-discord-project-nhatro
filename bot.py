import os
import re
import time
import asyncio
import logging
import urllib.parse
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

import discord
from discord.ext import commands
from discord import app_commands

import database as database

# Theme Colors
COLOR_PRIMARY = discord.Color.from_rgb(31, 106, 165)    # Slate Blue
COLOR_SUCCESS = discord.Color.from_rgb(46, 189, 89)    # Emerald Green
COLOR_WARNING = discord.Color.from_rgb(243, 156, 18)   # Amber Orange
COLOR_DANGER = discord.Color.from_rgb(231, 76, 60)     # Crimson Red
COLOR_INFO = discord.Color.from_rgb(155, 89, 182)       # Purple

# Setup logger
logger = logging.getLogger("railway_bot")

def broadcast_saved_message(bot, sender_username, receiver_username, message_content, message_type, discord_message_id):
    if hasattr(bot, 'ws_manager') and bot.ws_manager:
        conn = database.get_connection()
        try:
            res = conn.execute("SELECT id, timestamp, api_key FROM messages WHERE discord_message_id = ?;", (discord_message_id,)).fetchone()
            if res:
                msg_id, timestamp, api_key = res
                payload = {
                    "type": "new_message",
                    "data": {
                        "id": msg_id,
                        "sender_username": sender_username,
                        "receiver_username": receiver_username,
                        "message_type": message_type,
                        "message_content": message_content,
                        "timestamp": str(timestamp),
                        "discord_message_id": discord_message_id
                    }
                }
                asyncio.create_task(bot.ws_manager.send_to_landlord(api_key, payload))
        except Exception as e:
            logger.error(f"Error broadcasting WebSocket message: {e}")
        finally:
            conn.close()

def broadcast_link_room(bot, api_key, room_code, discord_user_id, discord_username):
    if hasattr(bot, 'ws_manager') and bot.ws_manager:
        room = database.get_room_by_code(api_key, room_code)
        if room:
            payload = {
                "type": "room_linked",
                "data": {
                    "id": room["id"],
                    "room_code": room["room_code"],
                    "discord_user_id": str(discord_user_id),
                    "discord_username": discord_username,
                    "discord_link_status": "Linked",
                    "discord_link_date": datetime.now().strftime("%Y-%m-%d")
                }
            }
            asyncio.create_task(bot.ws_manager.send_to_landlord(api_key, payload))

def get_payment_info() -> Dict[str, str]:
    """Loads banking settings from environment variables."""
    return {
        "bank_name": os.environ.get("BANK_NAME", "Vietcombank"),
        "bank_account": os.environ.get("BANK_ACCOUNT", "123456789"),
        "bank_owner": os.environ.get("BANK_OWNER", "NGUYEN GIA HUY")
    }

def build_base_embed(title: str, description: str, color: discord.Color = COLOR_PRIMARY) -> discord.Embed:
    """Helper to build a unified style Discord embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="GIA HUY HOME • Hệ thống Quản lý Phòng trọ Cao cấp")
    return embed

def build_invoice_embed(room: Dict[str, Any]) -> discord.Embed:
    """Builds the latest invoice embed."""
    room_id = room["id"]
    room_num = room["room_number"]
    invoice = database.get_latest_invoice_by_room(room_id)
    
    if not invoice:
        return build_base_embed(
            title=f"🧾 Hóa đơn Phòng {room_num}",
            description="Hiện tại phòng của bạn chưa có hóa đơn nào được khởi tạo.",
            color=COLOR_WARNING
        )
        
    status = invoice["status"]
    color = COLOR_SUCCESS if status == "Đã thanh toán" else (COLOR_WARNING if status == "Thanh toán một phần" else COLOR_DANGER)
    
    desc = f"Dưới đây là chi tiết hóa đơn tháng của **Phòng {room_num}**:\n"
    embed = build_base_embed(title=f"🧾 Chi tiết Hóa đơn - Phòng {room_num}", description=desc, color=color)
    
    # Fields
    embed.add_field(name="📅 Ngày lập", value=str(invoice["invoice_date"]), inline=True)
    embed.add_field(name="⏳ Hạn đóng", value=str(invoice["due_date"]), inline=True)
    embed.add_field(name="📌 Trạng thái", value=f"**{status.upper()}**", inline=True)
    
    breakdown = (
        f"• **Tiền thuê phòng**: {float(invoice['room_fee']):,.0f} đ\n"
        f"• **Tiền điện ({invoice['electricity_consumption']} kWh)**: {float(invoice['electricity_fee']):,.0f} đ\n"
        f"• **Tiền nước ({invoice['water_consumption']} m³)**: {float(invoice['water_fee']):,.0f} đ\n"
        f"• **Tiền mạng Internet**: {float(invoice['internet_fee']):,.0f} đ\n"
        f"• **Phí thu gom rác**: {float(invoice['garbage_fee']):,.0f} đ\n"
        f"• **Chi phí dịch vụ khác**: {float(invoice['other_services_fee']):,.0f} đ\n"
    )
    embed.add_field(name="💰 Chi tiết các khoản phí", value=breakdown, inline=False)
    embed.add_field(name="🔴 TỔNG CỘNG CẦN ĐÓNG", value=f"### {float(invoice['total_amount']):,.0f} đ", inline=False)
    
    return embed

def build_payment_embed(room: Dict[str, Any]) -> discord.Embed:
    """Builds the payment instructions and status embed."""
    room_id = room["id"]
    room_num = room["room_number"]
    invoice = database.get_latest_invoice_by_room(room_id)
    
    if not invoice:
        return build_base_embed(
            title=f"💰 Trạng thái Thanh toán - Phòng {room_num}",
            description="Phòng của bạn hiện chưa có hóa đơn nợ phí nào.",
            color=COLOR_SUCCESS
        )
        
    status = invoice["status"]
    total = float(invoice["total_amount"])
    
    if status == "Đã thanh toán":
        desc = f"🎉 Tuyệt vời! Hóa đơn tháng này của **Phòng {room_num}** đã được thanh toán hoàn tất.\nCảm ơn bạn đã đóng tiền phòng đúng hạn!"
        return build_base_embed(title=f"💰 Trạng thái Thanh toán - Phòng {room_num}", description=desc, color=COLOR_SUCCESS)
        
    # Unpaid or partially paid
    desc = (
        f"Hóa đơn của **Phòng {room_num}** hiện tại **{status.upper()}**.\n"
        f"Số tiền cần thanh toán: **{total:,.0f} đ**.\n\n"
        f"Vui lòng nhấn nút **[Chuyển khoản]** dưới đây hoặc chạy lệnh `/bank` để lấy thông tin tài khoản ngân hàng và mã QR thanh toán nhanh."
    )
    return build_base_embed(title=f"💰 Trạng thái Thanh toán - Phòng {room_num}", description=desc, color=COLOR_DANGER)

def build_utilities_embed(room: Dict[str, Any]) -> discord.Embed:
    """Builds the utility metrics embed."""
    room_id = room["id"]
    room_num = room["room_number"]
    invoice = database.get_latest_invoice_by_room(room_id)
    
    if not invoice:
        return build_base_embed(
            title=f"⚡ Chỉ số Điện nước - Phòng {room_num}",
            description="Chưa ghi nhận chỉ số điện nước tháng này.",
            color=COLOR_WARNING
        )
        
    desc = (
        f"Chỉ số điện nước tiêu thụ tháng này của **Phòng {room_num}**:\n\n"
        f"⚡ **Điện tiêu thụ**: `{invoice['electricity_consumption']} kWh` → **{float(invoice['electricity_fee']):,.0f} đ**\n"
        f"💧 **Nước tiêu thụ**: `{invoice['water_consumption']} m³` → **{float(invoice['water_fee']):,.0f} đ**\n\n"
        f"Mọi thắc mắc về chỉ số vui lòng liên hệ trực tiếp chủ trọ qua nút chat hoặc lệnh `/support`."
    )
    return build_base_embed(title=f"⚡ Chỉ số Điện nước - Phòng {room_num}", description=desc, color=COLOR_INFO)

def build_bank_embed(room: Optional[Dict[str, Any]] = None, amount_override: Optional[float] = None) -> Tuple[discord.Embed, Optional[str]]:
    """Builds the bank transfer details and VietQR code image URL."""
    bank = get_payment_info()
    
    bank_name = bank["bank_name"]
    bank_acc = bank["bank_account"]
    bank_owner = bank["bank_owner"]
    
    amount = 0.0
    syntax = "Dong tien phong"
    room_num = "unknown"
    
    if room:
        room_num = room["room_number"]
        syntax = f"Phong {room_num} dong tien phong"
        if amount_override is not None:
            amount = amount_override
        else:
            invoice = database.get_latest_invoice_by_room(room["id"])
            if invoice:
                amount = float(invoice["total_amount"])
    
    desc = (
        f"### 🏦 THÔNG TIN TÀI KHOẢN NGÂN HÀNG\n"
        f"• **Ngân hàng**: `{bank_name}`\n"
        f"• **Số tài khoản**: `{bank_acc}`\n"
        f"• **Chủ tài khoản**: `{bank_owner.upper()}`\n"
        f"• **Số tiền**: **{amount:,.0f} đ**\n"
        f"• **Nội dung chuyển khoản**: `{syntax}`\n\n"
        f"Quét mã QR dưới đây trong ứng dụng ngân hàng của bạn để tự động điền số tiền và nội dung chuyển khoản."
    )
    
    embed = build_base_embed(title="🏦 Thông tin Thanh toán Chuyển khoản", description=desc, color=COLOR_SUCCESS)
    
    # Generate VietQR link
    qr_url = None
    if amount > 0:
        syntax_enc = urllib.parse.quote(syntax)
        owner_enc = urllib.parse.quote(bank_owner)
        qr_url = f"https://img.vietqr.io/image/{bank_name}-{bank_acc}-compact2.png?amount={int(amount)}&addInfo={syntax_enc}&accountName={owner_enc}"
        embed.set_image(url=qr_url)
        
    return embed, qr_url

def build_profile_embed(room: Dict[str, Any]) -> discord.Embed:
    """Builds the tenant profile details embed."""
    room_num = room["room_number"]
    profile = database.get_tenant_profile_by_room(room["id"])
    
    if not profile:
        return build_base_embed(
            title=f"👤 Hồ sơ Khách thuê - Phòng {room_num}",
            description="Phòng của bạn hiện chưa được gắn với hợp đồng khách thuê nào đang hoạt động.",
            color=COLOR_WARNING
        )
        
    desc = (
        f"### 👤 THÔNG TIN KHÁCH THUÊ PHÒNG {room_num}\n"
        f"• **Họ và tên**: **{profile['full_name'].upper()}**\n"
        f"• **Số điện thoại**: `{profile['phone']}`\n"
        f"• **Email**: `{profile['email']}`\n"
        f"• **Ngày dọn vào**: `{profile['checkin_date']}`\n"
        f"• **Thời hạn hợp đồng**: Từ `{profile['start_date']}` đến `{profile['end_date']}`\n"
        f"• **Tiền đặt cọc đã nộp**: `{float(profile['deposit']):,.0f} đ`"
    )
    return build_base_embed(title=f"👤 Hồ sơ Khách thuê - Phòng {room_num}", description=desc, color=COLOR_PRIMARY)

def build_support_instructions() -> discord.Embed:
    """Builds instructions on how to use support."""
    desc = (
        "💬 **HỖ TRỢ LIÊN HỆ CHỦ TRỌ**\n\n"
        "Để gửi tin nhắn trực tiếp đến phần mềm quản lý của chủ trọ, bạn có thể thực hiện theo 2 cách:\n"
        "1. Sử dụng lệnh: `/support <nội dung tin nhắn>`\n"
        "2. Nhắn tin riêng (DM) trực tiếp cho Bot này.\n\n"
        "Chủ trọ sẽ nhận được tin nhắn và phản hồi lại bạn ngay trên phần mềm desktop. Bạn sẽ nhận được câu trả lời qua tin nhắn riêng của Bot!"
    )
    return build_base_embed(title="💬 Hướng dẫn Liên hệ Hỗ trợ", description=desc, color=COLOR_INFO)


class MenuView(discord.ui.View):
    """Interactive Button panel displayed when /menu is triggered."""
    def __init__(self, discord_user_id: int):
        super().__init__(timeout=180.0)
        self.discord_user_id = discord_user_id
        
    async def get_room(self, interaction: discord.Interaction) -> Optional[Dict[str, Any]]:
        room = database.get_room_by_discord_id(self.discord_user_id)
        if not room:
            embed = build_base_embed(
                title="❌ Tài khoản Chưa Liên Kết",
                description="Tài khoản Discord này chưa được liên kết với bất kỳ phòng trọ nào.\n\n"
                            "Vui lòng dùng lệnh sau để liên kết:\n"
                            "`/link <mã_phòng> <mã_xác_minh>`\n"
                            "*Ví dụ: `/link P101 ABCD1234`*",
                color=COLOR_DANGER
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return None
        return room

    @discord.ui.button(label="📄 Hóa đơn", style=discord.ButtonStyle.primary, row=0)
    async def btn_invoice(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_room(interaction)
        if room:
            embed = build_invoice_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💰 Thanh toán", style=discord.ButtonStyle.success, row=0)
    async def btn_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_room(interaction)
        if room:
            embed = build_payment_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="⚡ Điện nước", style=discord.ButtonStyle.secondary, row=0)
    async def btn_utilities(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_room(interaction)
        if room:
            embed = build_utilities_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🏦 Chuyển khoản", style=discord.ButtonStyle.success, row=1)
    async def btn_bank(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_room(interaction)
        if room:
            embed, _ = build_bank_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💬 Liên hệ chủ trọ", style=discord.ButtonStyle.primary, row=1)
    async def btn_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_support_instructions()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="👤 Hồ sơ", style=discord.ButtonStyle.secondary, row=1)
    async def btn_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_room(interaction)
        if room:
            embed = build_profile_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 Làm mới", style=discord.ButtonStyle.danger, row=2)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.get_room(interaction)
        if room:
            embed = build_base_embed(
                title=f"🏠 Bảng chức năng - Phòng {room['room_number']}",
                description="Bạn có thể tra cứu thông tin nhanh chóng bằng cách bấm các nút dưới đây."
            )
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send("🔄 Đã cập nhật số liệu mới nhất!", ephemeral=True)


class LinkRoomModal(discord.ui.Modal, title="Liên kết tài khoản Phòng trọ"):
    room_code = discord.ui.TextInput(
        label="Mã phòng (Ví dụ: P101)", 
        placeholder="Nhập mã phòng của bạn...", 
        min_length=2, 
        max_length=10
    )
    link_code = discord.ui.TextInput(
        label="Mã xác minh liên kết", 
        placeholder="Lấy mã 8 ký tự tại phần mềm Desktop...", 
        min_length=8, 
        max_length=8
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        username_disc = f"{interaction.user.name}#{interaction.user.discriminator}" if interaction.user.discriminator != "0" else interaction.user.name
        success, message, api_key = database.link_room_discord(
            room_code=self.room_code.value.upper().strip(),
            discord_user_id=interaction.user.id,
            discord_username=username_disc,
            link_code=self.link_code.value.strip(),
            guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            guild_name=interaction.guild.name if interaction.guild else None
        )
        
        if success:
            broadcast_link_room(interaction.client, api_key, self.room_code.value.upper().strip(), interaction.user.id, username_disc)
            embed = build_base_embed(
                title="✅ Liên kết Thành công",
                description=f"Tài khoản Discord **{interaction.user.name}** đã được liên kết thành công với phòng **{self.room_code.value.upper()}**.\n\n"
                            "Bây giờ bạn đã có thể nhận thông báo hóa đơn, xem chỉ số điện nước và gửi tin nhắn trực tiếp!",
                color=COLOR_SUCCESS
            )
        else:
            embed = build_base_embed(
                title="❌ Liên kết Thất bại",
                description=f"Không thể thực hiện liên kết:\n**{message}**",
                color=COLOR_DANGER
            )
            
        await interaction.followup.send(embed=embed, ephemeral=True)


class SupportMessageModal(discord.ui.Modal, title="Gửi tin nhắn liên hệ chủ trọ"):
    message_content = discord.ui.TextInput(
        label="Nội dung tin nhắn cần gửi",
        style=discord.TextStyle.paragraph,
        placeholder="Nhập nội dung bạn muốn gửi tới chủ nhà trọ...",
        min_length=1,
        max_length=500
    )
    
    def __init__(self, room: dict):
        super().__init__()
        self.room = room
        
    async def on_submit(self, interaction: discord.Interaction):
        content = self.message_content.value.strip()
        sender_username = database.get_room_username_by_discord_id(interaction.user.id) or f"phong_{self.room['room_number']}"
        api_key = self.room.get("api_key")
        
        success = database.save_message_from_tenant(
            api_key=api_key,
            sender_username=sender_username,
            receiver_username="admin",
            message_content=content,
            message_type="text",
            discord_message_id=f"gui_msg_{interaction.id}"
        )
        
        if success:
            broadcast_saved_message(interaction.client, sender_username, "admin", content, "text", f"gui_msg_{interaction.id}")
            embed = build_base_embed(
                title="✉️ Gửi Tin nhắn Thành công",
                description=f"Tin nhắn của bạn đã được gửi tới chủ trọ:\n\n"
                            f"> *{content}*\n\n"
                            f"Chủ trọ sẽ nhận được thông báo trên phần mềm và phản hồi sớm nhất qua tin nhắn riêng của Bot này.",
                color=COLOR_SUCCESS
            )
        else:
            embed = build_base_embed(
                title="❌ Gửi thất bại",
                description="Hệ thống đang bận. Vui lòng thử lại sau.",
                color=COLOR_DANGER
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class EphemeralLinkView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60.0)
        
    @discord.ui.button(label="🔗 Liên kết ngay", style=discord.ButtonStyle.primary)
    async def btn_link_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LinkRoomModal())


class PersistentControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    async def check_link(self, interaction: discord.Interaction) -> Optional[dict]:
        room = database.get_room_by_discord_id(interaction.user.id)
        if not room:
            embed = build_base_embed(
                title="❌ Tài khoản Chưa Liên Kết",
                description="Tài khoản Discord của bạn chưa được liên kết với bất kỳ phòng trọ nào.\n\n"
                            "Vui lòng nhấn nút **[🔗 Liên kết ngay]** phía dưới để liên kết nhanh.",
                color=COLOR_DANGER
            )
            view = EphemeralLinkView()
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return None
        return room

    @discord.ui.button(label="🔗 Liên kết", style=discord.ButtonStyle.primary, row=0, custom_id="panel_btn_link")
    async def btn_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = database.get_room_by_discord_id(interaction.user.id)
        if room:
            embed = build_base_embed(
                title="ℹ️ Đã liên kết",
                description=f"Tài khoản Discord của bạn đã được liên kết với **Phòng {room['room_number']}**.\nKhông cần liên kết lại.",
                color=COLOR_INFO
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_modal(LinkRoomModal())

    @discord.ui.button(label="📄 Hóa đơn", style=discord.ButtonStyle.secondary, row=1, custom_id="panel_btn_invoice")
    async def btn_invoice(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            embed = build_invoice_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💰 Thanh toán", style=discord.ButtonStyle.success, row=1, custom_id="panel_btn_payment")
    async def btn_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            embed = build_payment_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="⚡ Điện nước", style=discord.ButtonStyle.secondary, row=2, custom_id="panel_btn_utilities")
    async def btn_utilities(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            embed = build_utilities_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🏦 Chuyển khoản", style=discord.ButtonStyle.success, row=2, custom_id="panel_btn_bank")
    async def btn_bank(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            embed, _ = build_bank_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💬 Liên hệ chủ trọ", style=discord.ButtonStyle.primary, row=3, custom_id="panel_btn_support")
    async def btn_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            await interaction.response.send_modal(SupportMessageModal(room))

    @discord.ui.button(label="👤 Hồ sơ", style=discord.ButtonStyle.secondary, row=3, custom_id="panel_btn_profile")
    async def btn_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            embed = build_profile_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 Làm mới", style=discord.ButtonStyle.danger, row=4, custom_id="panel_btn_refresh")
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = await self.check_link(interaction)
        if room:
            await interaction.response.send_message("🔄 Đã cập nhật số liệu mới nhất của phòng!", ephemeral=True)


class BotCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_linked_room(self, interaction: discord.Interaction) -> Optional[dict]:
        room = database.get_room_by_discord_id(interaction.user.id)
        if not room:
            embed = build_base_embed(
                title="❌ Tài khoản Chưa Liên Kết",
                description="Tài khoản Discord này chưa được liên kết với bất kỳ phòng trọ nào.\n\n"
                            "Vui lòng liên kết tài khoản bằng lệnh:\n"
                            "`/link <mã_phòng> <mã_xác_minh>`\n"
                            "*Ví dụ: `/link P101 ABCD1234`*",
                color=COLOR_DANGER
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return None
        return room

    @app_commands.command(name="link", description="Liên kết tài khoản Discord với phòng trọ của bạn")
    @app_commands.describe(room_code="Mã phòng trọ của bạn (ví dụ: P101)", link_code="Mã liên kết xác minh (ví dụ: ABCD1234)")
    async def slash_link(self, interaction: discord.Interaction, room_code: str, link_code: str):
        await interaction.response.defer(ephemeral=True)
        username_disc = f"{interaction.user.name}#{interaction.user.discriminator}" if interaction.user.discriminator != "0" else interaction.user.name
        success, message, api_key = database.link_room_discord(
            room_code=room_code.upper().strip(),
            discord_user_id=interaction.user.id,
            discord_username=username_disc,
            link_code=link_code.strip(),
            guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            guild_name=interaction.guild.name if interaction.guild else None
        )
        if success:
            broadcast_link_room(self.bot, api_key, room_code.upper().strip(), interaction.user.id, username_disc)
            embed = build_base_embed(
                title="✅ Liên kết Thành công",
                description=f"Tài khoản Discord **{interaction.user.name}** đã được liên kết thành công với phòng **{room_code.upper()}**.\n\n"
                            "Bây giờ bạn đã có thể nhận thông báo hóa đơn, xem chỉ số điện nước và gửi tin nhắn trực tiếp!",
                color=COLOR_SUCCESS
            )
        else:
            embed = build_base_embed(
                title="❌ Liên kết Thất bại",
                description=f"Không thể thực hiện liên kết:\n**{message}**",
                color=COLOR_DANGER
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="invoice", description="Tra cứu chi tiết hóa đơn dịch vụ tháng mới nhất")
    async def slash_invoice(self, interaction: discord.Interaction):
        room = await self.get_linked_room(interaction)
        if room:
            embed = build_invoice_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="payment", description="Kiểm tra trạng thái nợ phí và thời hạn thanh toán")
    async def slash_payment(self, interaction: discord.Interaction):
        room = await self.get_linked_room(interaction)
        if room:
            embed = build_payment_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bank", description="Nhận thông tin tài khoản chuyển khoản ngân hàng và mã QR")
    async def slash_bank(self, interaction: discord.Interaction):
        room = await self.get_linked_room(interaction)
        if room:
            embed, _ = build_bank_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="support", description="Gửi tin nhắn liên hệ/hỗ trợ trực tiếp cho chủ nhà trọ")
    @app_commands.describe(content="Nội dung bạn muốn nhắn gửi cho chủ trọ")
    async def slash_support(self, interaction: discord.Interaction, content: str):
        room = await self.get_linked_room(interaction)
        if not room:
            return
        sender_username = database.get_room_username_by_discord_id(interaction.user.id) or f"phong_{room['room_number']}"
        success = database.save_message_from_tenant(
            sender_username=sender_username,
            receiver_username="admin",
            message_content=content,
            message_type="text",
            discord_message_id=f"slash_sup_{interaction.id}"
        )
        if success:
            broadcast_saved_message(self.bot, sender_username, "admin", content, "text", f"slash_sup_{interaction.id}")
            embed = build_base_embed(
                title="✉️ Gửi Tin nhắn Thành công",
                description=f"Tin nhắn hỗ trợ của bạn đã được gửi trực tiếp đến phần mềm của chủ trọ:\n\n"
                            f"> *{content}*\n\n"
                            f"Chủ trọ sẽ phản hồi bạn sớm nhất có thể qua tin nhắn riêng của Bot này.",
                color=COLOR_SUCCESS
            )
        else:
            embed = build_base_embed(
                title="❌ Lỗi Hệ thống",
                description="Không thể lưu gửi tin nhắn vào lúc này.",
                color=COLOR_DANGER
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="profile", description="Xem hồ sơ thông tin cá nhân và hợp đồng thuê")
    async def slash_profile(self, interaction: discord.Interaction):
        room = await self.get_linked_room(interaction)
        if room:
            embed = build_profile_embed(room)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="Hiển thị danh sách các lệnh hỗ trợ của Bot")
    async def slash_help(self, interaction: discord.Interaction):
        desc = (
            "Chào mừng bạn đến với Cổng Hỗ trợ **GIA HUY HOME**!\n\n"
            "Dưới đây là danh sách các lệnh Slash Command khả dụng:\n"
            "• `/link <mã_phòng> <mã_xác_minh>`: Liên kết Discord với phòng thuê.\n"
            "• `/menu`: Hiển thị bảng điều khiển nút bấm đa năng.\n"
            "• `/invoice`: Xem chi tiết tiền phòng và dịch vụ tháng mới nhất.\n"
            "• `/payment`: Kiểm tra trạng thái nợ phí và hạn thanh toán.\n"
            "• `/bank`: Lấy tài khoản ngân hàng và mã QR chuyển khoản VietQR.\n"
            "• `/support <nội dung>`: Gửi tin nhắn chat trực tiếp cho chủ nhà.\n"
            "• `/profile`: Tra cứu hồ sơ thông tin và thời hạn hợp đồng thuê.\n"
            "• `/help`: Hiển thị danh sách lệnh hỗ trợ.\n\n"
            "💡 *Mách nhỏ: Bạn cũng có thể nhắn tin riêng (DM) trực tiếp cho Bot này để chat với chủ trọ.*"
        )
        embed = build_base_embed(title="❓ Danh sách lệnh hỗ trợ Bot", description=desc, color=COLOR_INFO)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="menu", description="Hiển thị bảng nút chức năng tương tác nhanh")
    async def slash_menu(self, interaction: discord.Interaction):
        room = database.get_room_by_discord_id(interaction.user.id)
        if not room:
            view = EphemeralLinkView()
            embed = build_base_embed(
                title="❌ Tài khoản Chưa Liên Kết",
                description="Tài khoản Discord của bạn chưa được liên kết với bất kỳ phòng trọ nào.\n\n"
                            "Vui lòng nhấn nút **[🔗 Liên kết ngay]** phía dưới để liên kết nhanh.",
                color=COLOR_DANGER
            )
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return
            
        desc = f"Chào mừng khách thuê **Phòng {room['room_number']}**!\nBấm vào các nút tương ứng bên dưới để thực hiện tra cứu thông tin dịch vụ."
        embed = build_base_embed(title=f"🏠 Bảng chức năng - Phòng {room['room_number']}", description=desc, color=COLOR_PRIMARY)
        view = MenuView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class BotEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info(f"Bot logged in as {self.bot.user} (ID: {self.bot.user.id})")
        activity = discord.Activity(type=discord.ActivityType.watching, name="GIA HUY HOME")
        await self.bot.change_presence(activity=activity)
        
        try:
            synced = await self.bot.tree.sync()
            logger.info(f"Successfully synced {len(synced)} slash commands.")
        except Exception as e:
            logger.error(f"Error syncing slash commands: {e}")
            
        self.bot.loop.create_task(self.check_and_deploy_control_panel())

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        logger.info(f"Bot joined a new guild: {guild.name} (ID: {guild.id})")
        # Deploy control panel to this new guild
        desc = """Chào mừng bạn đến với **GIA HUY HOME**!

Created by Dev Gia Huy.

Đây là Bảng điều khiển quản lý khách thuê cố định. Bạn có thể dễ dàng tra cứu mọi thông tin phòng bằng các nút bấm bên dưới.

🔒 **Bước 1**: Nhấn nút **`🔗 Liên kết`** để xác minh phòng của bạn.
🔑 **Bước 2**: Nhập **Mã phòng** và **Mã xác minh** (lấy tại phần mềm Desktop).
🎯 **Bước 3**: Trải nghiệm các tính năng tự động dưới đây!

• `📄 Hóa đơn`: Tra cứu hóa đơn dịch vụ tháng mới nhất.
• `💰 Thanh toán`: Kiểm tra trạng thái nợ phí và thời hạn.
• `⚡ Điện nước`: Xem chỉ số điện nước tiêu thụ.
• `🏦 Chuyển khoản`: Nhận thông tin tài khoản và mã QR VietQR.
• `💬 Liên hệ chủ trọ`: Gửi tin nhắn trực tiếp đến Desktop.
• `👤 Hồ sơ`: Xem hợp đồng thuê và thông tin cá nhân.
• `🔄 Làm mới`: Cập nhật lại trạng thái mới nhất."""
        embed = build_base_embed(
            title="🏠 GIA HUY HOME - BẢNG ĐIỀU KHIỂN KHÁCH THUÊ",
            description=desc,
            color=discord.Color.from_rgb(88, 101, 242)
        )
        view = PersistentControlPanelView()
        
        channel = discord.utils.get(guild.text_channels, name="nha-tro-bot")
        if not channel:
            try:
                channel = await guild.create_text_channel(
                    "nha-tro-bot",
                    topic="Bảng điều khiển quản lý nhà trọ Gia Huy Home - Tra cứu hóa đơn, điện nước, thông tin cá nhân."
                )
                logger.info(f"Created channel #nha-tro-bot in guild {guild.name}")
            except Exception as e:
                logger.error(f"Failed to create channel #nha-tro-bot in new guild: {e}")
                return

        try:
            await channel.purge(limit=20, check=lambda m: m.author.id == self.bot.user.id)
            await channel.send(embed=embed, view=view)
            logger.info(f"Deployed Control Panel to #{channel.name} in newly joined guild {guild.name}")
        except Exception as e:
            logger.error(f"Failed to deploy panel in channel of newly joined guild: {e}")

    async def check_and_deploy_control_panel(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)
        
        desc = """Chào mừng bạn đến với **GIA HUY HOME**!

Created by Dev Gia Huy.

Đây là Bảng điều khiển quản lý khách thuê cố định. Bạn có thể dễ dàng tra cứu mọi thông tin phòng bằng các nút bấm bên dưới.

🔒 **Bước 1**: Nhấn nút **`🔗 Liên kết`** để xác minh phòng của bạn.
🔑 **Bước 2**: Nhập **Mã phòng** và **Mã xác minh** (lấy tại phần mềm Desktop).
🎯 **Bước 3**: Trải nghiệm các tính năng tự động dưới đây!

• `📄 Hóa đơn`: Tra cứu hóa đơn dịch vụ tháng mới nhất.
• `💰 Thanh toán`: Kiểm tra trạng thái nợ phí và thời hạn.
• `⚡ Điện nước`: Xem chỉ số điện nước tiêu thụ.
• `🏦 Chuyển khoản`: Nhận thông tin tài khoản và mã QR VietQR.
• `💬 Liên hệ chủ trọ`: Gửi tin nhắn trực tiếp đến Desktop.
• `👤 Hồ sơ`: Xem hợp đồng thuê và thông tin cá nhân.
• `🔄 Làm mới`: Cập nhật lại trạng thái mới nhất."""
        embed = build_base_embed(
            title="🏠 GIA HUY HOME - BẢNG ĐIỀU KHIỂN KHÁCH THUÊ",
            description=desc,
            color=discord.Color.from_rgb(88, 101, 242)
        )
        view = PersistentControlPanelView()
        
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="nha-tro-bot")
            if not channel:
                try:
                    channel = await guild.create_text_channel(
                        "nha-tro-bot",
                        topic="Bảng điều khiển quản lý nhà trọ Gia Huy Home - Tra cứu hóa đơn, điện nước, thông tin cá nhân."
                    )
                    logger.info(f"Created channel #nha-tro-bot in guild {guild.name}")
                except Exception as e:
                    logger.error(f"Failed to create channel #nha-tro-bot: {e}")
                    continue
            
            try:
                await channel.purge(limit=20, check=lambda m: m.author.id == self.bot.user.id)
                await channel.send(embed=embed, view=view)
                logger.info(f"Deployed Control Panel to #{channel.name} in {guild.name}")
            except Exception as e:
                logger.error(f"Failed to deploy panel in channel: {e}")
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            logger.info(f"Received DM from {message.author} (ID: {message.author.id}): {message.content}")
            
            room = database.get_room_by_discord_id(message.author.id)
            if not room:
                embed = build_base_embed(
                    title="⚠️ Tài khoản Chưa Liên Kết",
                    description="Tài khoản Discord này chưa được liên kết với bất kỳ phòng trọ nào.\n\n"
                                "Vui lòng liên kết tài khoản bằng cách gõ lệnh sau trong máy chủ:\n"
                                "`/link <mã_phòng> <mã_xác_minh>`\n"
                                "*Ví dụ: `/link P101 ABCD1234`*",
                    color=COLOR_DANGER
                )
                await message.channel.send(embed=embed)
                return

            sender_username = database.get_room_username_by_discord_id(message.author.id) or f"phong_{room['room_number']}"
            api_key = room.get("api_key")
            
            saved_messages = []
            error_occurred = False
            
            # Save text message
            if message.content.strip():
                success = database.save_message_from_tenant(
                    api_key=api_key,
                    sender_username=sender_username,
                    receiver_username="admin",
                    message_content=message.content,
                    message_type="text",
                    discord_message_id=str(message.id)
                )
                if success:
                    saved_messages.append({"content": message.content, "type": "text"})
                    broadcast_saved_message(self.bot, sender_username, "admin", message.content, "text", str(message.id))
                else:
                    error_occurred = True

            # Save attachments
            if message.attachments:
                attachments_dir = os.environ.get("UPLOAD_DIR", "uploads")
                os.makedirs(attachments_dir, exist_ok=True)
                
                for attachment in message.attachments:
                    MAX_SIZE = 15 * 1024 * 1024
                    if attachment.size > MAX_SIZE:
                        error_occurred = True
                        try:
                            await message.channel.send(f"❌ Tệp đính kèm '{attachment.filename}' vượt quá kích thước giới hạn (Tối đa 15MB).")
                        except Exception:
                            pass
                        continue
                        
                    filename = attachment.filename
                    ext = os.path.splitext(filename)[1].lower()
                    dangerous_extensions = ['.exe', '.bat', '.vbs', '.msi', '.lnk', '.py', '.sh', '.cmd', '.reg', '.js', '.scr', '.jar']
                    safe_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar', '.7z']
                    
                    if ext in dangerous_extensions or (ext and ext not in safe_extensions):
                        error_occurred = True
                        try:
                            await message.channel.send(f"❌ Loại tệp '{ext}' bị chặn vì lý do bảo mật hệ thống.")
                        except Exception:
                            pass
                        continue

                    # Sanitize filename
                    clean_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
                    timestamp = int(time.time())
                    dest_filename = f"{timestamp}_{clean_filename}"
                    rel_path = os.path.join(attachments_dir, dest_filename)
                    
                    try:
                        await attachment.save(rel_path)
                        logger.info(f"Saved Discord attachment to: {rel_path}")
                        
                        content_type = (attachment.content_type or "").lower()
                        is_image = content_type.startswith("image/") or filename.lower().endswith(
                            (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
                        )
                        m_type = "image" if is_image else "file"
                        
                        # Store file relative path/URL
                        success = database.save_message_from_tenant(
                            api_key=api_key,
                            sender_username=sender_username,
                            receiver_username="admin",
                            message_content=rel_path,
                            message_type=m_type,
                            discord_message_id=f"{message.id}_att_{attachment.id}"
                        )
                        if success:
                            saved_messages.append({"content": rel_path, "type": m_type})
                            broadcast_saved_message(self.bot, sender_username, "admin", rel_path, m_type, f"{message.id}_att_{attachment.id}")
                        else:
                            error_occurred = True
                    except Exception as e:
                        logger.error(f"Error saving attachment {filename}: {e}")
                        error_occurred = True

            if saved_messages:
                try:
                    await message.add_reaction("✔️")
                except Exception:
                    pass
            
            if error_occurred:
                try:
                    await message.channel.send("❌ Đã xảy ra lỗi khi chuyển tiếp tin nhắn đến chủ trọ.")
                except Exception:
                    pass

        await self.bot.process_commands(message)


class DiscordBotClient(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guilds = True
        intents.members = True
        intents.presences = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        
    async def setup_hook(self):
        logger.info("Loading extensions...")
        await self.add_cog(BotEvents(self))
        await self.add_cog(BotCommands(self))
        self.add_view(PersistentControlPanelView())
        logger.info("Persistent view and cogs registered.")

def create_bot() -> DiscordBotClient:
    return DiscordBotClient()
