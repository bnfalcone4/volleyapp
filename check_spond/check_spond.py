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
    accepted_ids = event.get('responses', {}).get('acceptedIds', [])
    members = event.get('recipients', {}).get('group', {}).get('members', [])
    members_by_id = {member.get('id'): member for member in members}
    return [members_by_id[user_id] for user_id in accepted_ids if user_id in members_by_id]


def print_event_details(event, people):
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


def save_event_cache(events, group_id):
    cache_path = Path(__file__).with_name('upcoming_events.json')
    cache = {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'groupId': group_id,
        'identifierMeanings': IDENTIFIER_MEANINGS,
        'positionFieldIds': POSITION_FIELD_IDS,
        'events': events,
    }
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return cache_path


def load_event_cache():
    cache_path = Path(__file__).with_name('upcoming_events.json')
    cache = json.loads(cache_path.read_text(encoding='utf-8'))
    if not isinstance(cache, dict) or not isinstance(cache.get('events'), list):
        raise ValueError(f'Expected an events list in {cache_path}.')
    return cache['events']


def load_spond_client_module():
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
                'people': people,
                'players': player_preferences(people),
            })
        return saved_events
    finally:
        await client.clientsession.close()


def player_preferences(people):
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
    results_path = Path(__file__).with_name('results.py')
    events = ast.literal_eval(results_path.read_text(encoding='utf-8'))
    if not isinstance(events, list):
        raise ValueError(f'Expected a list of events in {results_path}.')
    return events


async def main(source='api'):
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