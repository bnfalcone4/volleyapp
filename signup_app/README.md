# Volleyball signups

This is a standalone Streamlit app. It has no connection to Spond and does not
read or write the Spond cache. It stores account names/emails, events, signups,
and waitlist offers in a local JSON file at `signup_app/signups.json`; Git
ignores that file. On first run, it creates a test event for Tuesday, November
10, 2026, from 10:00 to 12:00 UTC.

Run from the repository root:

```bash
streamlit run signup_app/app.py -- --nomail
```

The app uses `app_password` from `.streamlit/secrets.toml` by default, so it
shares the existing app password. You can override it with
`SIGNUP_APP_PASSWORD` in secrets or the environment:

```toml
SIGNUP_APP_PASSWORD = "shared-password-for-players"
```

The `--nomail` option disables all email handling and does not read Gmail
settings. Pending waitlist offers appear to the offered player after they sign
in, with simulated accept/reject controls. To test the flow, register multiple
players with different email addresses, fill a position, and edit an assigned
player's preferences to free a spot. Sign in as the next waitlisted player to
see and respond to the simulated offer.

To allow real email as an option, omit the flag:

```bash
streamlit run signup_app/app.py
```

In that mode, email simulation is still the default, but **Send with Gmail**
becomes available.

To opt into real email delivery, select **Send with Gmail** and configure
these additional settings:

```toml
SIGNUP_APP_URL = "https://your-public-app.example"
GMAIL_ADDRESS = "your-account@gmail.com"
GMAIL_APP_PASSWORD = "your-16-character-google-app-password"
```

Use a Google App Password for SMTP, not the normal Gmail password. Google
requires two-step verification to create an App Password. The public app URL
is used for the one-time accept/reject links.

Players first register a name and email with the shared app password. On later
visits, they sign in with that same name/email pair and the shared password.
Position ranks must be unique; an unranked position is never offered.
`SIGNUP_DATA_FILE` can override the JSON database path. The file format is
versioned so the JSON storage can later be migrated to SQL.
