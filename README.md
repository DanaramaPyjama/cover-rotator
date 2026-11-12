# Cover Rotator

Q: Is this AI Slop?
A: Pretty much.  I can, and do write code but this would have taken me days on my own so, I saved time given this is for personal use and wrote an dtested it in a couple of hours.

Q: Can I use it?
A: Feel free to use the code as per the licence.  This project is provided free, so please do not charge for this code

Q: Is it secure?
A: I built this for myself, running on a private network.  There are no security controls baked in. It's designed for a single user to configure via env, and presents a web front end that shows you the lists, the images, and the media name and thats about it.

Q: What support is offered?
A: None.  I built it for personal use.  Feel free to use it, fork it whatever.  I will not be accepting PRs.  If you fork it and update it, please let me know as I may start using your version instead :D

Q: Should I change anything in AIOMetadata?
A: Yes you need to ensure you're using AIOM's poster proxy settings.  Also add your subdomain, for example covers.yourdomain.com as part of AIOM Image cache to create an exception (Reduce to 12 or 24 hours perhaps)

Q: What about AIOStreams?
A: If AIOmetadata is an addon in AIOStreams, you may also wish to prevent AIOStreams caching catalogues for addons.

Rotating, random landscape AIOMetadata "covers" for your [MDBList](https://mdblist.com) list-based collections.
Each list gets **one permanent URL**; the image behind it switches to a random item
from that list every 48 hours (configurable). Use the URLs as collection cover images
in AIOM

- **Movies** → TMDB backdrops
- **TV shows & anime series** → TVDB backgrounds (falls back to TMDB if TVDB has none)
- Prefers textless art, cycles through every item before repeating, never repeats back-to-back
- Art is only downloaded when an item is picked, so API usage is tiny
- Single Python file, standard library only. Multi-arch image (amd64 + arm64)

## Quick start

You need: an [MDBList API key](https://mdblist.com/preferences/), a
[TMDB API key](https://www.themoviedb.org/settings/api) (v3 key or v4 read token), and
optionally a [TVDB v4 key](https://thetvdb.com/api-information).

**Linux / macOS**
```bash
curl -O https://raw.githubusercontent.com/DanaramaPyjama/cover-rotator/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/DanaramaPyjama/cover-rotator/main/.env.example
nano .env                  # add your keys
nano docker-compose.yml    # edit the LISTS block
docker compose up -d
docker compose logs -f
```

**Windows (PowerShell, Docker Desktop)**
```powershell
Invoke-WebRequest https://raw.githubusercontent.com/DanaramaPyjama/cover-rotator/main/docker-compose.yml -OutFile docker-compose.yml
Invoke-WebRequest https://raw.githubusercontent.com/DanaramaPyjama/cover-rotator/main/.env.example -OutFile .env
notepad .env                  # add your keys
notepad docker-compose.yml    # edit the LISTS block
docker compose up -d
docker compose logs -f
```

Open `http://<host>:8099/` for a preview of every list's current cover.

## Lists

One per line, `key=username/list-slug`. The slug is from the list's mdblist.com address
(`mdblist.com/lists/<username>/<slug>`). A slug without the username will 404.

The key becomes the URL: `http://<host>:8099/cover/<key>.jpg`

Prefer a file? Mount a `config.json` (see `config.example.json`) at `/config/config.json`.
Environment variables override the file.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `MDBLIST_API_KEY` | required | |
| `TMDB_API_KEY` | required | v3 key or v4 read token |
| `TVDB_API_KEY` | empty | Without it, shows use TMDB |
| `TVDB_PIN` | empty | Only for subscriber-type TVDB keys |
| `LISTS` | required | `key=username/slug`, one per line |
| `BASE_URL` | `http://localhost:8099` | Public address, used only to display links |
| `ROTATE_HOURS` | 48 | How often each cover changes |
| `SYNC_HOURS` | 12 | How often lists are re-read from MDBList |
| `IMAGE_SIZE` | `w1280` | TMDB size: `w780`, `w1280`, `original` |
| `FALLBACK_TO_TMDB` | true | Shows: use TMDB if TVDB has no background |
| `ADMIN_TOKEN` | empty | Enables `/rotate`; empty = disabled |
| `PORT` | 8099 | |

State and downloaded art live in the `/data` volume.

## Endpoints

| URL | Purpose |
|---|---|
| `/cover/<key>.jpg` | The rotating cover |
| `/` | Preview page |
| `/status` | JSON: current title and next rotation per list |
| `/health` | Liveness check |
| `/rotate/<key>?token=<ADMIN_TOKEN>` | Force a re-roll now |

## Behind a reverse proxy

Point your proxy (Traefik, Caddy, nginx) at port 8099 and set `BASE_URL` to the public
HTTPS address. Covers are safe to expose; `/rotate` stays off unless `ADMIN_TOKEN` is set.

## Notes

- Media apps may cache cover images. If a collection doesn't pick up a new cover, refresh
  its image in the app. The server is serving the new one.
- Anime **movies** use TMDB (MDBList gives no TVDB ID for movies).
- Needs outbound access to `api.mdblist.com`, `api.themoviedb.org`, `image.tmdb.org`,
  `api4.thetvdb.com`, `artworks.thetvdb.com`.
- Data volume is written as UID 1000. For a bind mount, `chown 1000:1000` the folder.

## Publishing your own fork

Push to GitHub; the included workflow builds and publishes
`ghcr.io/<you>/cover-rotator` on every push to `main` and on `v*` tags.
After the first run, set the package to **Public** (GitHub profile → Packages →
cover-rotator → Package settings) so others can pull it without logging in.

## Credits

Data from MDBList, TMDB and TVDB. Credits to AIOMetadata for providing an awesome platform
