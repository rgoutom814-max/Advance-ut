import logging
from flask import Flask, redirect, abort

import config
import utils

logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/")
def home():
    return "⚡ Download server is running!"


@app.route("/health")
def health():
    return "OK"


@app.route("/download/<short_id>/<quality>")
def download(short_id, quality):
    """
    Creates a direct download redirect.

    The server does not download or store the video.
    It asks yt-dlp for the media URL and redirects the user's
    browser to that URL.
    """

    allowed_qualities = {
        "360p",
        "480p",
        "720p",
        "1080p",
        "audio",
    }

    if quality not in allowed_qualities:
        abort(404)

    url = utils.get_pending_url(short_id)

    if not url:
        return (
            "❌ Link expired. Please send the YouTube link again.",
            404,
        )

    try:
        direct_url = utils.get_direct_url_for_quality(
            url,
            quality,
        )

        if not direct_url:
            return (
                "❌ This quality is not available.",
                404,
            )

        # Redirect directly to the media URL.
        return redirect(direct_url, code=302)

    except Exception:
        logger.exception("Failed to create direct download link")
        return (
            "❌ Download link could not be created.",
            500,
        )


if __name__ == "__main__":
    port = int(getattr(config, "PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
  )
  
