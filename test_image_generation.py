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
from image_creation import _generate_front_page, _generate_images_for_deck, _generate_back_cover

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
    
    # Generate front page image
    logger.info("Generating front page image...")
    try:
        front_page_bytes = _generate_front_page(set_info)
        if front_page_bytes:
            front_path = test_dir / "00_front_page.jpg"
            with open(front_path, "wb") as f:
                f.write(front_page_bytes)
            logger.info(f"✅ Saved front page to {front_path}")
        else:
            logger.warning("Front page generation returned None")
    except Exception as e:
        logger.error(f"Error generating front page: {e}")
    
    # Generate deck images
    logger.info("Generating deck images...")
    failed_decks = []
    for idx, deck in enumerate(decks, start=1):
        try:
            logger.info(f"Processing deck {idx}/{len(decks)}: {deck.get('name')}")
            title_bytes, grid_bytes = _generate_images_for_deck(
                deck,
                position=idx,
                set_code=set_info.get("id") if isinstance(set_info, dict) else ""
            )
            
            # Save title/stats image
            title_path = test_dir / f"{idx:02d}_deck_{idx}_title.jpg"
            with open(title_path, "wb") as f:
                f.write(title_bytes)
            logger.info(f"  ✅ Saved title image to {title_path}")
            
            # Save grid/cards image
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
