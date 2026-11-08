"""Fetch, cache, and inspect upcoming Spond volleyball events.

The module can read live events from Spond or load cached/saved event data.
It normalizes attendee preference fields for use by the assignment module.
"""

import argparse
import ast
import asyncio
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

POSITION_FIELD_IDS = {
    '2B2750AA5F65467A99E3E83B93153E00': 'setter',
    '57D2266300294609BA90B85C5F0E3E89': 'middle',
    '6985006C9EDE499F9219136BF17A49BA': 'opposite',
    '74806AEFD38C450A99707C92BF5CD0A3': 'outside',
    '7B62F5178AF94D089AC7C5AA07E66F73': 'libero',
}

IDENTIFIER_MEANINGS = {
    'groupId': 'Opaque Spond identifier for the group queried by this script.',
    'events[].id': 'Opaque Spond identifier for the event.',
    'events[].people[].id': (
        'Spond member or guardian record identifier. get_person() accepts this ID.'
    ),
    'events[].people[].clubMembershipId': (
        'Spond-provided opaque club-membership-related identifier; '
        'get_person() does not resolve it as a member/profile ID.'
    ),
    'events[].people[].profile.id': (
        'Spond profile identifier. It can differ from the member record ID, '
        'including for child profiles; get_person() accepts it.'
    ),
    'events[].people[].guardians[].id': (
        'Spond member or guardian record identifier. get_person() accepts this ID.'
    ),
    'events[].people[].guardians[].profile.id': (
        'Spond profile identifier. It can differ from the member record ID; '
        'get_person() accepts it.'
    ),
    'events[].people[].fields': (
        'Player preference ranks keyed by the IDs in positionFieldIds.'
    ),
}

#st.title('Volleyball Positions')

def accepted_people(event):
    """Return accepted group members for a Spond event.

    Args:
        event: Spond event mapping containing accepted response IDs and group
            member records.

    Returns:
        Member mappings whose IDs appear in the event's accepted response list.
    """
    accepted_ids = event.get('responses', {}).get('acceptedIds', [])
    members = event.get('recipients', {}).get('group', {}).get('members', [])
    members_by_id = {member.get('id'): member for member in members}
    return [members_by_id[user_id] for user_id in accepted_ids if user_id in members_by_id]


def print_event_details(event, people):
    """Print an event's UTC date/time and attendee first names.

    Args:
        event: Event mapping containing heading and ISO start/end timestamps.
        people: Iterable of attendee mappings.

    Returns:
        None. Writes event details to standard output.
    """
    start = datetime.fromisoformat(
        event['startTimestamp'].replace('Z', '+00:00')
    )
    end = datetime.fromisoformat(
        event['endTimestamp'].replace('Z', '+00:00')
    )
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    print(f"\n{event.get('heading', 'Untitled event')}")
    print(f"Date: {start:%Y-%m-%d} (UTC)")
    print(f"Time: {start:%H:%M}–{end:%H:%M} UTC")
    print('People attending:')
    for index, person in enumerate(people, start=1):
        print(f"{index}. {person.get('firstName') or 'Unknown'}")


def sanitize_cached_data(value):
    """Remove private contact, birth-date, and image fields from cached data."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = ''.join(
                character for character in key.casefold() if character.isalnum()
            )
            if (
                normalized_key in {
                    'email',
                    'emailaddress',
                    'emails',
                    'phone',
                    'phonenumber',
                    'phonenumbers',
                    'mobile',
                    'mobilenumber',
                    'mobilephone',
                    'telephone',
                    'dateofbirth',
                    'birthdate',
                    'birthday',
                    'dob',
                    'imageurl',
                }
            ):
                continue
            sanitized[key] = sanitize_cached_data(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_cached_data(item) for item in value]
    return value


def save_event_cache(events, group_id):
    """Write fetched events and schema metadata to the local JSON cache.

    Args:
        events: Iterable of event mappings to serialize.
        group_id: Spond group identifier associated with the events.

    Returns:
        Path to the written ``upcoming_events.json`` cache.

    Raises:
        OSError: If the cache cannot be written.
    """
    cache_path = Path(__file__).with_name('upcoming_events.json')
    cache = {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'groupId': group_id,
        'identifierMeanings': IDENTIFIER_MEANINGS,
        'positionFieldIds': POSITION_FIELD_IDS,
        'events': sanitize_cached_data(list(events)),
    }
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return cache_path


def load_event_cache():
    """Load and validate events from the local JSON cache.

    Returns:
        The cached list of event mappings.

    Raises:
        OSError: If the cache file cannot be read.
        ValueError: If the cache does not contain an events list.
        json.JSONDecodeError: If the cache is not valid JSON.
    """
    cache_path = Path(__file__).with_name('upcoming_events.json')
    cache = json.loads(cache_path.read_text(encoding='utf-8'))
    if not isinstance(cache, dict) or not isinstance(cache.get('events'), list):
        raise ValueError(f'Expected an events list in {cache_path}.')
    return cache['events']


def load_spond_client_module():
    """Import and return the installed Spond API client module.

    Temporarily removes the repository root from ``sys.path`` so this
    repository's ``spond.py`` does not shadow the installed ``spond`` package.

    Returns:
        The installed ``spond.spond`` module.

    Raises:
        ImportError: If the Spond API package is not installed.
    """
    repository_root = Path(__file__).resolve().parents[1]
    local_script = repository_root / 'spond.py'
    cached_module = sys.modules.get('spond')
    cached_path = getattr(cached_module, '__file__', None)
    if cached_path and Path(cached_path).resolve() == local_script:
        del sys.modules['spond']

    original_path = sys.path[:]
    sys.path[:] = [
        entry
        for entry in original_path
        if Path(entry or os.getcwd()).resolve() != repository_root
    ]
    try:
        return importlib.import_module('spond.spond')
    except ModuleNotFoundError as error:
        if error.name in ('spond', 'spond.spond'):
            raise ImportError(
                'The Spond API package is unavailable. Install the project requirements.'
            ) from error
        raise
    finally:
        sys.path[:] = original_path


async def fetch_upcoming_events(username, password, group_id):
    """Fetch visible upcoming events and build normalized attendee data.

    Args:
        username: Spond account username.
        password: Spond account password.
        group_id: Identifier of the Spond group to query.

    Returns:
        A list of event mappings with attendees and normalized player
        preference dictionaries.

    Raises:
        ImportError: If the Spond API client package is unavailable.
        ValueError: If attendee preference data is malformed or names collide.
        Exception: Propagates API and network errors from the Spond client.
    """
    spond_client = load_spond_client_module().Spond
    client = spond_client(username=username, password=password)
    try:
        events = await client.get_events(
            group_id,
            max_events=1000,
        )
        events = visible_events(events or [])
        saved_events = []
        for event in events:
            people = []
            for person_id in event.get('responses', {}).get('acceptedIds', []):
                people.append(await client.get_person(person_id))
            saved_events.append({
                'id': event.get('id'),
                'heading': event.get('heading'),
                'startTimestamp': event['startTimestamp'],
                'endTimestamp': event['endTimestamp'],
                'maxAccepted': event.get('maxAccepted'),
                'people': people,
                'players': player_preferences(people),
            })
        return saved_events
    finally:
        await client.clientsession.close()


def player_preferences(people):
    """Convert Spond attendee records into position preference dictionaries.

    Args:
        people: Iterable of Spond person mappings with optional ``fields``.

    Returns:
        Mapping of full player names to position-to-rank mappings, ordered by
        preference rank.

    Raises:
        ValueError: If names are duplicated, ``fields`` is malformed, or a
            preference rank is not an integer from 1 through 5.
    """
    players = {}
    for person in people:
        name = ' '.join(
            part for part in (person.get('firstName'), person.get('lastName')) if part
        ) or person.get('id', 'Unknown person')
        if name in players:
            raise ValueError(f'Multiple attending people have the same name: {name}.')

        fields = person.get('fields', {})
        if not isinstance(fields, dict):
            raise ValueError(f'Expected a fields dictionary for {name}.')

        preferences = {}
        for field_id, position in POSITION_FIELD_IDS.items():
            if field_id not in fields:
                continue
            rank = fields[field_id]
            if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 5:
                raise ValueError(
                    f'Invalid {position} preference rank for {name}: {rank!r}.'
                )
            preferences[position] = rank
        players[name] = dict(
            sorted(preferences.items(), key=lambda item: item[1])
        )
    return players


def load_players_from_json(path=None, event_index=0):
    """Load normalized player preferences for one cached event.

    Args:
        path: Optional path to an event-cache JSON file; defaults to the cache
            beside this module.
        event_index: Zero-based index of the event in the cache.

    Returns:
        Mapping of player names to position preference ranks.

    Raises:
        OSError: If the cache file cannot be read.
        ValueError: If the cache or selected player's data has an invalid shape.
        IndexError: If ``event_index`` is outside the cached event list.
    """
    cache_path = Path(path) if path is not None else Path(__file__).with_name(
        'upcoming_events.json'
    )
    cache = json.loads(cache_path.read_text(encoding='utf-8'))
    if not isinstance(cache, dict) or not isinstance(cache.get('events'), list):
        raise ValueError(f'Expected an events list in {cache_path}.')
    events = cache['events']
    if not 0 <= event_index < len(events):
        raise IndexError(
            f'Event index {event_index} is out of range for {len(events)} cached events.'
        )

    event = events[event_index]
    players = event.get('players')
    if players is None:
        players = player_preferences(event.get('people', []))
    if not isinstance(players, dict):
        raise ValueError(f'Expected a players dictionary for event {event_index}.')
    return players


def visible_events(events):
    """Remove hidden events and sort the rest by start time.

    Args:
        events: Iterable of Spond event mappings with start timestamps.

    Returns:
        A list of visible event mappings ordered by start time.

    Raises:
        KeyError: If an event has no start timestamp.
        ValueError: If a start timestamp is malformed.
    """
    visible = []
    for event in events:
        if event.get('hidden') is True:
            continue
        start = datetime.fromisoformat(
            event['startTimestamp'].replace('Z', '+00:00')
        )
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        visible.append((start, event))
    return [event for _, event in sorted(visible, key=lambda item: item[0])]


def load_saved_events():
    """Read the Python-literal event list from ``results.py``.

    Returns:
        The saved list of event mappings.

    Raises:
        OSError: If the saved-data file cannot be read.
        ValueError: If the file is not a literal event list.
        SyntaxError: If the saved data is not valid Python literal syntax.
    """
    results_path = Path(__file__).with_name('results.py')
    events = ast.literal_eval(results_path.read_text(encoding='utf-8'))
    if not isinstance(events, list):
        raise ValueError(f'Expected a list of events in {results_path}.')
    return events


async def main(source='api'):
    """Run the event inspection workflow for the selected data source.

    Args:
        source: ``api`` to fetch live events, ``json`` to read the JSON cache,
            or ``results`` to read the saved Python-literal event file.

    Returns:
        None. Prints event details and saves the cache for live API requests.

    Raises:
        ValueError: If API credentials are missing or ``source`` cannot be
            used to load data.
        Exception: Propagates file, parsing, and Spond API errors.
    """
    if source == 'json':
        events = load_event_cache()
        for event in events:
            print_event_details(event, event.get('people', []))
    elif source == 'results':
        events = visible_events(load_saved_events())
        for event in events:
            print_event_details(event, accepted_people(event))
    else:
        username = os.environ.get('SPOND_USERNAME')
        password = os.environ.get('SPOND_PASSWORD')
        group_id = os.environ.get('SPOND_GROUP_ID')
        if not username or not password or not group_id:
            raise ValueError(
                'Set SPOND_USERNAME, SPOND_PASSWORD, and SPOND_GROUP_ID to fetch live events.'
            )
        saved_events = await fetch_upcoming_events(username, password, group_id)
        cache_path = save_event_cache(saved_events, group_id)
        print(f'Saved event and attendee details to {cache_path}.')
        events = saved_events

    if not events:
        print('No upcoming events with open sign-up were found.')
    elif source == 'api':
        for event in events:
            print_event_details(event, event['people'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        '--from-file',
        action='store_true',
        help='Read events from check_spond/results.py instead of fetching them.',
    )
    source_group.add_argument(
        '--from-json',
        action='store_true',
        help='Read cached events and attendee details from upcoming_events.json.',
    )
    args = parser.parse_args()
    source = 'results' if args.from_file else 'json' if args.from_json else 'api'
    asyncio.run(main(source=source))