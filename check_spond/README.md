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

Run the Streamlit app:

```bash
streamlit run check_spond/app.py
```

Edit `.streamlit/secrets.toml` to set a separate app password and Spond
credentials before running Streamlit:

```toml
app_password = "choose-a-separate-app-password"

[spond]
username = "your-spond-username"
password = "your-spond-password"
group_id = "your-spond-group-id"
```

The app requires the app password to view data. It fetches live events when
**Fetch live events** is submitted and keeps only event details and preference
dictionaries in the app session. Each event displays separate Ranked, Flexible,
and Hungarian assignment results. Flexible and Hungarian use the matching
player-count row in the repository-root `min_positions.csv`; the local terminal
mode prints all three results and also saves fetched data to
`upcoming_events.json`.
