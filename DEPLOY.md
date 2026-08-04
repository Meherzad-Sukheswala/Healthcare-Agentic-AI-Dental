# Deploying this as a real, shareable website

## How API keys actually work here (read this first)

No platform can "reach into your laptop" to fetch a secret when someone visits your
site — your laptop isn't part of the request path at all once something is deployed.
The real pattern is simpler than that:

- Your real key never goes into any file that gets committed to Git. `.gitignore`
  already blocks `.env`, `.env.*`, `*.key` and `*.pem` from ever being committed (with
  `.env.example` explicitly allowed through, since it holds no values) — check with
  `git status` before your first commit if you're ever unsure.
- If you want a *live* AI-backed deployment, the key is typed once into your
  hosting platform's **Environment Variables** panel (encrypted at rest by them,
  injected into the running server process, never visible in your repo or to
  anyone browsing your GitHub).
- **You don't need a key at all for the version you're about to share.** This app
  already runs a fully deterministic **offline sandbox model** by default — real
  code systems (CDT, ICD-10, NPI), realistic dental scenarios, zero network calls,
  zero cost, zero key-leak surface. That's what `render.yaml` and the `Dockerfile`
  in this folder deploy by default. See `docs/external-systems-sandbox.md` for
  what "sandbox" means here.
- A public link with a *live* paid API key behind it means anyone with the URL can
  spend your API quota. Keep the public share link on sandbox mode; only flip a
  private/internal deployment to live mode if you specifically want that.

## Step 0 — decide the licence before you make the repo public

There is deliberately **no `LICENSE` file** in this folder. Adding one is a business
decision, not a technical one, and it isn't mine to pick: with no licence file a public
repo is "all rights reserved" by default, which may be exactly what you want if this is
company work. If you want others to be able to use it, MIT is the usual permissive
choice. Either way, decide before flipping the repo to public — and if this is
company-owned work, check who is meant to hold the copyright line.

Same question for the repo itself: **private** is the safer default while you're still
showing it to prospects. A Render deploy works fine from a private repo.

## Step 1 — push this folder to GitHub

```bash
git init
git add .
git status
```

Before committing, check that `git status` shows **no `.env`**, no `venv/`, and no
`data/synthea/output/`. All three are covered by `.gitignore` — but it's worth one look,
because a secret removed in a later commit is still in the history.

There **is** a local `.env` in this folder. As shipped it holds only non-secret sandbox
settings (`LLM_PROVIDER=sandbox`, `EHR_MODE=sandbox`, log levels) so nothing sensitive is
at risk today — but it is the file a real API key would go into, so keep it ignored and
never `git add -f` it.

```bash
git commit -m "Healthcare Agentic AI — dental practice demo"
```

Then create an empty repo on GitHub (github.com/new, or `gh repo create`) and push:

```bash
git remote add origin https://github.com/<your-username>/healthcare-agentic-ai-dental.git
git branch -M main
git push -u origin main
```

Once pushed, GitHub Actions runs `.github/workflows/ci.yml` automatically: the full
195-test suite on Python 3.11 and 3.12, plus a Docker build that boots the container and
checks `/health` and the demo page actually respond. No secrets or setup needed — the
suite is fully offline. Watch it under the repo's **Actions** tab; a green check there is
your signal the deploy in Step 2 will work.

## Step 2 — deploy it as a live website (Render.com, free tier)

1. Go to [render.com](https://render.com) and sign in with GitHub.
2. **New → Web Service** → pick this repo.
3. Render will auto-detect `render.yaml` in this folder and pre-fill everything
   (build command, start command, and `LLM_PROVIDER=sandbox`). Click **Create Web
   Service** — no other setup needed.
4. First deploy takes a few minutes. You'll get a URL like
   `https://healthcare-agentic-ai-dental.onrender.com` — that's your shareable link.

Free-tier note: Render's free web services sleep after ~15 min of no traffic and
take ~30-60s to wake back up on the next visit. Fine for sharing a portfolio demo;
upgrade to a paid instance if you want it always-warm.

### Alternatives
Anything that can run a Docker container or a Python web service works — the
`Dockerfile` in this folder is portable to **Railway**, **Fly.io**, or similar.
GitHub Pages will **not** work on its own — this is a live FastAPI backend, not a
static site.

## Step 3 (optional, and only if you want live AI responses)

Only do this for a deployment you don't mind other people using your API quota on
— e.g. a private Render service, not the link you hand out publicly.

1. Get a free Gemini key from [aistudio.google.com](https://aistudio.google.com/apikey)
   (or a Groq key from [console.groq.com](https://console.groq.com/keys)).
2. In Render: your service → **Environment** tab → **Add Environment Variable**.
   Add `GEMINI_API_KEY` = *(your key)*, and change `LLM_PROVIDER` from `sandbox`
   to `gemini`. Save — Render redeploys automatically.
3. That's the entire mechanism. The key lives only in Render's encrypted
   environment-variable store; it is never in `render.yaml`, never in a commit,
   never visible to anyone who clones or browses the repo.

## Running it locally first (recommended before deploying)

```bash
python -m venv venv
# Windows:
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
python -m pytest -q          # should show 195 passed
uvicorn src.api.app:app --reload --port 8000
```

Then open http://localhost:8000/.

## One thing to know before a live demo: the web font

The UI loads **Jost** from Google Fonts to match the brand typography. It uses
`display=swap`, so with no internet the page still renders immediately in the system
sans — nothing breaks, no invisible text — but the type won't be brand-exact.

If you're demoing somewhere the wifi might be unreliable and the visual match matters,
self-host it instead: download the Jost web font, drop the `.woff2` files in `web/fonts/`,
replace the `<link>` tags in `web/index.html` with an `@font-face` block, and the demo is
fully offline again. Say the word and I'll wire that up.
