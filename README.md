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
.venv\Scripts\streamlit run app.py
```

Create an account on the sign-in page. Each account has its own sports, teams/drivers,
timezone and saved Ask conversations; nobody else using the app can see them. A user's
first visit runs a short setup; change it any time under **Settings**.

Public data (fixtures, team lists, news articles) is shared, so it's fetched once for
everyone. Passwords are hashed with scrypt. You'll need to sign in again after refreshing
the page, because Streamlit can't keep its own login cookie.

Upgrading from the single-user version: the **first account created** takes over the
existing setup.

## API keys

| Key | Needed for | Where |
|---|---|---|
| football-data.org | Football teams and fixtures | free at football-data.org/client/register |
| Gemini | Written answers on Ask, "Catch me up" briefings | free at aistudio.google.com/apikey |

Each user adds their own keys under **API keys** in the sidebar. Keys are checked with the
service before they're saved, stay private to that account, and are only ever shown masked
(last 4 characters). Keys in `.env` (`FOOTBALL_DATA_API_KEY`, `GEMINI_API_KEY`) are an
optional shared fallback for users who haven't added their own. Keys are stored unencrypted
in the local database, like `.env`, so keep `data/` private.

F1 and news need no key. Without the football key you can still pick competitions, but
the app will ask for the key before it can show matches. Without the Gemini key, Ask
shows the best-matching articles instead of a written answer.

The Gemini app subscription doesn't include API access; the free AI Studio key is separate.
Each question makes exactly one Gemini call. If you hit the free daily limit, set
`GEMINI_MODEL=gemini-flash-lite-latest` in `.env`.

## How it works

- `src/sports_info/providers/`: one adapter per data source behind the `SportProvider`
  interface (football-data.org for football, Jolpica for F1).
- `src/sports_info/auth.py`: local accounts (scrypt password hashes).
- `src/sports_info/store/`: SQLite via SQLModel. Per-user tables (`user`, `userprofile`,
  `follow`, `conversation`, `chatmessage`) are always queried by `user_id`; shared tables
  hold the cached wizard options, matches/races, and news articles with their embeddings.
- `src/sports_info/services/`: refreshes fixtures when stale and picks the events relevant to you.
- `src/sports_info/news/`: reads RSS feeds (BBC, Guardian, Sky, ESPN, Autosport, Motorsport.com,
  plus a Google News search per followed team/driver), extracts full article text where
  allowed, tags the teams/drivers mentioned, splits into passages and embeds them locally
  (`bge-small-en`, ~70 MB downloaded on first run).
- `src/sports_info/rag/`: answers a question in one LLM call:
  1. find the teams/drivers it mentions (or carry them over from the previous question);
  2. hybrid search over the last two weeks of news: embedding similarity + SQLite FTS5
     keywords, merged with reciprocal rank fusion and boosted for those entities;
  3. add upcoming fixtures and recent results from the database as authoritative context;
  4. Gemini answers using only that context and cites articles as [1], [2].
- `src/sports_info/ui/`: Streamlit pages (setup, Home, Fixtures & results, News, Ask, Settings).

Fixtures refresh every 6 hours and news every hour, when you open a page; **Refresh data**
in the sidebar forces both. The first news fetch takes about a minute.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

See [PLAN.md](PLAN.md) for the roadmap.
