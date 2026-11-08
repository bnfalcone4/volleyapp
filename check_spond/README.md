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
`check_spond/upcoming_events.json`. The cache retains attendee surnames but
omits phone numbers, email addresses, dates of birth, and image URLs. The
Streamlit app also saves fetched data to that file. To run either local mode
using the saved data without accessing Spond, pass `--from-json`:

```bash
python check_spond/app.py --from-json
streamlit run check_spond/app.py -- --from-json
```

The offline Streamlit mode still uses the app password, but does not require
Spond credentials. Select the event you want from the event picker.
Events are ordered with today's and future events first in ascending UTC date
and time, followed by past events with the most recent first.

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
separate Ranked, Strict, Flexible, and Optimized assignment results. Strict
assigns players in signup order only to their rank-1 position. If that position
is full or reserved, the player is waitlisted and a remaining slot in each
other position is reserved for them. Flexible and Optimized use the
`min_positions.csv` row for the number of checked players up to the selected
Player cap as their initial minimums. The **Adjust position limits** controls
appear in each mode's tab, and Flexible and Optimized keep independent limits.
The controls keep each limit
within the selected player count, prevent minimums from exceeding maximums,
and ensure the totals can accommodate all selected players.
Changing the active player count (checked players up to the cap, excluding the
waitlist) reloads the defaults for that count. Counts above the largest
`total` in `min_positions.csv` use the minimums from that largest row. Position
maximums are calculated as `ceil(active players / 6)` times the position
factor: setter 1, outside 3, middle 2, opposite 1, and libero 1; each maximum
is capped at the active-player count. Limits are shown compactly, one position
per row.
The local terminal mode prints all four results. For each player,
submitted preference scores are sorted and renumbered consecutively from 1;
positions without a score remain blank.
Use **Edit attendance** to check or uncheck players; the first 21 players start
checked and players beyond the event capacity (initially waiting) start
unchecked. Each checkbox change immediately updates the attending and waiting
list counts; when players are unchecked, **Absent** shows their count. It also
recalculates all assignment lists.
In the Streamlit app, **List visualization** defaults to **Positions** and can
be switched to **Order** to show assignments in signup order. The **Show
cascade** option displays players' blocked preferences when those positions
have a better rank than their assigned position. **Player cap**
defaults to Spond's maximum number of participants (`maxAccepted`), saved with
each event in `upcoming_events.json`; older cache entries without this field
default to 21. The cap has no signup-count maximum and can be increased as
needed; assignments recalculate with players beyond the cap moved to the
waitlist.
