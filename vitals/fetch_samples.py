"""Download real sample photos (injured, grimacing, neutral) from Wikimedia Commons.

Writes images plus manifest.json (title, source page, license, artist) into the
output directory so every benchmark input stays attributable.

    python -I vitals/fetch_samples.py <out_dir>
"""
import json
import time
import sys
import urllib.parse
import urllib.request

QUERIES = {
    "grimace": "man grimacing face",
    "pain": "facial expression of pain",
    "crying": "crying child face",
    "wounded": "wounded soldier face bandage",
    "casualty": "casualty first aid exercise",
    "rubble": "earthquake survivor rescued rubble",
    "neutral": "headshot portrait man",
}
PER_QUERY = 6
HEADERS = {"User-Agent": "mayfly-vitals-bench/0.1"}


def search(query):
    params = dict(action="query", format="json", generator="search",
                  gsrsearch=f"filetype:bitmap {query}", gsrnamespace=6, gsrlimit=PER_QUERY,
                  prop="imageinfo", iiprop="url|extmetadata", iiurlwidth=1280)
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as resp:
        return json.load(resp).get("query", {}).get("pages", {}).values()


def main(out):
    manifest = []
    for tag, query in QUERIES.items():
        for i, page in enumerate(search(query)):
            info = page["imageinfo"][0]
            meta = info.get("extmetadata", {})
            name = f"{tag}_{i}.jpg"
            time.sleep(1.5)  # Commons returns 429 on fast thumbnail bursts
            try:
                with urllib.request.urlopen(urllib.request.Request(info["thumburl"], headers=HEADERS)) as resp:
                    blob = resp.read()
            except Exception as e:
                print("skip", page["title"], e)
                continue
            with open(f"{out}/{name}", "wb") as f:
                f.write(blob)
            manifest.append(dict(file=name, tag=tag, title=page["title"], page=info["descriptionurl"],
                                 license=meta.get("LicenseShortName", {}).get("value"),
                                 artist=meta.get("Artist", {}).get("value", "")[:200]))
    with open(f"{out}/manifest.json", "w") as f:
        json.dump(manifest, f, indent=1)
    for m in manifest:
        print(m["file"], "|", m["title"], "|", m["license"])


if __name__ == "__main__":
    main(sys.argv[1])
