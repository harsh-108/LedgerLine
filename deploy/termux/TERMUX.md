# Running Ledgerline on an Android phone (Termux)

Works on the F-Droid Termux (Android 7+). 64-bit (aarch64) phones with 2 GB+
RAM are comfortable; 32-bit (arm) works but is slower; 1 GB RAM is marginal
(pandas + scikit-learn alone take ~300 MB).

## 0. On the PC — make a lean copy

`frontend-react/node_modules` (Windows binaries) is not needed on the phone;
`frontend-react/dist` is already built.

    # zip everything except node_modules; then copy the zip to the phone's Downloads
    # if you changed Login.tsx: cd frontend-react && npm run build   (before zipping)

## 1. Get the project into Termux

    termux-setup-storage                       # allow access to /sdcard (once)
    pkg install -y unzip
    unzip ~/storage/downloads/share_1.zip -x "*/node_modules/*" -d ~
    mv ~/share_1 ~/ledgerline

Bring your real `data/market_data.db` and your `.env` the same way
(`~/storage/downloads/...`), or `pkg install openssh` and `scp` them from the PC.

## 2. Install everything

    bash ~/ledgerline/deploy/termux/setup.sh

Takes 10–20 min on a slow phone. It installs Termux packages, points pip at the
Termux User Repository wheel index (prebuilt numpy/pandas/scipy/scikit-learn/
lxml/pydantic-core, so nothing heavy is compiled on the phone), installs
yfinance without `curl_cffi` (it falls back to `requests`), and ends with an
import check.

## 3. Configure

    nano ~/ledgerline/.env

- `APP_BASE_URL` = the address people will actually open. Find the phone's
  LAN IP with `ifconfig wlan0` → e.g. `http://192.168.1.50:8000`.
- `RESEND_API_KEY`, `MAIL_FROM` — see the mail notes in `.env.example`.
- Test mail from the phone:  `python ~/ledgerline/scripts/check_mail.py you@example.com`

## 4. Run once by hand

    bash ~/ledgerline/deploy/termux/start.sh
    # other devices on the same Wi-Fi: http://<phone-ip>:8000

Ctrl-C stops it. First start warms caches and may hit Yahoo/NSE for a while.

## 5. Autostart on boot (Termux:Boot)

    bash ~/ledgerline/deploy/termux/install-boot.sh

Then, on the phone itself (Android forgets otherwise):

1. Open the **Termux:Boot** app once (it just needs to have been launched).
2. Settings → Apps → Termux → Battery → **Unrestricted / Don't optimise**.
   Same for Termux:Boot.
3. Keep the Termux notification; swiping it away kills the shell.
4. Reboot and check: `tail -f ~/ledgerline/data/server.log`

The boot script runs two tiny supervisor loops: if uvicorn or the ngrok
tunnel dies, it restarts after 10 s (logs: `data/server.log`,
`data/ngrok.log`). The tunnel uses your reserved ngrok domain from
`NGROK_URL=your-name.ngrok-free.dev` in `.env` (or `data/ngrok_url`); without
one, or if ngrok isn't installed, only the server is supervised.
Running the boot script again never starts a second copy of either.
`bash ~/ledgerline/deploy/termux/stop.sh` stops the server only;
`stop.sh all` stops ngrok too.

## 6. Reaching it from outside your Wi-Fi (optional)

Email links only work from where `APP_BASE_URL` resolves, so for family on
other networks you need a tunnel:

- **Cloudflare Tunnel** (stable URL, HTTPS, free): put a domain on Cloudflare,
  `pkg install cloudflared`, `cloudflared tunnel login`, create a named tunnel
  pointing at `http://localhost:8000`, then set
  `APP_BASE_URL=https://ledger.yourdomain.in`. The same domain, once verified
  in Resend, also fixes `MAIL_FROM`.
- Quick test only: `cloudflared tunnel --url http://localhost:8000` gives a
  random `*.trycloudflare.com` URL that changes every run — fine for a demo,
  useless as `APP_BASE_URL`.
- **Tailscale** (`pkg install tailscale`, run `tailscaled --tun=userspace-networking`)
  if only you need it from your own devices.

## 7. Updating later (changed files only)

On the PC, make a zip of just the files that changed (paths relative to the
project root, e.g. `backend/app/main.py`, `frontend-react/dist/...`) and copy
it to the phone's Downloads. Then:

    bash ~/ledgerline/deploy/termux/update.sh ~/storage/downloads/ledgerline-update.zip

It stops the server, backs up the current code to `data/code-backup-*.tar.gz`,
unpacks the bundle (never `data/` or `.env`), checks that the app imports,
and restarts under the supervisor. If the import check fails it puts the old
code back and restarts that. ngrok keeps running throughout, and the
installed boot script is refreshed from the bundle.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pip` starts compiling numpy/pandas for an hour | The TUR index isn't active: `cat ~/.config/pip/pip.conf`, re-run setup. |
| `pydantic-core` "needs Rust" | Same cause; `--only-binary` in setup.sh must pick a TUR wheel. |
| Server dies after screen-off | Battery optimisation not disabled for Termux, or notification dismissed. |
| Other devices can't connect | You started it without `deploy/termux/start.sh` (needs `--host 0.0.0.0`), or the router isolates clients. |
| Times in the app are off | `TZ` is set to `Asia/Kolkata` in `start.sh`; change it if you're elsewhere. |
| Yahoo returns empty data / 429 | yfinance is on the `requests` fallback (no `curl_cffi` on Android); reduce refresh frequency in Settings. |
