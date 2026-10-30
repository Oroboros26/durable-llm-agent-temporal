# Kill-the-worker demo (storyboard)

No GIF is committed: nothing has been run. Record one with `asciinema`/`vhs` following this script, save it as `docs/resume.gif`, then reference it in the README.

Use 3 terminals (`TOOL_DELAY_S=3 FAKE_LLM=1` makes the window easy to hit):

| # | Terminal | Command | What the viewer sees |
|---|---|---|---|
| 1 | server | `docker compose up` | Temporal UI at http://localhost:8080 |
| 2 | worker | `make worker` | "worker started" |
| 3 | client | `python -m durable_agent.client start demo "revenue report"` | workflow id `demo` |
| 3 | client | `python -m durable_agent.client status demo` | `{step: 4, pending_key: 'demo:4:0'}` |
| 3 | client | `python -m durable_agent.client approve demo demo:4:0` | email step starts |
| 2 | worker | **Ctrl+C or `kill -9`** while the email step runs | worker dies |
| UI | browser | open workflow `demo` | history intact, last activity "scheduled" |
| 2 | worker | `make worker` | worker resumes |
| UI | browser | refresh | `send_email` completes, workflow Completed |
| 3 | client | `sqlite3 data/agent.db "select count(*) from outbox"` | `1` |
