# palworld-exporter

A **Prometheus exporter for a dedicated [Palworld](https://www.pocketpair.jp/palworld) server**, meant to run **on the game host itself**. It turns your server into Prometheus metrics so you can graph and alert on it in Grafana — live server health *and* deep save-file stats (Pals per player, box/party split, levels, captures, technologies, bosses…).

It exposes **only Palworld-related information** — no host CPU/RAM/disk — and has **no external dependency**: it talks to the game's own local APIs. Metrics come from two local sources:

- **Palworld's official REST API** (`127.0.0.1:8212`) — FPS, frame time, connected players (with ping and position), max players, server version and name.
- **save parser** (optional, bundled in [`parser/`](parser/)) — stats derived from parsing the save files: Pals per player (box / party / lucky), level, captures, technologies, bosses, dungeons…

> **Compatibility:** developed against **Palworld dedicated server `v1.0.3.101283`** (Steam app `2394010`). Live metrics come from the game's REST API and are essentially version-independent; the save parser reads the `PlM1` (Oodle-compressed) save format via [`palworld-save-tools`](https://github.com/cheahjs/palworld-save-tools) `0.24.0`, so it is the part tied to a specific game version.

---

## How it works

```
                         Palworld host (Linux)
  ┌──────────────────────────────────────────────────────────────┐
  │  Palworld server — REST API  :8212  (Basic auth)   ─┐         │
  │      └─ FPS, players, ping, version                 │ 127.0.0.1
  │  palworld-parser  :8100  (HTTP, reads save files)  ─┤         │
  │      └─ per-player save stats                       ▼         │
  │  palworld-exporter  :9812  ───────►  GET /metrics  (HTTP)     │
  └───────────────────────────────────────────┬──────────────────┘
                                               │ scrape (firewall-restricted)
                                               ▼
                                   Prometheus  ───►  Grafana
```

On every scrape the exporter:

1. calls the parser's `/metrics-data` (a cached snapshot — cheap) for save-derived per-player stats;
2. calls the game's REST API (`/v1/api/metrics`, `/v1/api/info`, `/v1/api/players`) for live server state;
3. renders everything as Prometheus text.

Each source is best-effort and independent: if the parser is down you still get live metrics (`palworld_stats_up 0`); if the server is stopped you still get save stats and `palworld_game_online 0`.

## Requirements

- **Palworld's REST API enabled.** In `PalWorldSettings.ini`:

  ```ini
  RESTAPIEnabled=True
  RESTAPIPort=8212
  AdminPassword="your-admin-password"
  ```

  The exporter authenticates as `admin` with `AdminPassword` over loopback. No game server mod or agent is required.

- **Python ≥ 3.11** on the host *only if* you want the save-stats parser (it needs the `pyooz` Oodle wheel). On RHEL/Rocky 9: `sudo dnf install -y python3.12`. Without it, the exporter still serves all live metrics.

- **Prometheus** to scrape it (plain Prometheus, kube-prometheus-stack, etc.).

## Install

Both components install as hardened systemd services. Run from a machine that can SSH to the game host:

```bash
# 1) The exporter (live metrics: FPS, players, ping).
#    Reads AdminPassword + REST port from PalWorldSettings.ini automatically.
make deploy REMOTE=user@game-host HOME_IP=<IP allowed to scrape /metrics>

# 2) The save-stats parser (per-player Pals box/party, levels, captures…).
#    Point SAVE_DIR at your SaveGames folder (the world sub-folder is auto-detected).
make parser-deploy REMOTE=user@game-host SAVE_DIR=/path/to/Pal/Saved/SaveGames
```

`install.sh` (exporter): extracts `AdminPassword`/`RESTAPIPort` from the `.ini`, creates an unprivileged system user, opens port `9812` **only to `HOME_IP`** (firewalld/ufw), installs a locked-down unit. `HOME_IP` is the source IP the game host sees when Prometheus scrapes it — see [Exposing & securing `/metrics`](#exposing--securing-metrics) if that IP is dynamic or Prometheus lives elsewhere. `install.sh` (parser): builds a Python venv, reads the local saves, re-parses every 5 min, listens on `127.0.0.1` only.

Local checks on the host:

```bash
curl -s http://127.0.0.1:9812/metrics | head
curl -s http://127.0.0.1:8100/metrics-data | head   # parser snapshot (JSON)
```

### Download a prebuilt binary

Every release ships static Linux binaries (amd64 & arm64) on the
[**Releases**](https://github.com/frakev/palworld-exporter/releases) page — no Go toolchain needed. Each tarball bundles the binary, `install.sh`, the systemd unit, `config.example.env`, and the `parser/` sources.

```bash
# pick the archive for your architecture from the latest release
curl -sSL -o palworld-exporter.tar.gz \
  https://github.com/frakev/palworld-exporter/releases/latest/download/palworld-exporter_<version>_linux_amd64.tar.gz
tar -xzf palworld-exporter.tar.gz && cd palworld-exporter_*_linux_amd64
sudo ./install.sh --home-ip <IP allowed to scrape /metrics>
```

Checksums are published as `checksums.txt` alongside the archives.

### Build from source

```bash
make build      # -> ./palworld-exporter (static, CGO-free)
make test
```

## Configuration

Exporter — `/etc/palworld-exporter/exporter.env` (see [`config.example.env`](config.example.env)):

| Key | Default | Purpose |
|---|---|---|
| `LISTEN` | `:9812` | HTTP listen address for `/metrics` |
| `REST_URL` | `http://127.0.0.1:8212` | Palworld REST API base URL |
| `REST_USER` | `admin` | Basic-auth user |
| `REST_PASSWORD` | — | the server's `AdminPassword`; empty = live metrics disabled |
| `PARSER_URL` | `http://127.0.0.1:8100` | save-stats parser; empty = no save metrics |
| `METRICS_TOKEN` | *(empty)* | if set, `/metrics` requires `Authorization: Bearer <token>` |

Parser — `/etc/palworld-parser/parser.env` (see [`parser/config.example.env`](parser/config.example.env)). The one setting to get right is **`SAVE_DIR`**, your `SaveGames` folder:

```bash
SAVE_DIR=/home/steam/Steam/steamapps/common/PalServer/Pal/Saved/SaveGames
REPARSE_INTERVAL=300     # re-parse the saves every 5 min (0 = disabled)
```

## Prometheus scrape config

```yaml
scrape_configs:
  - job_name: palworld
    scrape_interval: 30s
    static_configs:
      - targets: ["<game-host>:9812"]
    # If METRICS_TOKEN is set on the exporter (see below):
    # authorization:
    #   type: Bearer
    #   credentials: "<METRICS_TOKEN>"
```

## Exposing & securing `/metrics`

`/metrics` is **plain HTTP with no authentication by default** and includes information about your server (player names, positions, FPS…). So you must not leave port `9812` open to the whole internet. Pick **one** of these:

### Option A — firewall to a single source IP (installer default)

`install.sh --home-ip <IP>` restricts the port to one source address: the machine that scrapes it. The value is **the source IP the game host sees when Prometheus connects**, which depends on where Prometheus runs:

| Where Prometheus runs | `--home-ip` value |
|---|---|
| On the **same machine** as the Palworld server | `127.0.0.1` (nothing is opened to the network) |
| On the **same LAN** as the game host | Prometheus's LAN IP |
| On another site / at home, behind a router (Prometheus scrapes a remote game host) | **the public IP of that network** (e.g. `curl ifconfig.me` from there) — because of NAT, all its traffic arrives with that one address |

Simple and dependency-free, but awkward if that IP is **dynamic** (it changes) — then prefer B or C.

### Option B — bearer token (good for dynamic IPs)

Set a token in `/etc/palworld-exporter/exporter.env` and restart the service:

```bash
METRICS_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -dc A-Za-z0-9)
```

Now `/metrics` rejects requests without `Authorization: Bearer <token>`, so the port can be reachable from more than one address. Give the same token to Prometheus:

```yaml
    authorization:
      type: Bearer
      credentials: "<METRICS_TOKEN>"
```

### Option C — private tunnel (cleanest)

Put the game host and Prometheus on a private network ([WireGuard](https://www.wireguard.com/), [Tailscale](https://tailscale.com/)…) and scrape the tunnel address. Nothing is exposed publicly and there is no fixed-IP requirement. You can then bind the exporter to the tunnel interface (`LISTEN=<tunnel-ip>:9812`) or firewall to the tunnel subnet.

You can also combine A/C with B for defence in depth.

## Metrics

All gauges, prefixed `palworld_`.

### Live server & game (via the REST API)

| Metric | Description |
|---|---|
| `palworld_game_online` | 1 if the game REST API answers (server up and ready) |
| `palworld_game_info{version,server_name}` | server version & name (value = 1) |
| `palworld_server_fps` | server FPS |
| `palworld_server_frametime_ms` | server frame time (ms) |
| `palworld_players_current` / `palworld_players_max` | connected / max players |
| `palworld_game_uptime_seconds` | uptime reported by the game |
| `palworld_player_online{name,player_id}` | 1 per connected player |
| `palworld_player_ping_ms{name,player_id}` | connected player ping |
| `palworld_player_location_x{…}` / `_y{…}` | connected player map position |
| `palworld_scrape_duration_seconds` | collection time |

### Save stats (via the parser — labels `uid,name,guild`)

| Metric | Description |
|---|---|
| `palworld_stats_up` | 1 if the parser responds |
| `palworld_stats_snapshot_timestamp_seconds` | last save parse (epoch) |
| `palworld_guilds_total` / `palworld_players_known_total` | guilds / known players |
| `palworld_pals_total` / `palworld_pals_lucky_total` | owned / lucky Pals (server-wide) |
| `palworld_player_level` / `palworld_player_exp` | level / XP |
| `palworld_player_pals_owned` | total Pals owned |
| **`palworld_player_pals_box`** | **Pals in the palbox** |
| **`palworld_player_pals_party`** | **Pals in the active party** |
| `palworld_player_pals_lucky` | lucky (shiny) Pals |
| `palworld_player_captures` / `palworld_player_tribes_captured` | captures / species |
| `palworld_player_paldeck` | Paldeck entries |
| `palworld_player_technologies` / `palworld_player_technology_points` | techs / points |
| `palworld_player_boss_technology_points` | ancient (boss) tech points |
| `palworld_player_tower_bosses` / `palworld_player_field_bosses` | tower / field bosses |
| `palworld_player_dungeons` | dungeons cleared |
| `palworld_player_zones_explored` / `palworld_player_fast_travels` | exploration |
| `palworld_player_effigies` / `palworld_player_quests_completed` | effigies / quests |
| `palworld_player_last_online_timestamp_seconds` | last login (epoch) |

`palworld_game_*` and per-connected-player metrics only appear while the server is running; save stats stay available even when it is stopped.

### Sample output

```prometheus
palworld_game_online 1
palworld_game_info{version="v1.0.3.101283",server_name="My \"Example\" Server"} 1
palworld_server_fps 58.4
palworld_players_current 2
palworld_player_ping_ms{name="Alice",player_id="abc123"} 42.5

palworld_stats_up 1
palworld_pals_total 137
palworld_pals_lucky_total 3
palworld_player_level{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 42
palworld_player_pals_box{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 25
palworld_player_pals_party{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 5
palworld_player_pals_lucky{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 2
palworld_player_captures{uid="a1b2c3d4",name="Alice",guild="ExampleWorld"} 410
```

## Example queries (PromQL)

```promql
# Connected players over time
palworld_players_current

# Server FPS
palworld_server_fps

# Pals in each player's box, top 10
topk(10, palworld_player_pals_box)

# Total lucky Pals on the server
palworld_pals_lucky_total

# Alert: server went offline
palworld_game_online == 0

# Alert: saves haven't been parsed in over an hour
time() - palworld_stats_snapshot_timestamp_seconds > 3600
```

## Security

- The exporter is **read-only** and needs no privileges (its systemd unit runs with `NoNewPrivileges`, `ProtectSystem=strict`, a syscall filter, etc.).
- It reaches the game and the parser over **loopback only**. Your `AdminPassword` lives in `exporter.env` (mode `0640`, owned by the exporter user) and never leaves the host.
- `/metrics` is plain HTTP and unauthenticated by default — lock it down with a firewall rule, a bearer token, or a private tunnel. See [Exposing & securing `/metrics`](#exposing--securing-metrics).
- **Never commit** a real `*.env`, password, or save file — see [`.gitignore`](.gitignore).

## How the save parser works

The parser reads `Level.sav` + `Players/*.sav` from your `SaveGames` world folder, decompresses the `PlM1`/Oodle blocks (`pyooz`), decodes the GVAS structures (`palworld-save-tools`), and aggregates per-player counters and Pal container membership (box vs party vs base). It caches a snapshot in SQLite and re-parses on an interval, so scrapes stay cheap. It listens on `127.0.0.1` only and exposes `GET /metrics-data` (JSON) for the exporter. Because it depends on the save format, it is the component tied to a specific game version (`v1.0.3.101283`).

## License

[MIT](LICENSE) © frakev
