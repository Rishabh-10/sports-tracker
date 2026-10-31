# Sports Info

A personal sports app for the teams, drivers and competitions you follow: upcoming
matches and races, recent results, a news feed, and an **Ask** page where Gemini answers
questions grounded in the latest news and fixtures (RAG). Built with Streamlit; all data
comes from free sources.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env      # then add your keys (see below)
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # then set up Google sign-in (below)
.venv\Scripts\streamlit run app.py
```

Sign in with Google. Each account has its own sports, teams/drivers, timezone and saved
Ask conversations; nobody else using the app can see them. A user's first visit runs a
short setup; change it any time under **Settings**. Sign-ins last 30 days (Streamlit's
login cookie), so refreshing the page or opening a new tab keeps you signed in.

Public data (fixtures, team lists, news articles) is shared, so it's fetched once for
everyone.

Upgrading from the single-user version: the **first account to sign in** takes over the
existing setup. Upgrading from the username/password version: its database can't be
reused, and the app says so. Delete `data/sports_info.db` and fixtures and news are fetched
again; each user signs in with Google and runs setup again.

## Google sign-in

Sign-in uses Streamlit's built-in `st.login()` with Google. Accounts are keyed by Google's
permanent account ID, so the same Google account always gets the same data.

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), go to
   **APIs & Services → Credentials → Create credentials → OAuth client ID** and choose
   **Web application**. (If asked, configure the consent screen first; "External" with
   yourself as a test user is enough to start.)
2. Under **Authorized redirect URIs**, add `http://localhost:8501/oauth2callback`, plus
   `https://<your-app>.streamlit.app/oauth2callback` if you deploy. One client can serve
   several apps.
3. In `.streamlit/secrets.toml`, fill in the `[auth]` section: client ID, client secret
   and a random `cookie_secret`.

## Database

Locally the app uses SQLite at `data/sports_info.db`. Set `DATABASE_URL` (in
`.streamlit/secrets.toml` or `.env`) to use Postgres instead; tables and the keyword index
are created on first start. Keyword search uses SQLite FTS5 or Postgres full-text search
(an indexed `tsvector` column), both accent-insensitive, so "Perez" finds "Pérez".

## Deploying to Streamlit Community Cloud

Community Cloud wipes the app's disk whenever it restarts, redeploys or sleeps, so a SQLite
file there loses every account. Use a hosted Postgres instead:

1. Create a free project at [Neon](https://neon.tech) and copy its connection string.
2. Add `https://<your-app>.streamlit.app/oauth2callback` to the Google OAuth client's
   redirect URIs.
3. In the app's **Settings → Secrets**, paste `.streamlit/secrets.toml.example` with your
   values: `DATABASE_URL`, `KEYS_ENCRYPTION_KEY`, and the `[auth]` section with
   `redirect_uri` set to the `streamlit.app` URL above.
4. Reboot the app and sign in once to check it works.

## API keys

| Key | Needed for | Where |
|---|---|---|
| football-data.org | Football teams and fixtures | free at football-data.org/client/register |
| Gemini | Written answers on Ask, "Catch me up" briefings | free at aistudio.google.com/apikey |

Each user adds their own keys under **API keys** in the sidebar. Keys are checked with the
service before they're saved, stay private to that account, and are only ever shown masked
(last 4 characters). Keys in `.env` (`FOOTBALL_DATA_API_KEY`, `GEMINI_API_KEY`) are an
optional shared fallback for users who haven't added their own. When `KEYS_ENCRYPTION_KEY`
is set, saved keys are encrypted in the database; keep that secret stable, because changing
it means users have to add their keys again. Without it (fine for a local install) keys are
stored as plain text, so keep `data/` private. Plain-text keys saved before you set it keep
working and are encrypted the next time they're saved.

F1 and news need no key. Without the football key you can still pick competitions, but
the app will ask for the key before it can show matches. Without the Gemini key, Ask
shows the best-matching articles instead of a written answer.

The Gemini app subscription doesn't include API access; the free AI Studio key is separate.
Each question makes exactly one Gemini call. If you hit the free daily limit, set
`GEMINI_MODEL=gemini-flash-lite-latest` in `.env`.

## How it works

- `src/sports_info/providers/`: one adapter per data source behind the `SportProvider`
  interface (football-data.org for football, Jolpica for F1).
- `src/sports_info/auth.py`: maps a Google account (via `st.login`) to a local account.
- `src/sports_info/store/`: SQLModel over Postgres (`DATABASE_URL`) or SQLite. Per-user
  tables (`user`, `userprofile`, `follow`, `userapikeys`, `conversation`, `chatmessage`) are
  always queried by `user_id`; shared tables hold the cached wizard options, matches/races,
  and news articles with their embeddings.
- `src/sports_info/services/`: refreshes fixtures when stale and picks the events relevant to you.
- `src/sports_info/news/`: reads RSS feeds (BBC, Guardian, Sky, ESPN, Autosport, Motorsport.com,
  plus a Google News search per followed team/driver), extracts full article text where
  allowed, tags the teams/drivers mentioned, splits into passages and embeds them locally
  (`bge-small-en`, ~70 MB downloaded on first run).
- `src/sports_info/rag/`: answers a question in one LLM call:
  1. find the teams/drivers it mentions (or carry them over from the previous question);
  2. hybrid search over the last two weeks of news: embedding similarity + full-text
     keywords (SQLite FTS5 or Postgres `tsvector`), merged with reciprocal rank fusion
     and boosted for those entities;
  3. add upcoming fixtures and recent results from the database as authoritative context;
  4. Gemini answers using only that context and cites articles as [1], [2].
- `src/sports_info/ui/`: Streamlit pages (setup, Home, Fixtures & results, News, Ask, Settings).

Fixtures refresh every 6 hours and news every hour, when you open a page; **Refresh data**
in the sidebar forces both. The first news fetch takes about a minute.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

The suite uses throwaway SQLite files. To run it against Postgres too, point
`TEST_DATABASE_URL` at an empty database used only for tests (its tables are dropped after
each test):

```powershell
$env:TEST_DATABASE_URL = "postgresql://postgres:test@localhost:5432/sports_test"
.venv\Scripts\python -m pytest
```
