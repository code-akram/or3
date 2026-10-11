"""Explore Freesound candidates (licence-filtered). Prints one line per result.

    uv run python -I -m audiopipe.search 'tokyo street' --geo 35.69,139.70,30 --tag ambience
"""

from __future__ import annotations

import argparse
import urllib.parse

from .common import RateLimiter, freesound_token, http_json

API = "https://freesound.org/apiv2"
LICENCE_FILTER = 'license:("Creative Commons 0" OR "Attribution")'
FIELDS = "id,name,username,license,type,samplerate,bitdepth,channels,duration,filesize,geotag,tags,num_downloads,avg_rating"

limiter = RateLimiter(2.0)  # 30 req/min max, well under 60/min


def search(query: str, filters: list[str], page_size: int = 30, sort: str = "score") -> list[dict]:
    flt = " ".join([LICENCE_FILTER, *filters])
    qs = urllib.parse.urlencode({
        "query": query, "filter": flt, "fields": FIELDS, "page_size": page_size, "sort": sort,
    })
    tok = freesound_token()
    data = http_json(f"{API}/search/?{qs}", {"Authorization": f"Bearer {tok}"}, limiter)
    return data.get("results", [])


def sound(sound_id: int) -> dict:
    tok = freesound_token()
    return http_json(f"{API}/sounds/{sound_id}/?fields={FIELDS},description,url,pack,created,download",
                     {"Authorization": f"Bearer {tok}"}, limiter)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--geo", help="lat,lon,km")
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument("--filter", action="append", default=[])
    ap.add_argument("--sort", default="score")
    ap.add_argument("-n", type=int, default=30)
    a = ap.parse_args()
    f = list(a.filter)
    if a.geo:
        lat, lon, km = a.geo.split(",")
        f.append(f"{{!geofilt sfield=geotag pt={lat},{lon} d={km}}}")
    f += [f"tag:{t}" for t in a.tag]
    for r in search(a.query, f, a.n, a.sort):
        lic = r["license"].rstrip("/").split("/")[-2:]
        print(f'{r["id"]:>7} {r["type"]:>4} {r["samplerate"]:>6}/{r.get("bitdepth")}/{r["channels"]}ch '
              f'{r["duration"]:7.1f}s {"/".join(lic):14} dl={r.get("num_downloads")} '
              f'{r["username"][:16]:16} {r["name"][:50]} | {r.get("geotag") or ""}')


if __name__ == "__main__":
    main()
