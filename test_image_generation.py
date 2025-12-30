#!/usr/bin/env python3
"""
Test script for image generation and card image fetching.
Fetches top decks, generates all images, and saves them to /test_images/ folder.
Does NOT run the Telegram bot or post to Facebook.

Usage:
    python test_image_generation.py
"""

import os
import logging
from pathlib import Path

from get_decks import get_top_10_decks
from image_creation import _generate_front_page, _generate_deck_grid_image, _generate_back_cover, _generate_listing_pages

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_image_generation():
    """Test image generation by fetching decks and saving images locally."""
    
    # Create test_images directory
    test_dir = Path("test_images")
    test_dir.mkdir(exist_ok=True)
    logger.info(f"Saving test images to {test_dir.resolve()}")
    
    # Fetch top decks
    logger.info("Fetching top decks...")
    try:
        result = get_top_10_decks()
        decks = result.get("decks", [])
        set_info = result.get("set", {})
        if not decks:
            logger.error("No decks returned from get_top_10_decks()")
            return False
        logger.info(f"Fetched {len(decks)} decks")
    except Exception as e:
        logger.error(f"Error fetching decks: {e}")
        return False
    
    # Front page generation removed (no front page will be created)
    
    # Generate listing pages
    logger.info("Generating listing pages...")
    try:
        listing_pages = _generate_listing_pages(decks, set_info, per_page=5)
        for idx, page_bytes in enumerate(listing_pages, start=1):
            if page_bytes:
                listing_path = test_dir / f"01_listing_page_{idx}.jpg"
                with open(listing_path, "wb") as f:
                    f.write(page_bytes)
                logger.info(f"✅ Saved listing page {idx} to {listing_path}")
            else:
                logger.warning(f"Listing page {idx} generation returned None")
    except Exception as e:
        logger.error(f"Error generating listing pages: {e}")
    
    
    # Generate deck images
    logger.info("Generating deck images...")
    failed_decks = []
    for idx, deck in enumerate(decks, start=1):
        try:
            logger.info(f"Processing deck {idx}/{len(decks)}: {deck.get('name')}")
            # Generate only the grid image (title+stats drawn inside)
            cards = deck.get('cards', []) or []
            set_code_val = set_info.get("id") if isinstance(set_info, dict) else ""
            grid_bytes = _generate_deck_grid_image(cards, idx, deck.get('name',''), set_code_val, deck.get('win_pct'), deck.get('share'))
            grid_path = test_dir / f"{idx:02d}_deck_{idx}_grid.jpg"
            with open(grid_path, "wb") as f:
                f.write(grid_bytes)
            logger.info(f"  ✅ Saved grid image to {grid_path}")
            
        except Exception as e:
            logger.error(f"Error generating deck {idx} images: {e}")
            failed_decks.append((idx, deck.get('name')))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("IMAGE GENERATION TEST COMPLETE")
    logger.info("="*60)
    logger.info(f"Successfully generated images for {len(decks) - len(failed_decks)}/{len(decks)} decks")
    if failed_decks:
        logger.warning(f"Failed decks:")
        for idx, name in failed_decks:
            logger.warning(f"  - Deck {idx}: {name}")
    
    logger.info(f"\nAll images saved to: {test_dir.resolve()}")
    logger.info("You can now review the images and check for missing card images.")
    
    # Generate back cover
    logger.info("Generating back cover image...")
    try:
        back_bytes = _generate_back_cover(set_info)
        if back_bytes:
            back_path = test_dir / "99_back_cover.jpg"
            with open(back_path, "wb") as f:
                f.write(back_bytes)
            logger.info(f"✅ Saved back cover to {back_path}")
    except Exception as e:
        logger.error(f"Error generating back cover: {e}")

    return len(failed_decks) == 0


if __name__ == "__main__":
    success = test_image_generation()
    exit(0 if success else 1)
