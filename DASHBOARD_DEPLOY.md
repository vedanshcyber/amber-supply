# Hubble Dashboard — Deployment Guide

This adds a **web dashboard** to your existing Hubble Slack bot, with read **and** write
(close / reassign / change priority from the browser).

The setup has two halves that live in two different places:

| Piece | What it is | Where it goes | Cost |
|---|---|---|---|
| `hubble_dashboard.html` | the website (static) | **GitHub Pages** | free |
| `dashboard_api.py` + your Flask app | the backend (Python) | **Render / Railway / Fly** | free tier OK |

> **Why not host everything on GitHub?** GitHub Pages only serves static files — it can't
> run Python, hold your Slack/Google secrets, or write to your sheet. So the dashboard goes
> on Pages and the backend stays on a Python host. The dashboard just calls the backend over HTTPS.

---

## Part 1 — Add the write endpoints to the backend

1. Copy `dashboard_api.py` into your Hubble project root (next to `app.py`).

2. Register the blueprint in `app.py`. After `ticket_service` and `slack_handler` are created, add:

   ```python
   from dashboard_api import dashboard_api
   app.register_blueprint(dashboard_api)
   ```

3. Set two new environment variables on your host:

   ```bash
   DASHBOARD_API_TOKEN=<long-random-string>        # required for any write
   DASHBOARD_ALLOWED_ORIGINS=https://YOURNAME.github.io
   ```

   Generate a token with:  `python -c "import secrets; print(secrets.token_urlsafe(32))"`

   - If `DASHBOARD_API_TOKEN` is **unset**, all writes are refused (fail-closed) — reads still work.
   - `DASHBOARD_ALLOWED_ORIGINS` is a comma-separated allow-list. Use `*` only for quick testing.

4. Deploy the backend (you already have `Procfile`, `runtime.txt`, `requirements.txt`):
   - **Render** → New Web Service → connect repo → add all env vars (existing Slack/Google ones
     **plus** the two above) → deploy. Note the URL, e.g. `https://hubble-xxxx.onrender.com`.

5. Verify:
   ```
   GET  https://your-backend/api/tickets         → JSON list
   POST https://your-backend/api/tickets/1/status with header X-Dashboard-Token → updates
   ```

### Endpoints added
| Method | Path | Body | Auth |
|---|---|---|---|
| GET | `/api/tickets` | — | open |
| GET | `/api/tickets/<id>` | — | open |
| POST | `/api/tickets/<id>/status` | `{"status":"Open"\|"Closed"}` | token |
| POST | `/api/tickets/<id>/assignee` | `{"assignee":"@Name"}` | token |
| POST | `/api/tickets/<id>/priority` | `{"priority":"Low\|Medium\|High\|Urgent"}` | token |
| POST | `/api/tickets/<id>` | any of the above combined | token |

These call the **same** `TicketService` methods the Slack buttons use, so Slack and web stay in sync.

---

## Part 2 — Put the dashboard on GitHub Pages

1. Open `hubble_dashboard.html` and set the backend URL near the bottom:

   ```js
   const API_BASE = "https://hubble-xxxx.onrender.com";   // no trailing slash
   const WORKSPACE = "amberstudent";                       // optional, for Slack deep-links
   ```

2. Create a GitHub repo (e.g. `hubble-dashboard`) and add the file. Easiest is to rename it
   `index.html` so it loads at the root:

   ```bash
   git init
   mv hubble_dashboard.html index.html
   git add index.html
   git commit -m "Hubble dashboard"
   git branch -M main
   git remote add origin https://github.com/YOURNAME/hubble-dashboard.git
   git push -u origin main
   ```

3. On GitHub: **Settings → Pages → Source: `main` / root → Save.**
   Your site goes live at `https://YOURNAME.github.io/hubble-dashboard/` within a minute or two.

4. Make sure `DASHBOARD_ALLOWED_ORIGINS` on the backend includes **exactly** that origin
   (`https://YOURNAME.github.io`), then reload the dashboard.

---

## Using it

- The dashboard loads tickets automatically (green dot = live, amber = demo/unreachable).
- Click any ticket → drawer opens → change status / priority / assignee → **Save changes.**
- The first save asks for the **dashboard token** (the `DASHBOARD_API_TOKEN` value). It's held only
  in that browser tab — never written into the public file.

## Security notes (worth reading once)
- The token is a shared secret typed in at runtime, fine for a small internal team. For anything
  bigger, put the dashboard behind real auth (e.g. Cloudflare Access or your SSO) and drop the token.
- Keep `DASHBOARD_ALLOWED_ORIGINS` pinned to your Pages URL, not `*`, once you're past testing.
- The backend still owns all permission/validation logic, so the browser can't do anything the
  service layer wouldn't allow.
