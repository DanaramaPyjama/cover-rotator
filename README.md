# Cover Rotator

## FAQ

<details>
<summary><strong>Is this AI slop?</strong></summary>

Pretty much. I can, and do, write code, but this would have taken me days on my own. Since it's for personal use, I used AI to save time and had it written and tested in a couple of hours.
</details>

<details>
<summary><strong>Can I use it?</strong></summary>

Yes, feel free to use the code under the terms of the licence. It's provided free, so please don't charge for it.
</details>

<details>
<summary><strong>Is it secure?</strong></summary>

I built this for myself, running on a private network, so there are no security controls baked in. It's designed for a single user who configures it with environment variables. The web front end shows your lists, the cover images and the media names, and that's about it. The only protected action is `/rotate`, which needs the `ADMIN_TOKEN`.
</details>

<details>
<summary><strong>What support is offered?</strong></summary>

None, I built it for personal use. Use it, fork it, do what you like. I won't be accepting PRs. If you fork it and improve it, let me know, as I may start using your version instead. 😄
</details>

<details>
<summary><strong>Why are the environment variables in the compose file?</strong></summary>

That's just how I prefer to do things. Organise it however you like. The compose file works on its own as it is, with no separate config file needed.
</details>

### AIOMetadata / AIOStreams

<details>
<summary><strong>Should I change anything in AIOMetadata?</strong></summary>

Yes:

1. Make sure you're using AIOM's **poster proxy** settings.
2. Add your subdomain (for example `covers.yourdomain.com`) to AIOM's **image cache** as an exception.
3. Consider reducing the cache time to 12 or 24 hours.
</details>

<details>
<summary><strong>What about AIOStreams?</strong></summary>

If AIOMetadata is an addon in AIOStreams, you may also want to stop AIOStreams caching catalogues for addons.
</details>

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
| `SYNC_HOURS` | 0 | `0` = re-read a list from MDBList only when its cover is about to rotate (one API call per list per rotation). Set e.g. `24` to also sync on a fixed schedule |
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
