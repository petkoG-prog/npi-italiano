"""
upload_r2.py — upload NPI media files (audio, video, PDF) to Cloudflare R2.
Images are NOT uploaded. Teacher guides ("Guida didattica") are skipped.

Prerequisites:
    pip install boto3

Usage:
    python upload_r2.py \
        --account  YOUR_CLOUDFLARE_ACCOUNT_ID \
        --key      YOUR_R2_ACCESS_KEY_ID \
        --secret   YOUR_R2_SECRET_ACCESS_KEY \
        --bucket   YOUR_BUCKET_NAME

How to get credentials:
  1. Cloudflare dashboard → R2 → Manage R2 API Tokens → Create API Token
     (permissions: Object Read & Write)
  2. Your account ID is in the URL:
     https://dash.cloudflare.com/ACCOUNT_ID/r2/...
  3. Create a bucket (e.g. "npi-italiano") and enable Public Access
     so files are reachable without auth.
  4. Copy your public bucket URL — it looks like:
     https://pub-XXXXXXXX.r2.dev
     Paste it in cdn.js as CDN_BASE.

R2 CORS (run once, already handled by this script):
    The script automatically sets the CORS policy on the bucket so that
    your Netlify site (or any origin) can load audio / video.
"""

import argparse
import os
import re
import sys
import unicodedata

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("boto3 is not installed. Run:  pip install boto3", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths — adjust LOCAL_ROOT if your NPI folder is elsewhere
# ---------------------------------------------------------------------------

LOCAL_ROOT = (
    "D:/Games/Marin T., Ruggieri L., Magnelli S., "
    "Cernigliaro M.A., Spinosa E. - Nuovissimo Progetto Italiano - 2019-2022"
)

# ---------------------------------------------------------------------------
# PDFs — every PDF in levels 1-4 EXCEPT the teacher guides ("Guida didattica")
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """ASCII-only, URL-safe file name (spaces, commas, $ and Cyrillic removed)."""
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    return base or "file"


def _title(stem: str) -> str:
    """'Marin T. - Nuovissimo Progetto Italiano 2. B1-B2. Libro dello studente - 2019' ->
    'Nuovissimo Progetto Italiano 2. B1-B2. Libro dello studente'"""
    parts = [p.strip() for p in stem.split(" - ")]
    if len(parts) > 1 and re.fullmatch(r"\d{4}", parts[-1]):
        parts = parts[:-1]
    if len(parts) > 1 and re.search(r"[.,]", parts[0]) and len(parts[0]) < 80:
        parts = parts[1:]
    return " - ".join(parts)


def pdf_entries():
    """Return [(local_path, r2_key, level, group, title, size_bytes)] sorted for display."""
    out, used = [], set()
    for level in (1, 2, 3, 4):
        lvl_dir = os.path.join(LOCAL_ROOT, str(level))
        for dirpath, _dirs, files in os.walk(lvl_dir):
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                local = os.path.join(dirpath, fname)
                rel = os.path.relpath(local, lvl_dir)
                if "guida didattica" in rel.lower():
                    continue  # teacher guides are excluded on purpose
                group = os.path.dirname(rel).replace("\\", "/") or "Libri"
                slug = _slug(os.path.splitext(fname)[0])
                key = f"level{level}/pdf/{slug}.pdf"
                n = 2
                while key in used:
                    key = f"level{level}/pdf/{slug}_{n}.pdf"
                    n += 1
                used.add(key)
                out.append((local, key, level, group, _title(os.path.splitext(fname)[0]),
                            os.path.getsize(local)))
    out.sort(key=lambda e: (e[2], e[3] != "Libri", e[3].lower(), e[4].lower()))
    return out


# (local_path, r2_key, content_type)
def build_manifest() -> list[tuple[str, str, str]]:
    manifest = []

    # Level 1 — 57 audio tracks
    audio1 = os.path.join(LOCAL_ROOT, "1", "Audio")
    for i in range(1, 58):
        fname = f"Traccia_{i}_NVSS.mp3"
        manifest.append((
            os.path.join(audio1, fname),
            f"level1/audio/{fname}",
            "audio/mpeg",
        ))

    # Level 2 — CD1 (22) + CD2 (32)
    audio2 = os.path.join(LOCAL_ROOT, "2", "Audio")
    for i in range(1, 23):
        fname = f"CD1-Traccia_ Audio_{i:02d}.mp3"
        manifest.append((os.path.join(audio2, fname), f"level2/audio/{fname}", "audio/mpeg"))
    for i in range(1, 33):
        fname = f"CD2-Traccia_ Audio_{i:02d}.mp3"
        manifest.append((os.path.join(audio2, fname), f"level2/audio/{fname}", "audio/mpeg"))

    # Level 3 — 10 videos (local names have "Unità N_title.mp4")
    video3 = os.path.join(LOCAL_ROOT, "3", "Video")
    wanted_units = {1, 10, 13, 14, 17, 18, 20, 21, 22, 25}
    for entry in os.listdir(video3):
        if not entry.endswith(".mp4"):
            continue
        m = re.match(r"Unit[àa]\s+(\d+)", entry, re.IGNORECASE)
        if not m:
            continue
        unit = int(m.group(1))
        if unit not in wanted_units:
            continue
        r2_name = f"Unita_{unit}.mp4"
        manifest.append((
            os.path.join(video3, entry),
            f"level3/video/{r2_name}",
            "video/mp4",
        ))

    # Level 4 — libro (26) + quaderno (26)
    audio4_libro = os.path.join(LOCAL_ROOT, "4", "Audio")
    audio4_quad  = os.path.join(LOCAL_ROOT, "4", "Audio esercizi")
    for i in range(1, 27):
        fname = f"nvs4cd1ltr{i:02d}.mp3"
        manifest.append((os.path.join(audio4_libro, fname), f"level4/audio_libro/{fname}", "audio/mpeg"))
    for i in range(1, 27):
        fname = f"nvs4cd1qtr{i:02d}.mp3"
        manifest.append((os.path.join(audio4_quad, fname), f"level4/audio_quaderno/{fname}", "audio/mpeg"))

    # PDFs (levels 1-4, no teacher guides)
    for local, key, _lvl, _grp, _ttl, _size in pdf_entries():
        manifest.append((local, key, "application/pdf"))

    return manifest


# ---------------------------------------------------------------------------
# CORS policy — allow any origin to fetch audio/video
# ---------------------------------------------------------------------------
CORS_CONFIG = {
    "CORSRules": [
        {
            "AllowedHeaders": ["*"],
            "AllowedMethods": ["GET", "HEAD"],
            "AllowedOrigins": ["*"],
            "ExposeHeaders":  ["Content-Length", "Content-Type", "Accept-Ranges"],
            "MaxAgeSeconds":  86400,
        }
    ]
}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def upload(args):
    endpoint = f"https://{args.account}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=args.key,
        aws_secret_access_key=args.secret,
        region_name="auto",
    )

    # Apply CORS once (may fail if API token lacks bucket-level permissions)
    print("Setting CORS policy …")
    try:
        s3.put_bucket_cors(Bucket=args.bucket, CORSConfiguration=CORS_CONFIG)
        print("  Done.")
    except ClientError as e:
        print(f"  Skipped ({e.response['Error']['Code']}) — set CORS manually in the Cloudflare dashboard.")

    manifest = build_manifest()
    total = len(manifest)
    ok = skip = fail = 0

    for idx, (local, r2_key, ctype) in enumerate(manifest, 1):
        tag = f"[{idx:3d}/{total}]"
        if not os.path.exists(local):
            print(f"{tag} MISSING  {local}")
            fail += 1
            continue

        # Skip if already uploaded (same size)
        try:
            head = s3.head_object(Bucket=args.bucket, Key=r2_key)
            r2_size = head["ContentLength"]
            local_size = os.path.getsize(local)
            if r2_size == local_size:
                print(f"{tag} skip     {r2_key}")
                skip += 1
                continue
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                print(f"{tag} WARN head_object: {e}")

        try:
            fsize_mb = os.path.getsize(local) / 1_048_576
            print(f"{tag} upload   {r2_key}  ({fsize_mb:.1f} MB)")
            s3.upload_file(
                local,
                args.bucket,
                r2_key,
                ExtraArgs={
                    "ContentType": ctype,
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )
            ok += 1
        except Exception as e:
            print(f"{tag} FAIL     {r2_key}: {e}")
            fail += 1

    print(f"\nDone — uploaded: {ok}  skipped: {skip}  failed: {fail}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Upload NPI media to Cloudflare R2")
    parser.add_argument("--account", required=True, help="Cloudflare Account ID")
    parser.add_argument("--key",     required=True, help="R2 Access Key ID")
    parser.add_argument("--secret",  required=True, help="R2 Secret Access Key")
    parser.add_argument("--bucket",  required=True, help="R2 bucket name")
    args = parser.parse_args()
    upload(args)


if __name__ == "__main__":
    main()
