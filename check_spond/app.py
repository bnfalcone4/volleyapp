import asyncio
import hmac
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_fetch_module():
    fetch_path = Path(__file__).with_name('check_spond.py')
    spec = importlib.util.spec_from_file_location('_spond_fetch', fetch_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load Spond fetch logic from {fetch_path}.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_assignment_module():
    assignment_path = Path(__file__).resolve().parents[1] / 'spond.py'
    spec = importlib.util.spec_from_file_location(
        '_volley_assignment',
        assignment_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load assignment logic from {assignment_path}.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def first_name_label(full_name, counts, seen):
    first_name = full_name.split()[0] if full_name.split() else 'Unknown'
    seen[first_name] = seen.get(first_name, 0) + 1
    if counts[first_name] > 1:
        return f'{first_name} #{seen[first_name]}'
    return first_name


def display_event(event, assignment_module, streamlit=None):
    assignment, waiting = assignment_module.ranked_assignments(event['players'])
    start = datetime.fromisoformat(event['startTimestamp'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(event['endTimestamp'].replace('Z', '+00:00'))
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)

    counts = {}
    for full_name in event['players']:
        first_name = full_name.split()[0] if full_name.split() else 'Unknown'
        counts[first_name] = counts.get(first_name, 0) + 1
    seen = {}

    title = event.get('heading') or 'Untitled event'
    date_line = f'{start:%Y-%m-%d} · {start:%H:%M}–{end:%H:%M} UTC'
    if streamlit:
        streamlit.subheader(title)
        streamlit.caption(date_line)
        streamlit.markdown('**Assignments**')
        for index, (full_name, position) in enumerate(assignment.items(), start=1):
            first_name = first_name_label(full_name, counts, seen)
            rank = event['players'][full_name].get(position)
            rank_text = f' (rank {rank})' if rank is not None else ''
            streamlit.write(f'{index}. {first_name} — {position}{rank_text}')
        if waiting:
            streamlit.markdown('**Waiting list**')
            for full_name, preferences in waiting.items():
                first_name = first_name_label(full_name, counts, seen)
                streamlit.write(f'{first_name} — {", ".join(preferences)}')
        return

    print(f'\n{title}')
    print(date_line)
    for index, (full_name, position) in enumerate(assignment.items(), start=1):
        first_name = first_name_label(full_name, counts, seen)
        rank = event['players'][full_name].get(position)
        rank_text = f' (rank {rank})' if rank is not None else ''
        print(f'{index}. {first_name} - {position}{rank_text}')
    if waiting:
        print('Waiting list:')
        for full_name, preferences in waiting.items():
            first_name = first_name_label(full_name, counts, seen)
            print(f'{first_name} - {", ".join(preferences)}')


def local_main():
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    username = os.environ.get('SPOND_USERNAME')
    password = os.environ.get('SPOND_PASSWORD')
    group_id = os.environ.get('SPOND_GROUP_ID')
    if not username or not password or not group_id:
        raise SystemExit(
            'Set SPOND_USERNAME, SPOND_PASSWORD, and SPOND_GROUP_ID before running locally.'
        )

    fetch_module = load_fetch_module()
    events = asyncio.run(
        fetch_module.fetch_upcoming_events(username, password, group_id)
    )
    cache_path = fetch_module.save_event_cache(events, group_id)
    print(f'Saved live event data to {cache_path}.')
    if not events:
        print('No upcoming events with open sign-up were found.')
        return

    assignment_module = load_assignment_module()
    for event in events:
        display_event(event, assignment_module)


def streamlit_main():
    import streamlit as st

    fetch_module = load_fetch_module()
    st.set_page_config(page_title='VolleyApp', page_icon='🏐')
    st.title('Volleyball sign-ups')
    st.write('Fetch upcoming open events and assign positions from live Spond data.')

    try:
        configured = st.secrets
    except (FileNotFoundError, KeyError):
        configured = {}

    app_password = configured.get('app_password') or os.environ.get(
        'STREAMLIT_APP_PASSWORD'
    )
    if not app_password:
        st.error('Configure STREAMLIT_APP_PASSWORD before making this app available.')
        return

    if not st.session_state.get('authenticated'):
        with st.form('app_login'):
            supplied_password = st.text_input('App password', type='password')
            login_submitted = st.form_submit_button('Log in')
        if login_submitted:
            if hmac.compare_digest(supplied_password, app_password):
                st.session_state['authenticated'] = True
                st.rerun()
            st.error('Incorrect app password.')
        return

    spond_config = configured.get('spond', {})
    username = spond_config.get('username') or os.environ.get('SPOND_USERNAME')
    password = spond_config.get('password') or os.environ.get('SPOND_PASSWORD')
    group_id = spond_config.get('group_id') or os.environ.get('SPOND_GROUP_ID')
    if not username or not password or not group_id:
        st.error('Configure Spond credentials and group ID in Streamlit secrets.')
        return

    if st.button('Fetch live events'):
        try:
            events = asyncio.run(
                fetch_module.fetch_upcoming_events(username, password, group_id)
            )
        except (ImportError, OSError, ValueError, KeyError) as error:
            st.error(f'Could not load Spond events: {error}')
        else:
            st.session_state['events'] = [
                {
                    'id': event['id'],
                    'heading': event['heading'],
                    'startTimestamp': event['startTimestamp'],
                    'endTimestamp': event['endTimestamp'],
                    'players': event['players'],
                }
                for event in events
            ]

    events = st.session_state.get('events', [])
    if not events:
        st.info('Fetch live events to view upcoming open sign-ups.')
        return

    def event_label(event):
        start = datetime.fromisoformat(event['startTimestamp'].replace('Z', '+00:00'))
        return f"{event.get('heading') or 'Untitled event'} — {start:%Y-%m-%d %H:%M} UTC"

    selected_index = st.selectbox(
        'Event',
        range(len(events)),
        format_func=lambda index: event_label(events[index]),
    )
    assignment_module = load_assignment_module()
    display_event(events[selected_index], assignment_module, streamlit=st)


if __name__ == '__main__':
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        get_script_run_ctx = None

    if get_script_run_ctx is not None and get_script_run_ctx() is not None:
        streamlit_main()
    else:
        local_main()
