#!/usr/bin/env python3
"""
Quick test script to post a blank image to Facebook page.
Enhanced: attempts to auto-detect a Page Access Token from a user token
and prints diagnostic information about accessible Pages.

Usage:
    python test_facebook.py
"""

import os
import io
import logging
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import facebook
except ImportError:
    logger.error("facebook-sdk not installed. Run: pip install facebook-sdk")
    exit(1)


def _discover_page_token(graph, target_page_id=None):
    """Try to discover a Page Access Token using the provided token's
    `me/accounts` connection. Returns (page_id, page_name, page_token) or None.
    """
    try:
        logger.info("Querying /me/accounts to discover page access tokens...")
        accounts = graph.get_connections('me', 'accounts')
        data = accounts.get('data', []) if isinstance(accounts, dict) else []
        if not data:
            logger.info("No pages found for this token (empty /me/accounts).")
            return None

        # Print a brief list of pages we can access
        logger.info("Accessible Pages:")
        for p in data:
            pid = p.get('id')
            name = p.get('name')
            token = p.get('access_token')
            logger.info(f" - {name} (id={pid})")
            if target_page_id and str(pid) == str(target_page_id):
                logger.info(f"Found matching page {name} ({pid}). Using its Page Access Token.")
                return pid, name, token

        # If no exact match, return the first page's token as a convenience
        first = data[0]
        logger.info(f"No matching page id found; falling back to first page: {first.get('name')} ({first.get('id')})")
        return first.get('id'), first.get('name'), first.get('access_token')

    except facebook.GraphAPIError as e:
        logger.error(f"GraphAPIError while fetching /me/accounts: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while fetching pages: {e}")
        return None


def test_facebook_posting():
    """Test Facebook posting with a blank image. Will try to auto-detect
    a Page Access Token (preferred) and fall back to a provided token.
    """
    facebook_page_id = os.getenv("FACEBOOK_PAGE_ID")
    facebook_access_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")

    if not facebook_access_token:
        logger.error("FACEBOOK_PAGE_ACCESS_TOKEN not set in environment.")
        logger.info("Set it using (PowerShell):")
        logger.info("  $env:FACEBOOK_PAGE_ACCESS_TOKEN='your_access_token'")
        logger.info("If you have a user token, this script will try to find a Page token via /me/accounts.")
        return False

    try:
        # Create a blank test image
        logger.info("Creating blank test image...")
        test_img = Image.new('RGB', (800, 600), color=(73, 109, 137))
        img_bytes = io.BytesIO()
        test_img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        img_bytes.name = "test_image.jpg"

        # Initialize Graph API with the provided token (user or page)
        logger.info("Initializing Graph API with provided token...")
        graph = facebook.GraphAPI(access_token=facebook_access_token)

        chosen_token = facebook_access_token
        used_page_id = None

        # If the user provided a PAGE ID, try to find its page token specifically
        if facebook_page_id:
            discovered = _discover_page_token(graph, facebook_page_id)
        else:
            discovered = _discover_page_token(graph, None)

        if discovered:
            pid, name, page_token = discovered
            if page_token:
                chosen_token = page_token
                used_page_id = pid
                logger.info(f"Using Page Access Token for page: {name} ({pid})")
        else:
            logger.warning("Could not discover a Page Access Token; using the provided token as-is.")

        # Use the chosen token to perform the upload
        page_graph = facebook.GraphAPI(access_token=chosen_token)

        logger.info("Posting test image to Facebook...")
        img_bytes.seek(0)
        response = page_graph.put_photo(image=img_bytes, message="Test post from Pokémon TCG Pocket bot 🤖 - Testing API connection")

        logger.info(f"✅ SUCCESS! Image posted with ID: {response.get('id')}")
        if used_page_id:
            logger.info(f"Posted to Page ID: {used_page_id}")
        else:
            logger.info("Posted using supplied token (could be a Page token you set manually).")
        return True

    except facebook.GraphAPIError as e:
        logger.error(f"❌ Facebook GraphAPIError: {e}")
        # Some GraphAPIError instances include .code and .error_data
        try:
            logger.error(f"Error type/code: {getattr(e, 'code', 'N/A')}")
        except Exception:
            pass
        logger.error("Check that the token is a Page Access Token with publish permissions (pages_manage_posts or equivalent).")
        logger.error("Also ensure your Facebook App has the necessary permission approvals for production use.")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = test_facebook_posting()
    exit(0 if success else 1)
