# MAC database Q&A website

A web page where lab members ask the TTU MAC database questions in plain English
and see the answer stream in live: each SQL query, its result table (plots
inline), then a short summary. It reuses `nl_query_agent.py` for all database
access, so it is read-only in the same ways: validated SELECT only, run as
`viewer` in a READ ONLY transaction.

- Sign-in: name + one shared lab password. Each name's token use is logged to
  `webapp/data/usage.jsonl` (time, name, question, tokens).
- Billing: an Anthropic API key, pay per use. A typical question is ~25k
  tokens, mostly cheap cached reads. Daily caps: 1M tokens per user, 5M for the
  whole site (configurable).
- Look: matches the repo's `web_ui.html` (MAC-BOT Dobby): four pastel themes,
  a "show SQL" toggle, short answers with "see more", stored images shown large.
  It also keeps the quick links (lab RH/T, MMTS T, production summary), which run
  fixed read-only queries and use no model tokens.
- Charts: the agent can draw bar, line, scatter, histogram and box charts
  (`webapp/plotting.py`). It sends a declarative spec (a read-only SELECT plus
  which columns go where), never code; the server draws it with matplotlib.
  Chart PNGs live in `webapp/data/charts/` and are deleted after 30 days.
- Conversations keep context for follow-ups (last 8 questions, forgotten after
  3 h idle or on "New conversation").

## Running it

Settings live in `~/.config/macdb-web/env` (private, outside the repo): the
API key, the lab password, the caps. The app runs as a systemd user service:

    systemctl --user restart macdb-web     # after editing the env file
    systemctl --user status macdb-web
    journalctl --user -u macdb-web -f      # logs

It listens on 127.0.0.1:8510 only. To preview it yourself from VS Code, forward
port 8510 (Ports tab) and open http://localhost:8510/.

## Making it reachable on campus (needs root, one time)

    sudo cp webapp/deploy/nginx-macdb.conf /etc/nginx/default.d/macdb.conf
    sudo setsebool -P httpd_can_network_connect 1   # let nginx reach the app (SELinux)
    sudo nginx -t && sudo systemctl reload nginx

Then the site is at http://10.130.165.10/macdb/ (port 80 must be open to the
campus network in firewalld).
