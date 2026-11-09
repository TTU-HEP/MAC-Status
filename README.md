Repository for viewing local database information within TTU APD Lab. 

**Database query tool**

The only requirement for using the database query tool `all_in_one.sh` is installation of the PostgresQL software, as described here: https://www.postgresql.org/download/

Once this is set up, can run the program with:

```
./all_in_one.sh
```

Tutorial for usage is linked here: https://eventreg.ads.ttu.edu/event/237/contributions/610/attachments/303/625/Database%20query%20tutorial-2.pdf

**Natural-language query agent**

`nl_query_agent.py` is MAC-BOT George, a read-only agent version of `all_in_one.sh`: ask questions in plain English and it translates them into validated SQL SELECT queries, runs them as the `viewer` user inside a READ ONLY transaction, prints the rows, and summarizes the answer. It cannot modify the database.

Setup (inside the venv described below, after installing dependencies):

```
export ANTHROPIC_API_KEY=sk-ant-...   # from https://console.anthropic.com
python3 nl_query_agent.py             # interactive
python3 nl_query_agent.py "which modules were assembled in October 2025?"   # one-shot
```

It uses the lightweight `claude-haiku-5-5` model by default (override with the `MAC_AGENT_MODEL` environment variable). The generated SQL is hidden by default; pass `--show-sql` (or set `MAC_AGENT_SHOW_SQL=1`) to echo each query, or just ask the agent "what query did you run?". Example questions: "latest 5 IV tests for TT modules", "how many hexaboards do we have per resolution?", "show inspection grades for 320MLF3WDTT0099".

Each answer ends with a token-usage line, and usage is capped: 100k tokens per query and 1M per session by default (`MAC_AGENT_QUERY_TOKEN_CAP` / `MAC_AGENT_SESSION_TOKEN_CAP`; a typical query is ~25k, nearly all cached schema reads). Results are capped at 500 rows, and printing anything over ~500 terminal lines first asks for confirmation (Enter to proceed, anything else to skip; suppressed automatically in non-interactive runs; tune with `MAC_AGENT_PRINT_LIMIT`). All output is human-readable: image columns (hexplots, offset plots, pedestal hexmaps) are saved as PNG files under `agent_plots/` and shown as file paths instead of raw bytes, long per-channel arrays are summarized as `[N values: min, max, mean]` with unusual values flagged as outliers (Tukey 1.5×IQR rule — flagged only, never diagnosed), and dates/floats are formatted cleanly. Ask e.g. "show me the hexplot for 320MLF2WDTT0035" to get the saved plot file. George can also sketch quick plots from the data itself (make_plot tool): "sketch the IV curve for 320MLF3WDTT0099", "histogram the noise of the latest pedestal test" — rendered as PNGs in agent_plots/ (line, scatter, bar, hist; arrays are unnested in SQL).

**Web chat UI**

`web_ui.py` serves MAC-BOT George as a chat web page (standard LLM layout) at http://localhost:8765, using your Claude Code login:

```
python3 web_ui.py
```

Result tables render inline (stored images and sketched plots are displayed large with row fields as small captions, outlier counts highlighted), SQL stays hidden unless the "show SQL" toggle is on, token usage shows under each reply, and four pastel themes (Lavender, Mint, Peach, Sky) are switchable in the header. Port via `MAC_AGENT_UI_PORT`.

**Summary plotting tools**

More dependencies are needed to make sure this runs. These are listed in `dependencies.txt`. A virtual environment is recommended for making this work.

```
python3 -m venv venv                      
source venv/bin/activate
python3 -m pip install -r dependencies.txt
```

Once dependencies are installed, then can run with:
```
python3 summary_plotter_interactive.py
```
Tutorial to be uploaded soon.
------------------------------------
More updates and tools TBA
