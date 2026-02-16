import os
import logging
import random
import re
import io
import json
from typing import List, Optional

try:
    import facebook
except ImportError:
    facebook = None

logger = logging.getLogger(__name__)

PHRASES = [
    "Climbing the ladder? These decks are carrying hard right now 👀",
    "The meta doesn't lie, these Pokémon Pocket decks are winning.",
    "If you're tired of losing, start here.",
    "Top-tier decks you can build right now.",
    "These decks are everywhere… and for good reason.",
    "Best-performing decks in Pokémon TCG Pocket",
    "Tested, refined, and ladder-approved decks",
    "Easy-to-play, hard-to-beat decks",
    "Which deck are you playing this season?",
    "What deck is the hardest to beat?",
    "Comment your main deck if it's not here",
    "Agree or disagree with this tier list?",
    "Decks you can't stop playing against, because they are winning!",
]

BASE_HASHTAGS = ["#PokemonTCG", "#PokemonTCGPocket"]


def _extract_pokemon_names(deck_names: List[str], limit: int = 3) -> List[str]:
    """
    Extract Pokémon names from deck titles (first 3 decks).
    Assumes deck names may contain Pokémon names as separate words.
    Returns list of Pokémon names.
    """
    pokemon_names = []
    for deck_name in deck_names[:limit]:
        # Split by non-alphanumeric and take the first significant word(s)
        # Most deck names start with the main Pokémon name
        words = re.split(r'[^a-zA-Z0-9]+', deck_name.strip())
        # Filter out empty strings and try to get the first Pokémon-like word
        words = [w for w in words if w and len(w) > 2]
        if words:
            # The first word is usually the main Pokémon
            pokemon_names.append(words[0])
    return pokemon_names


def _pokemon_to_hashtag(pokemon_name: str) -> str:
    """Convert Pokémon name to hashtag format."""
    # Remove spaces and special chars, make it one word
    hashtag = re.sub(r'[^a-zA-Z0-9]', '', pokemon_name)
    return f"#{hashtag}"


def generate_caption(deck_names: List[str]) -> tuple:
    """
    Generate caption with random phrase and hashtags.
    Returns (caption_text, phrase, hashtags_string)
    """
    phrase = random.choice(PHRASES)
    
    # Extract Pokémon names from first 3 decks
    pokemon_names = _extract_pokemon_names(deck_names, limit=3)
    pokemon_hashtags = [_pokemon_to_hashtag(name) for name in pokemon_names]
    
    # Combine all hashtags
    all_hashtags = BASE_HASHTAGS + pokemon_hashtags
    hashtags_str = " ".join(all_hashtags)
    
    caption = f"{phrase}\n\n{hashtags_str}"
    return caption, phrase, hashtags_str


def _get_page_access_token(page_id: str, user_or_page_token: str) -> Optional[str]:
    """Try to obtain a Page Access Token for `page_id` using a provided user or page token.
    If the provided token is already a Page token for the page, returns it. If it's a user token
    with manage_pages/accounts permission, returns the page token. Otherwise returns None.
    """
    if not user_or_page_token:
        return None
    try:
        g = facebook.GraphAPI(user_or_page_token)
        # Try to list pages the token can manage
        accounts = g.get_connections('me', 'accounts')
        for p in accounts.get('data', []) if isinstance(accounts, dict) else []:
            if str(p.get('id')) == str(page_id) and p.get('access_token'):
                return p.get('access_token')
    except Exception:
        # If token is already a page token, we may not be able to call me/accounts; ignore
        return None
    return None


def post_to_facebook(
    deck_names: List[str],
    image_bytes_list: List[bytes],
    facebook_page_id: Optional[str] = None,
    facebook_access_token: Optional[str] = None,
    caption_override: Optional[str] = None,
) -> bool:
    """
    Post images to Facebook page with caption, phrase, and hashtags.
    
    Args:
        deck_names: List of deck names (first 3 used for hashtags)
        image_bytes_list: List of image bytes to post
        facebook_page_id: Facebook page ID (defaults to env var FACEBOOK_PAGE_ID)
        facebook_access_token: Facebook page access token (defaults to env var FACEBOOK_PAGE_ACCESS_TOKEN)
        caption_override: Optional complete caption text to use as-is
    
    Returns:
        True if posting succeeded, False otherwise.
    """
    if facebook is None:
        logger.warning("facebook-sdk not installed. Skipping Facebook posting.")
        return False

    page_id = facebook_page_id or os.getenv("FACEBOOK_PAGE_ID")
    access_token = facebook_access_token or os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")

    print('Facebook Page ID:', page_id)
    print('Facebook Access Token:', access_token)
    
    if not page_id or not access_token:
        logger.warning("Facebook page ID or access token not configured. Skipping posting.")
        return False
    
    try:
        if caption_override:
            caption = caption_override
        else:
            caption, _, _ = generate_caption(deck_names)

        # If a user access token was provided, try to obtain a Page access token for the target page
        page_token = _get_page_access_token(page_id, access_token)
        if page_token:
            logger.info("Resolved Page Access Token from user token; using Page token for posting.")
            access_token = page_token
        else:
            logger.info("Could not resolve a Page Access Token automatically. Ensure the access token is a Page access token.")

        # Create graph API instance (should be a Page token)
        graph = facebook.GraphAPI(access_token)
        
        # Post images as a single Facebook post by uploading each photo
        # unpublished (published=false) and then creating a single /{page_id}/feed
        # entry with attached_media referring to each uploaded photo.
        if not image_bytes_list:
            logger.warning("No images to post to Facebook.")
            return False

        try:
            media_fbs = []
            for idx, img_bytes in enumerate(image_bytes_list, start=1):
                img_io = io.BytesIO(img_bytes)
                img_io.name = f"image_{idx}.jpg"
                img_io.seek(0)

                # Upload the photo as unpublished so it doesn't create its own post
                logger.info(f"Uploading image {idx} as unpublished photo...")
                try:
                    resp = graph.put_photo(image=img_io, album_path=f"{page_id}/photos", published=False)
                except TypeError:
                    # Some facebook-sdk versions accept published as a string
                    resp = graph.put_photo(image=img_io, album_path=f"{page_id}/photos", published='false')

                photo_id = resp.get('id') or resp.get('post_id')
                if not photo_id:
                    logger.warning(f"Upload returned no photo id for image {idx}, response: {resp}")
                    continue
                media_fbs.append({"media_fbid": photo_id})

            if not media_fbs:
                logger.error("No photos were uploaded successfully; aborting post creation.")
                return False

            # Create the single post referencing uploaded media
            logger.info("Creating single feed post with attached media...")
            post_args = {
                "message": caption,
                "attached_media": json.dumps(media_fbs),
            }

            post_resp = graph.request(path=f"{page_id}/feed", method='POST', args=post_args)
            logger.info(f"Posted combined post to Facebook: {post_resp}")
            return True
        except Exception as e:
            logger.error(f"Error posting combined media to Facebook: {e}")

            # Fallback: try to post at least the first image with caption
            try:
                logger.info("Falling back: posting first image with caption as single post.")
                first_image = io.BytesIO(image_bytes_list[0])
                first_image.name = "front_page.jpg"
                first_image.seek(0)
                graph.put_photo(image=first_image, message=caption)
                return True
            except Exception as e2:
                logger.error(f"Fallback post also failed: {e2}")
                return False
    
    except Exception as e:
        logger.error(f"Error preparing Facebook post: {e}")
        return False
