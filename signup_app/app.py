"""Streamlit signup app with ranked position preferences and email offers."""

import argparse
import hmac
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import streamlit as st

from signup_app.store import (
    POSITION_CAPACITIES,
    JsonSignupStore,
    normalize_email,
)


ROOT = Path(__file__).resolve().parents[1]
ROSTER_POSITIONS = (
    ('setter', 'Setters', '👐'),
    ('middle', 'Middles', '🙌'),
    ('outside', 'Outsides', '🤚'),
    ('opposite', 'Oppos', '✋'),
    ('libero', 'Libs', '👊'),
)


def setting(name, default=''):
    """Read an app setting from Streamlit secrets, then the environment."""
    try:
        value = st.secrets.get(name)
    except (FileNotFoundError, KeyError):
        value = None
    return value or os.environ.get(name, default)


def send_offer_email(
    sender,
    app_password,
    recipient,
    event_title,
    event_date,
    position,
    accept_url,
    reject_url,
):
    """Send an offer with one-time accept and reject links using Gmail SMTP."""
    if not sender or not app_password:
        raise RuntimeError(
            'Configure GMAIL_ADDRESS and GMAIL_APP_PASSWORD to send waitlist offers.'
        )
    message = EmailMessage()
    message['Subject'] = (
        f'{position.title()} position available: {event_title}'
    )
    message['From'] = sender
    message['To'] = recipient
    message.set_content(
        f'A {position.title()} position is available for {event_title} '
        f'({event_date}).\n\n'
        f'Accept: {accept_url}\n'
        f'Reject: {reject_url}\n\n'
        'These links can only be used once.'
    )
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as smtp:
        smtp.login(sender, app_password.replace(' ', ''))
        smtp.send_message(message)


def deliver_unsent_offers(store, event_id, sender, gmail_password, app_url):
    """Send any queued offer emails for one event and report SMTP failures."""
    try:
        event, _ = store.event_status(event_id)
        event_start = datetime.fromisoformat(event['starts_at']).astimezone(timezone.utc)
        event_end = datetime.fromisoformat(event['ends_at']).astimezone(timezone.utc)
        event_date = (
            f'{event_start:%A %d %B %Y, %H:%M}–'
            f'{event_end:%H:%M} UTC'
        )
        offers = store.create_offer_links(event_id)
        for offer in offers:
            accept_url = (
                f'{app_url}?offer={offer["token"]}&action=accept'
            )
            reject_url = (
                f'{app_url}?offer={offer["token"]}&action=reject'
            )
            send_offer_email(
                sender,
                gmail_password,
                offer['email'],
                event['title'],
                event_date,
                offer['position'],
                accept_url,
                reject_url,
            )
            store.mark_offer_sent(offer['offer_id'])
    except (OSError, smtplib.SMTPException, RuntimeError) as error:
        st.error(f'Could not send a waitlist offer email: {error}')


def process_offer_link(store, app_url, sender, gmail_password):
    """Apply a clicked email action before rendering the regular sign-in view."""
    token = st.query_params.get('offer')
    action = st.query_params.get('action')
    if not token or action not in ('accept', 'reject'):
        return False
    try:
        result = store.respond_to_offer(token, accept=action == 'accept')
    except ValueError as error:
        st.error(str(error))
    else:
        if result['expired']:
            st.error('This offer expired because the event has already started.')
        elif result['accepted']:
            st.success(f'You accepted the {result["position"]} position.')
        else:
            st.info(f'You declined the {result["position"]} position.')
        if result['new_offers']:
            deliver_unsent_offers(
                store,
                result['event_id'],
                sender,
                gmail_password,
                app_url,
            )
    st.query_params.clear()
    return True


def verify_shared_password(supplied, configured):
    """Compare the supplied shared password without timing-sensitive equality."""
    return bool(configured) and hmac.compare_digest(supplied, configured)


def signup_roster_lines(entries):
    """Format current assignments and waitlist entries like the event viewer."""
    first_name_counts = {}
    for entry in entries:
        first_name = entry['name'].split()[0] if entry['name'].split() else 'Unknown'
        first_name_counts[first_name] = first_name_counts.get(first_name, 0) + 1
    seen_first_names = {}

    def display_name(full_name):
        first_name = full_name.split()[0] if full_name.split() else 'Unknown'
        seen_first_names[first_name] = seen_first_names.get(first_name, 0) + 1
        if first_name_counts[first_name] > 1:
            return f'{first_name} #{seen_first_names[first_name]}'
        return first_name

    lines = ['**Current signups:**']
    for position, label, emoji in ROSTER_POSITIONS:
        lines.append(f'**{label}: {emoji}**')
        assigned = [
            entry for entry in entries
            if entry['status'] in ('assigned', 'offered')
            and entry['position'] == position
        ]
        for index, entry in enumerate(assigned, start=1):
            rank = entry['preferences'].get(position)
            rank_text = f'(rank {rank})' if rank is not None else '(no preference)'
            pending_text = ' — offer pending' if entry['status'] == 'offered' else ''
            lines.append(
                f'{index}. {display_name(entry["name"])} {rank_text}{pending_text}'
            )

    waiting = [
        entry for entry in entries
        if entry['status'] == 'waitlisted'
    ]
    if waiting:
        lines.append('**📝 Waitlist:**')
        for entry in waiting:
            name = display_name(entry['name'])
            preferences = ', '.join(
                position.title()
                for position, _ in sorted(
                    entry['preferences'].items(),
                    key=lambda item: item[1],
                )
            )
            lines.append(f'{name} — {preferences}' if preferences else name)
    return lines


def render_signup_roster(entries):
    """Render the current signup roster grouped by assigned position."""
    for line in signup_roster_lines(entries):
        st.markdown(line)


def sign_in(store, shared_password):
    """Render registration and returning-user sign-in forms."""
    st.subheader('Sign in')
    register_tab, login_tab = st.tabs(['First sign in', 'Returning sign in'])
    with register_tab:
        with st.form('register'):
            new_name = st.text_input('Name', key='register_name')
            new_email = st.text_input('Email', key='register_email')
            new_password = st.text_input(
                'Shared app password',
                type='password',
                key='register_password',
            )
            register = st.form_submit_button('Save name and email')
        if register:
            if not verify_shared_password(new_password, shared_password):
                st.error('Incorrect app password.')
            else:
                try:
                    email = store.add_user(new_name, new_email)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.session_state['signup_user_email'] = email
                    st.rerun()

    with login_tab:
        with st.form('login'):
            name = st.text_input('Name', key='login_name')
            email = st.text_input('Email', key='login_email')
            password = st.text_input(
                'Shared app password',
                type='password',
                key='login_password',
            )
            login = st.form_submit_button('Sign in')
        if login:
            if not verify_shared_password(password, shared_password):
                st.error('Incorrect app password.')
            else:
                user = store.authenticate(name, email)
                if user is None:
                    st.error('The name and email do not match a registered account.')
                else:
                    st.session_state['signup_user_email'] = normalize_email(email)
                    st.rerun()


def render_event_signup(
    store,
    event,
    user_email,
    sender,
    gmail_password,
    app_url,
    simulate_email,
):
    """Render a user's current status and preference form for one event."""
    start = datetime.fromisoformat(event['starts_at']).astimezone(timezone.utc)
    end = datetime.fromisoformat(event['ends_at']).astimezone(timezone.utc)
    st.subheader(event['title'])
    st.caption(f'{start:%A %d %B %Y} · {start:%H:%M}–{end:%H:%M} UTC')

    _, entries = store.event_status(event['id'])
    render_signup_roster(entries)
    current = next(
        (entry for entry in entries if entry['email'] == user_email),
        None,
    )
    if current:
        if current['status'] == 'assigned':
            st.success(f'You are signed up as {current["position"].title()}.')
        elif current['status'] == 'offered':
            if simulate_email:
                st.info(
                    f'Simulated email: a {current["position"].title()} position '
                    'is available. Choose how to respond.'
                )
                offer = store.pending_offer(event['id'], user_email)
                if offer is not None:
                    accept_column, reject_column = st.columns(2)
                    with accept_column:
                        if st.button(
                            'Accept simulated offer',
                            key=f'accept:{offer["id"]}',
                        ):
                            respond_to_simulated_offer(
                                store,
                                offer['id'],
                                user_email,
                                True,
                            )
                    with reject_column:
                        if st.button(
                            'Reject simulated offer',
                            key=f'reject:{offer["id"]}',
                        ):
                            respond_to_simulated_offer(
                                store,
                                offer['id'],
                                user_email,
                                False,
                            )
            else:
                st.info(
                    f'An offer for {current["position"].title()} is pending. '
                    'Use the accept or reject link in your email.'
                )
        else:
            preferred = ', '.join(
                position.title()
                for position, _ in sorted(
                    current['preferences'].items(),
                    key=lambda item: item[1],
                )
            )
            st.warning(f'You are on the waiting list for: {preferred}.')

    with st.form(f'preferences:{event["id"]}:{user_email}'):
        st.write(
            'Choose a unique rank from 1 to 5 for each position you want. '
            'Leave a position unranked if you do not want to be offered it.'
        )
        preferences = {}
        for position in POSITION_CAPACITIES:
            selected = st.selectbox(
                position.title(),
                options=(0, 1, 2, 3, 4, 5),
                index=(
                    current['preferences'].get(position, 0)
                    if current else 0
                ),
                format_func=lambda rank: 'Not offered' if rank == 0 else str(rank),
                key=f'rank:{event["id"]}:{user_email}:{position}',
            )
            if selected:
                preferences[position] = selected
        save = st.form_submit_button(
            'Update positions' if current else 'Sign up'
        )
    if save:
        try:
            result = store.signup(event['id'], user_email, preferences)
        except ValueError as error:
            st.error(str(error))
        else:
            if result['status'] == 'assigned':
                st.success(
                    f'Saved. You are signed up as {result["position"].title()}.'
                )
            else:
                st.info('Saved. You are on the waiting list for your ranked positions.')
            if not simulate_email:
                deliver_unsent_offers(
                    store, event['id'], sender, gmail_password, app_url
                )
            st.rerun()
    elif current and not simulate_email:
        deliver_unsent_offers(
            store, event['id'], sender, gmail_password, app_url
        )


def respond_to_simulated_offer(store, offer_id, user_email, accept):
    """Apply a simulated offer response for the signed-in user."""
    try:
        result = store.respond_to_offer_as_user(offer_id, user_email, accept)
    except ValueError as error:
        st.error(str(error))
        return
    if result['expired']:
        notice = (
            'error',
            'This offer expired because the event has already started.',
        )
    elif result['accepted']:
        notice = (
            'success',
            f'You accepted the {result["position"].title()} position.',
        )
    else:
        notice = (
            'info',
            f'You declined the {result["position"].title()} position.',
        )
    st.session_state['simulated_offer_notice'] = notice
    st.rerun()


def main(nomail=False):
    """Run the signup and returning-user app."""
    st.set_page_config(page_title='VolleyApp Signups', page_icon='🏐')
    st.title('VolleyApp Signups 🏐')
    shared_password = (
        setting('SIGNUP_APP_PASSWORD')
        or setting('app_password')
    )
    if not shared_password:
        st.error(
            'Configure app_password in Streamlit secrets or '
            'SIGNUP_APP_PASSWORD in secrets or the environment.'
        )
        return

    data_path = setting(
        'SIGNUP_DATA_FILE',
        str(ROOT / 'signup_app' / 'signups.json'),
    )
    try:
        store = JsonSignupStore(data_path)
    except RuntimeError as error:
        st.error(str(error))
        return

    sender = None
    gmail_password = None
    app_url = 'http://localhost:8501'
    if not nomail:
        sender = setting('GMAIL_ADDRESS')
        gmail_password = setting('GMAIL_APP_PASSWORD')
        app_url = setting('SIGNUP_APP_URL', app_url).rstrip('/')
        if process_offer_link(store, app_url, sender, gmail_password):
            return

    if not st.session_state.get('signup_user_email'):
        sign_in(store, shared_password)
        return

    if nomail:
        simulate_email = True
        st.caption(
            '--nomail is enabled. No email settings are read and no email '
            'will be sent; offers appear here with simulated accept/reject controls.'
        )
    else:
        email_delivery = st.radio(
            'Email delivery',
            ('Simulate emails', 'Send with Gmail'),
            horizontal=True,
            key='email_delivery_mode',
        )
        simulate_email = email_delivery == 'Simulate emails'
    if simulate_email and not nomail:
        st.caption(
            'Simulation mode is on. No email will be sent; waitlist offers '
            'appear here with simulated accept/reject controls.'
        )
    elif not nomail and (not sender or not gmail_password):
        st.warning(
            'Configure GMAIL_ADDRESS and GMAIL_APP_PASSWORD to send real emails.'
        )
    notice = st.session_state.pop('simulated_offer_notice', None)
    if notice:
        getattr(st, notice[0])(notice[1])

    user_email = st.session_state['signup_user_email']
    left, right = st.columns([5, 1])
    with left:
        st.caption(f'Signed in as {user_email}')
    with right:
        if st.button('Sign out'):
            del st.session_state['signup_user_email']
            st.rerun()

    events = store.events()
    if not events:
        st.info('There are no future events available for signup.')
        return

    for event in events:
        with st.expander(event['title'], expanded=True):
            render_event_signup(
                store,
                event,
                user_email,
                sender,
                gmail_password,
                app_url,
                simulate_email,
            )


def parse_args(argv=None):
    """Parse signup app options while allowing Streamlit's own CLI arguments."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        '--nomail',
        action='store_true',
        help='Disable email settings and simulate waitlist offers in the app.',
    )
    args, _ = parser.parse_known_args(argv)
    return args


if __name__ == '__main__':
    main(nomail=parse_args(sys.argv[1:]).nomail)
