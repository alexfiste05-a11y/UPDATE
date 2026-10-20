#!/usr/bin/env python3
"""Download freely licensed real photos of the 2nd-gen Tesla Roadster from
Wikimedia Commons into images/ (needs commons.wikimedia.org and
upload.wikimedia.org reachable). Writes images/CREDITS.txt for attribution.

Review the picks and rename/reorder to taste:
  01 = hero front 3/4, 02 = detail close-up, 03 = side profile, 04 = rear/interior
"""
import json, os, re, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "roadster-launch-film/1.0 (personal project)"}


def get(params):
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA)))


def main():
    d = get({"action": "query", "generator": "categorymembers", "gcmtitle": "Category:Tesla Roadster (2020)",
             "gcmtype": "file", "gcmlimit": 100, "prop": "imageinfo",
             "iiprop": "url|size|extmetadata", "iiurlwidth": 3000})
    files = []
    for p in d.get("query", {}).get("pages", {}).values():
        ii = p["imageinfo"][0]
        if ii["width"] < 1600 or ii["width"] < ii["height"]:
            continue  # landscape, high-res only
        m = ii["extmetadata"]
        artist = re.sub("<[^>]+>", "", m.get("Artist", {}).get("value", "unknown"))
        files.append((ii["width"] * ii["height"], p["title"], ii.get("thumburl", ii["url"]),
                      artist, m.get("LicenseShortName", {}).get("value", "?"), ii["descriptionurl"]))
    files.sort(reverse=True)
    os.makedirs(os.path.join(HERE, "images"), exist_ok=True)
    credits = []
    for i, (_, title, url, artist, lic, page) in enumerate(files[:4], 1):
        dst = os.path.join(HERE, "images", f"{i:02d}.jpg")
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r, open(dst, "wb") as f:
            f.write(r.read())
        credits.append(f"{i:02d}.jpg  {title}  by {artist}  ({lic})  {page}")
        print("saved", dst, "-", title)
    with open(os.path.join(HERE, "images", "CREDITS.txt"), "w") as f:
        f.write("\n".join(credits) + "\n")


if __name__ == "__main__":
    main()
