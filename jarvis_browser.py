"""
jarvis_browser.py — Browser automation for Jarvis (Playwright)
Keeps ONE persistent Chromium window open.
Automatically restarts if the browser window is closed.
All functions are synchronous and thread-safe.
"""

import time
import threading

_lock = threading.Lock()
_pw       = None
_browser  = None
_page     = None


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_all():
    """Tear down everything so a fresh browser can be created."""
    global _pw, _browser, _page
    for obj, method in ((_page, "close"), (_browser, "close"), (_pw, "stop")):
        try:
            if obj is not None:
                getattr(obj, method)()
        except Exception:
            pass
    _page = None
    _browser = None
    _pw = None


def _get_page():
    """Return the active Playwright page, restarting the browser if it died."""
    global _pw, _browser, _page

    with _lock:
        # ── Check if page is still alive ───────────────────────────────────
        page_alive = False
        try:
            if _page is not None and not _page.is_closed():
                # Ping the page with a trivial JS call to confirm it's really alive
                _page.evaluate("1")
                page_alive = True
        except Exception:
            page_alive = False

        if page_alive:
            return _page

        # ── Page is dead — start fresh ─────────────────────────────────────
        _reset_all()

        from playwright.sync_api import sync_playwright
        _pw      = sync_playwright().start()
        _browser = _pw.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        ctx   = _browser.new_context(viewport=None)
        _page = ctx.new_page()

    return _page


def _trim(text: str, max_words: int = 80) -> str:
    words = text.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "..."
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Public browser tools
# ─────────────────────────────────────────────────────────────────────────────

def browser_open(url: str) -> str:
    """Navigate to any URL."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        page = _get_page()
        page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        title = page.title() or url
        return f"Opened {title}."
    except Exception as e:
        return f"Could not open that page. {e}"


def youtube_play(query: str) -> str:
    """Search YouTube and play the first real video result."""
    try:
        page = _get_page()
        search_url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
        page.goto(search_url, timeout=30_000, wait_until="domcontentloaded")
        time.sleep(2)

        # ── Step 1: Dismiss cookie / consent dialog if present ──────────────
        for consent in ("Accept all", "Accept All", "I agree", "Agree", "Reject all"):
            try:
                btn = page.get_by_role("button", name=consent, exact=False)
                if btn.first.is_visible(timeout=1000):
                    btn.first.click()
                    time.sleep(1)
                    break
            except Exception:
                pass

        # ── Step 2: Try multiple selectors — grab href and navigate directly ─
        # Navigating via href is far more reliable than clicking
        SELECTORS = [
            "ytd-video-renderer a#video-title",        # standard video card
            "ytd-video-renderer a#video-title-link",   # alternate attribute
            "ytd-compact-video-renderer a#video-title",
            "a#video-title[href*='/watch']",
            "a[href*='/watch?v=']",                    # any watch link
        ]

        video_url = None
        title = query

        for selector in SELECTORS:
            try:
                els = page.locator(selector)
                count = els.count()
                for i in range(min(count, 5)):           # check first 5 results
                    el = els.nth(i)
                    href = el.get_attribute("href") or ""
                    if "/watch?v=" in href or "/shorts/" in href:
                        t = el.get_attribute("title") or el.get_attribute("aria-label") or query
                        if t:
                            title = t
                        video_url = "https://www.youtube.com" + href if href.startswith("/") else href
                        break
                if video_url:
                    break
            except Exception:
                continue

        # ── Step 3: Navigate directly to the video URL ──────────────────────
        if video_url:
            page.goto(video_url, timeout=20_000, wait_until="domcontentloaded")
            time.sleep(2)

            # Try to start playback if paused
            try:
                play_btn = page.locator(".ytp-play-button").first
                label = (play_btn.get_attribute("aria-label") or "").lower()
                if "play" in label and "pause" not in label:
                    play_btn.click()
            except Exception:
                pass

            return f"Playing {title} on YouTube."

        # ── Step 4: Last resort — try JavaScript to grab first video href ───
        try:
            href = page.evaluate("""() => {
                const a = document.querySelector('a[href*="/watch?v="]');
                return a ? a.href : null;
            }""")
            if href:
                page.goto(href, timeout=20_000, wait_until="domcontentloaded")
                return f"Playing {query} on YouTube."
        except Exception:
            pass

        return f"I found the YouTube search for {query}, but could not click the video. Try saying 'click the first video'."

    except Exception as e:
        return f"YouTube ran into a problem: {e}"



def web_search(query: str) -> str:
    """Google search — returns a spoken summary of the top result."""
    try:
        page = _get_page()
        page.goto(
            "https://www.google.com/search?q=" + query.replace(" ", "+"),
            timeout=30_000, wait_until="domcontentloaded"
        )
        time.sleep(1)

        # Try featured snippet / knowledge panel first
        for selector in [
            "[data-attrid='wa:/description'] span",
            ".hgKElc",          # featured snippet paragraph
            ".IZ6rdc",          # knowledge panel description
            ".VwiC3b",          # normal result snippet
            ".s3v9rd",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1000):
                    text = el.inner_text().strip()
                    if text:
                        return _trim(text, 70)
            except Exception:
                continue

        return f"I searched for {query} but could not read a clear answer from the page."
    except Exception as e:
        return f"Web search failed: {e}"


def browser_read_page() -> str:
    """Read and summarise the text content of the current browser page."""
    try:
        page = _get_page()
        text = page.evaluate("""() => {
            const clone = document.body.cloneNode(true);
            clone.querySelectorAll('script,style,nav,footer,header,aside').forEach(e => e.remove());
            return (clone.innerText || '').replace(/\\n+/g,' ').trim();
        }""")
        return _trim(text, 120) or "The page appears to have no readable text."
    except Exception as e:
        return "Could not read page content."


def browser_click(text: str) -> str:
    """Click a visible element by its text label."""
    try:
        page = _get_page()
        # Try exact text first, then partial
        for strict in (True, False):
            try:
                page.get_by_text(text, exact=strict).first.click(timeout=4000)
                return f"Clicked '{text}'."
            except Exception:
                continue
        return f"Could not find '{text}' to click on the page."
    except Exception as e:
        return f"Click failed: {e}"


def browser_fill(field: str, value: str) -> str:
    """Find an input field by label/placeholder and type a value into it."""
    try:
        page = _get_page()
        filled = False
        for loc in [
            page.get_by_label(field, exact=False),
            page.get_by_placeholder(field, exact=False),
            page.locator(f"input[name*='{field}']"),
            page.locator(f"input[id*='{field}']"),
        ]:
            try:
                if loc.first.is_visible(timeout=1500):
                    loc.first.fill(value)
                    filled = True
                    break
            except Exception:
                continue
        return f"Filled in {field}." if filled else f"Could not find the '{field}' field."
    except Exception as e:
        return f"Fill failed: {e}"


def browser_scroll(direction: str = "down", amount: int = 3) -> str:
    """Scroll the current browser page up or down."""
    try:
        page = _get_page()
        px = 400 * amount * (1 if direction == "down" else -1)
        page.evaluate(f"window.scrollBy(0, {px})")
        return f"Scrolled {direction}."
    except Exception as e:
        return "Could not scroll the page."


def browser_go_back() -> str:
    """Go back one page in browser history."""
    try:
        page = _get_page()
        page.go_back(timeout=10_000)
        return "Went back."
    except Exception:
        return "Could not go back."


def browser_press_enter() -> str:
    """Press Enter in the browser (submit a form or search)."""
    try:
        page = _get_page()
        page.keyboard.press("Enter")
        return "Pressed Enter."
    except Exception:
        return "Could not press Enter in browser."


def browser_screenshot() -> str:
    """Take a screenshot of the current browser page and save it."""
    try:
        import os
        page = _get_page()
        path = r"C:\jarvis-local\browser_screenshot.png"
        page.screenshot(path=path, full_page=False)
        return "Browser screenshot saved."
    except Exception as e:
        return "Could not take a browser screenshot."


def browser_get_url() -> str:
    """Return the URL of the current browser page."""
    try:
        page = _get_page()
        return f"Currently on {page.url}"
    except Exception:
        return "No browser page is open."


def browser_close() -> str:
    """Close the browser entirely."""
    global _pw, _browser, _page
    try:
        if _page and not _page.is_closed():
            _page.close()
        if _browser:
            _browser.close()
        if _pw:
            _pw.stop()
    except Exception:
        pass
    finally:
        _page = None
        _browser = None
        _pw = None
    return "Browser closed."
