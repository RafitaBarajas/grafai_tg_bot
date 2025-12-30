import os
import logging
import io
import asyncio
from typing import Tuple, Optional
import re

from dotenv import load_dotenv

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
    _select_representative_cards,
    _generate_images_for_deck,
    _generate_deck_grid_image,
    _generate_back_cover,
    _generate_listing_pages,
)
from facebook_posting import post_to_facebook, generate_caption

load_dotenv()

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


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /schedule <hours>: schedules the get_decks run after given hours."""
    try:
        # Expect one argument: number of hours
        args = context.args or []
        if not args:
            await update.message.reply_text("Usage: /schedule <hours>")
            return
        try:
            hours = float(args[0])
        except Exception:
            await update.message.reply_text("Please provide a numeric value for hours.")
            return
        if hours <= 0:
            await update.message.reply_text("Please provide a positive number of hours.")
            return

        seconds = int(hours * 3600)
        chat_id = update.effective_chat.id

        # schedule job using JobQueue
        # data will carry chat_id so the job knows where to post
        context.job_queue.run_once(_scheduled_get_decks, when=seconds, data={"chat_id": chat_id})

        await update.message.reply_text(f"Scheduled get_decks to run in {hours} hour(s).")
    except Exception:
        logger.exception("Failed to schedule get_decks")
        await update.message.reply_text("Failed to schedule the job.")


async def get_decks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler: fetch decks locally, generate images for first 5 decks and send them to chat.
    Optional argument: /decks false to skip Facebook posting.
    """
    await update.message.reply_text("Getting Decks Data...")
    # Check for optional flag to disable Facebook posting
    post_to_fb = True
    args = context.args or []
    if args and args[0].lower() == 'false':
        post_to_fb = False
    # delegate the heavy lifting to the reusable function using the chat id
    try:
        await do_get_decks(update.effective_chat.id, context, post_to_facebook=post_to_fb)
    except Exception:
        logger.exception("Scheduled get_decks failed when invoked interactively")
        await update.message.reply_text("An error occurred while generating decks.")


async def do_get_decks(chat_id: int, context: ContextTypes.DEFAULT_TYPE, post_to_facebook: bool = True):
    """Perform the get_decks workflow for a specific chat id. This is reused by the
    interactive handler and by scheduled jobs.
    Args:
        chat_id: The Telegram chat ID to send images to.
        context: The Telegram context.
        post_to_facebook: Whether to post images to Facebook (default True).
    """
    try:
        data = await asyncio.to_thread(get_top_10_decks)
    except Exception as e:
        logger.exception("Error fetching decks")
        await context.bot.send_message(chat_id=chat_id, text=f"Error Getting Deck Data: {e}")
        return

    set_info = data.get("set", {}) or {}
    decks = data.get("decks", [])[:5]

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

    # Front page generation removed per configuration — listings and per-deck grids only

    listing_pages = []
    try:
        listing_pages = await asyncio.to_thread(_generate_listing_pages, decks, set_info, 5)
    except Exception:
        logger.exception("Failed to generate listing pages")

    if not decks:
        await context.bot.send_message(chat_id=chat_id, text="No decks found.")
        return

    media_items = []  # list of tuples (bytes, optional caption)
    # front page intentionally omitted
    # append listing pages (each shows up to 5 decks with rank + 2 representative cards)
    for idx_lp, lp in enumerate(listing_pages, start=1):
        media_items.append((lp, f"Top decks — set: {set_info.get('name') if isinstance(set_info, dict) else set_info} (page {idx_lp})"))

    for idx, deck in enumerate(decks, start=1):
        try:
            set_code_value = set_info.get('id') if isinstance(set_info, dict) else set_info
            # generate only the grid image (title + stats + grid)
            cards = deck.get('cards', []) or []
            name_cap = deck.get('name', '')
            grid_bytes = await asyncio.to_thread(_generate_deck_grid_image, cards, idx, name_cap, set_code_value, deck.get('win_pct'), deck.get('share'))
            # append only the grid image (title/stats are drawn inside the image)
            media_items.append((grid_bytes, None))
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

    # Add back cover image as the last image
    try:
        back = await asyncio.to_thread(_generate_back_cover, set_info)
        if back:
            media_items.append((back, None))
    except Exception:
        logger.exception("Failed to generate back cover")

    # Now send media items in batches of up to 10 (Telegram media group limit)
    if not media_items:
        await context.bot.send_message(chat_id=chat_id, text="No images to send.")
        return

    try:
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

    # Generate and send caption (phrase + hashtags) to Telegram and optionally Facebook
    try:
        deck_names = [deck.get('name', '') for deck in decks]
        caption, phrase, hashtags_str = await asyncio.to_thread(generate_caption, deck_names)

        # Send caption to Telegram
        await context.bot.send_message(chat_id=chat_id, text=f"{phrase}\n\n{hashtags_str}")

        # Post to Facebook only if enabled
        if post_to_facebook:
            image_bytes_for_fb = [item[0] for item in media_items]  # Extract bytes from media_items
            await asyncio.to_thread(post_to_facebook, deck_names, image_bytes_for_fb)
        else:
            logger.info("Facebook posting skipped as per user request")
    except Exception:
        logger.exception("Failed to send caption or post to Facebook")


async def _scheduled_get_decks(context: ContextTypes.DEFAULT_TYPE):
    """Job callback to run get_decks for a scheduled chat."""
    try:
        job = context.job
        data = job.data if hasattr(job, 'data') else None
        chat_id = None
        post_to_fb = True
        if isinstance(data, dict):
            chat_id = data.get('chat_id')
            post_to_fb = data.get('post_to_facebook', True)
        if not chat_id:
            logger.error("Scheduled job missing chat_id")
            return
        await context.bot.send_message(chat_id=chat_id, text="Scheduled decks run starting now...")
        await do_get_decks(chat_id, context, post_to_facebook=post_to_fb)
    except Exception:
        logger.exception("Error running scheduled get_decks job")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("inline", inline_example))
    app.add_handler(CommandHandler("decks", get_decks))
    app.add_handler(CommandHandler("schedule", schedule))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))

    logger.info("Bot running (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
