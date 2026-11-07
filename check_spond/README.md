# Spond volleyball app

Install the project dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

Edit the repository-root `.env` file with your Spond username, password, and
group ID. The local launcher loads these values automatically:

```bash
python check_spond/app.py
```

This fetches event and attendee data from Spond and saves it to
`check_spond/upcoming_events.json`. The Streamlit app also saves fetched data
to that file. To run either local mode using the saved data without accessing
Spond, pass `--from-json`:

```bash
python check_spond/app.py --from-json
streamlit run check_spond/app.py -- --from-json
```

The offline Streamlit mode still uses the app password, but does not require
Spond credentials. Select the event you want from the event picker.

Edit `.streamlit/secrets.toml` to set a separate app password and Spond
credentials before running Streamlit:

```toml
app_password = "choose-a-separate-app-password"

[spond]
username = "your-spond-username"
password = "your-spond-password"
group_id = "your-spond-group-id"
```

The app requires the app password to view data. In live mode, it fetches events
after login, saves the full event data to `upcoming_events.json`, and keeps
event details and preference dictionaries in the app session so reruns do not
fetch them again. If loading fails, reload the app to retry. Each event displays
separate Ranked, Flexible, and Optimized assignment results. Flexible and
Optimized use the matching player-count row in the repository-root
`min_positions.csv`; the local terminal mode prints all three results. For each
player, submitted preference scores are sorted and renumbered consecutively
from 1; positions without a score remain blank.
Use **Edit attendance** to check or uncheck players; the first 21 players start
checked and players beyond the event capacity (initially waiting) start
unchecked. Each checkbox change immediately recalculates all assignment lists.
In the Streamlit app, **List visualization** defaults to **Positions** and can
be switched to **Order** to show assignments in signup order. The **Show
cascade** option displays Ranked-mode players' blocked preferences when those
positions have a better rank than their assigned position.
