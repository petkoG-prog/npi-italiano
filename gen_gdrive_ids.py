"""
gen_gdrive_ids.py — populate gdrive.js with Google Drive file IDs.

Usage:
    python gen_gdrive_ids.py --key YOUR_API_KEY

How to get a free API key (no OAuth required, the folder is public):
  1. Go to https://console.cloud.google.com/
  2. Create a project → Enable "Google Drive API"
  3. Credentials → Create credentials → API key
  4. (Optional) Restrict the key to "Google Drive API"

The script recursively lists every file in the shared folder and matches
names to the keys already defined in gdrive.js.  It then rewrites gdrive.js
in-place with all matched IDs filled in and prints a report.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT_FOLDER = "1blI-oLaK4_e0RvQviSG_dgfkUU9l7AH7"
GDRIVE_JS   = "D:/Games/NPI/gdrive.js"

# ---------------------------------------------------------------------------
# Drive API helpers
# ---------------------------------------------------------------------------

def api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"[HTTP {e.code}] {url}\n{body}", file=sys.stderr)
        sys.exit(1)


def list_files(folder_id: str, api_key: str) -> list[dict]:
    """Return every file (not folder) under folder_id, recursively."""
    results = []
    page_token = None

    while True:
        params = {
            "q":      f"'{folder_id}' in parents and trashed = false",
            "key":    api_key,
            "fields": "nextPageToken,files(id,name,mimeType)",
            "pageSize": "1000",
        }
        if page_token:
            params["pageToken"] = page_token

        url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
        data = api_get(url)

        for f in data.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                results.extend(list_files(f["id"], api_key))
            else:
                results.append(f)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results


# ---------------------------------------------------------------------------
# gdrive.js rewriter
# ---------------------------------------------------------------------------

def load_gdrive_js(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def update_gdrive_js(source: str, name_to_id: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """
    Replace every  "filename.ext": ""  with  "filename.ext": "FILEID"
    where the filename matches a key in name_to_id.

    Returns (new_source, matched_names, unmatched_names).
    """
    matched   = []
    unmatched = list(name_to_id.keys())

    def replacer(m: re.Match) -> str:
        fname = m.group(1)
        fid   = name_to_id.get(fname, "")
        if fid:
            if fname in unmatched:
                unmatched.remove(fname)
            matched.append(fname)
            return f'"{fname}": "{fid}"'
        return m.group(0)  # leave blank entries alone

    new_source = re.sub(r'"([^"]+\.(mp3|mp4))":\s*"[^"]*"', replacer, source)
    return new_source, matched, unmatched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Populate gdrive.js from Google Drive folder.")
    parser.add_argument("--key", required=True, help="Google Drive API key")
    args = parser.parse_args()

    print("Listing files in Google Drive folder …")
    files = list_files(ROOT_FOLDER, args.key)
    print(f"  Found {len(files)} file(s).")

    name_to_id: dict[str, str] = {}
    for f in files:
        name = f["name"]
        fid  = f["id"]
        if name in name_to_id:
            print(f"  [WARN] Duplicate filename: {name!r} — keeping first occurrence.")
        else:
            name_to_id[name] = fid

    source = load_gdrive_js(GDRIVE_JS)
    new_source, matched, unmatched_in_drive = update_gdrive_js(source, name_to_id)

    with open(GDRIVE_JS, "w", encoding="utf-8") as f:
        f.write(new_source)

    print(f"\nUpdated {GDRIVE_JS}")
    print(f"  Matched and filled : {len(matched)}")
    if matched:
        for n in sorted(matched):
            print(f"    + {n}")

    # Files in gdrive.js that were NOT found on Drive
    all_js_keys = re.findall(r'"([^"]+\.(mp3|mp4))":', source)
    all_js_keys = [k for k, _ in all_js_keys]
    still_empty = [k for k in all_js_keys if k not in matched]
    if still_empty:
        print(f"\n  Still empty ({len(still_empty)}) — not found on Drive:")
        for n in still_empty:
            print(f"    - {n}")

    # Files on Drive that don't match any gdrive.js key
    extra = [n for n in name_to_id if n not in all_js_keys]
    if extra:
        print(f"\n  On Drive but not in gdrive.js ({len(extra)}):")
        for n in sorted(extra):
            print(f"    ? {n}")

    print("\nDone.")


if __name__ == "__main__":
    main()
