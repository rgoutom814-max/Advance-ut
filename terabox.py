import os
import re
import logging
import requests

logger = logging.getLogger(__name__)

TERABOX_NDUS = os.environ.get("TERABOX_NDUS", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

TERABOX_DOMAINS = [
    "terabox.com", "1024tera.com", "terasharelink.com", "nephobox.com",
    "1024terabox.com", "4funbox.com", "mirrobox.com", "momerybox.com",
    "teraboxapp.com", "1024-terabox.com", "tera1024box.com",
    "teraboxlink.com", "terasharefile.com",
]


def is_terabox_url(url: str) -> bool:
    return any(domain in url for domain in TERABOX_DOMAINS)


def _extract_surl(url: str) -> str:
    """Pull the share-id ('surl') out of a Terabox share URL, e.g.
    https://1024terabox.com/s/1AbCdEfGhIjK -> 1AbCdEfGhIjK
    """
    match = re.search(r"/s/([A-Za-z0-9_-]+)", url)
    if not match:
        raise ValueError("Could not find a share ID in this Terabox link.")
    return match.group(1)


def get_download_info(share_url: str) -> dict:
    """Returns {'dlink': ..., 'filename': ..., 'size': ...} for the first
    file in a Terabox share link, using the ndus session cookie.
    """
    if not TERABOX_NDUS:
        raise RuntimeError(
            "TERABOX_NDUS is not set — Terabox downloads need a valid "
            "'ndus' cookie from a logged-in Terabox account."
        )

    surl = _extract_surl(share_url)
    cookies = {"ndus": TERABOX_NDUS}

    # Step 1: resolve the share info (gives us shareid/uk/sign/timestamp)
    list_url = "https://www.terabox.com/share/list"
    params = {
        "app_id": "250528",
        "shorturl": surl,
        "root": "1",
    }
    resp = requests.get(list_url, params=params, headers=HEADERS, cookies=cookies, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if data.get("errno") != 0:
        raise RuntimeError(f"Terabox: {data.get('errmsg', 'unknown error')} (errno {data.get('errno')})")

    file_list = data.get("list", [])
    if not file_list:
        raise RuntimeError("Terabox: no files found in this share link.")

    first_file = file_list[0]
    dlink = first_file.get("dlink")
    filename = first_file.get("server_filename", "video.mp4")
    size = int(first_file.get("size", 0))

    if not dlink:
        raise RuntimeError("Terabox: no dlink in response — the share link may be invalid or expired.")

    return {"dlink": dlink, "filename": filename, "size": size}


def download_terabox_file(share_url: str, output_path: str) -> str:
    """Downloads the first file from a Terabox share link to output_path
    (a full file path, not a directory). Returns the final filepath.
    """
    info = get_download_info(share_url)
    cookies = {"ndus": TERABOX_NDUS}

    with requests.get(info["dlink"], headers=HEADERS, cookies=cookies, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return output_path
