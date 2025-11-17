import os
import logging
import io
import asyncio
from typing import Tuple, Optional
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from PIL import Image, ImageDraw, ImageFont
import requests
from datetime import datetime

from get_decks import get_top_10_decks
from image_creation import (
    _load_font,
    _get_text_size,
    _normalize_card_code,
    _fetch_card_image,
    _background_for_set,
    _hex_to_rgb,
    _create_diagonal_gradient,
    _compute_primary_color_from_image_url,
    _generate_front_page,
    _select_representative_cards,
    _generate_images_for_deck,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Simple mapping of some example set codes -> primary color (RGB). If unknown, a default gradient is used.
SET_COLORS = {
    "A4": (30, 144, 255),    # example mapping for set A4
    "B1": (255, 165, 0),     # example
    "C2": (34, 139, 34),     # example
}

DEFAULT_BG = (24, 24, 30)

# runtime chosen primary color for the current set (RGB tuple)
CURRENT_SET_COLOR: Optional[Tuple[int, int, int]] = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola! Soy tu bot. Escribe /help para ver comandos.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start - iniciar\n/help - ayuda\n/inline - ejemplo de botones")

async def inline_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Botón A", callback_data='A'),
         InlineKeyboardButton("Botón B", callback_data='B')]
    ]
    await update.message.reply_text("Elige:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(text=f"Seleccionaste: {q.data}")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Recibí: {update.message.text}")


async def get_decks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler: fetch decks locally, generate images for first 5 decks and send them to chat."""
    await update.message.reply_text("Getting Decks Data...")
    try:
        # run blocking network function in a thread
        data = await asyncio.to_thread(get_top_10_decks)
    except Exception as e:
        logger.exception("Error fetching decks")
        await update.message.reply_text(f"Error Getting Deck Data: {e}")
        return

    set_info = data.get("set", {}) or {}
    decks = data.get("decks", [])[:5] # limit to first deck for testing

    # Compute set primary color from logo (if available) and set runtime color
    global CURRENT_SET_COLOR
    CURRENT_SET_COLOR = None
    logo_url = None
    if isinstance(set_info, dict):
        logo_url = set_info.get("logo") or set_info.get("symbol") or set_info.get("image")
    if logo_url:
        try:
            color = await asyncio.to_thread(_compute_primary_color_from_image_url, logo_url)
            if color:
                CURRENT_SET_COLOR = color
        except Exception:
            CURRENT_SET_COLOR = None

    # Generate front page bytes (but don't send yet) so we can batch all images
    front = None
    try:
        front = await asyncio.to_thread(_generate_front_page, set_info)
    except Exception:
        logger.exception("Failed to generate front page")

    if not decks:
        await update.message.reply_text("No decks found.")
        return

    # await update.message.reply_text(f"Creating images for the first {len(decks)} decks...")

    # generate all images first
    media_items = []  # list of tuples (bytes, optional caption)
    if front:
        media_items.append((front, f"Top decks — set: {set_info.get('name') if isinstance(set_info, dict) else set_info}"))

    for idx, deck in enumerate(decks, start=1):
        try:
            set_code_value = set_info.get('id') if isinstance(set_info, dict) else set_info
            img1_bytes, img2_bytes = await asyncio.to_thread(_generate_images_for_deck, deck, idx, set_code_value)
            caption = f"#{idx} {deck.get('name','')} — Win: {deck.get('win_pct',0)}% • Share: {deck.get('share',0)}%"
            media_items.append((img1_bytes, caption))
            media_items.append((img2_bytes, None))
        except Exception as e:
            logger.exception("Error generating images for deck %s", deck.get('name'))
            # append a placeholder image with error text
            try:
                err_img = Image.new('RGB', (800, 450), (30, 30, 30))
                ed = ImageDraw.Draw(err_img)
                emsg = f"Error creating images for {deck.get('name','') }"
                ef = _load_font(24)
                ew, eh = _get_text_size(ed, emsg, ef)
                ed.text(((800-ew)//2, (450-eh)//2), emsg, font=ef, fill=(255,255,255))
                buf_err = io.BytesIO()
                err_img.save(buf_err, format='JPEG', quality=85)
                buf_err.seek(0)
                media_items.append((buf_err.getvalue(), f"Error: {deck.get('name','') }"))
            except Exception:
                continue

    # Now send media items in batches of up to 10 (Telegram media group limit)
    if not media_items:
        await update.message.reply_text("No images to send.")
        return

    try:
        chat_id = update.effective_chat.id
        batch_size = 10
        for i in range(0, len(media_items), batch_size):
            batch = media_items[i:i+batch_size]
            medias = []
            for j, (bbytes, cap) in enumerate(batch):
                bio = io.BytesIO(bbytes) if not isinstance(bbytes, io.BytesIO) else bbytes
                # ensure we have a file-like object with a name attribute
                if isinstance(bio, io.BytesIO):
                    bio.name = getattr(bio, 'name', f'photo_{i+j}.jpg')
                    bio.seek(0)
                if j == 0 and cap:
                    medias.append(InputMediaPhoto(media=bio, caption=cap))
                else:
                    medias.append(InputMediaPhoto(media=bio))

            # send the batch
            await context.bot.send_media_group(chat_id=chat_id, media=medias)
    except Exception:
        logger.exception("Failed to send media groups")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("inline", inline_example))
    app.add_handler(CommandHandler("decks", get_decks))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))

    logger.info("Bot running (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
