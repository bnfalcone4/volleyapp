"""JSON-backed signup records and waitlist offers for the signup app."""

import hashlib
import hmac
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_urlsafe

POSITION_CAPACITIES = {
    'setter': 3,
    'outside': 6,
    'middle': 6,
    'opposite': 3,
    'libero': 3,
}
TEST_EVENT = {
    'id': 'test-event-2026-11-10',
    'title': 'Test event — Tuesday 10 Nov, 10am–12pm',
    'starts_at': '2026-11-10T10:00:00+00:00',
    'ends_at': '2026-11-10T12:00:00+00:00',
    'capacity': sum(POSITION_CAPACITIES.values()),
    'positions': POSITION_CAPACITIES,
}


def utc_now():
    """Return a timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def normalize_email(email):
    """Normalize an email address for account matching."""
    return email.strip().casefold()


class JsonSignupStore:
    """Persist users, events, signups, and one-time offers in a JSON file."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._empty_data())

    @staticmethod
    def _empty_data():
        return {
            'schema_version': 1,
            'users': [],
            'events': [TEST_EVENT.copy()],
            'signups': {},
            'offers': [],
        }

    def _read(self):
        try:
            with self.path.open(encoding='utf-8') as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f'Could not read signup data from {self.path}: {error}') from error
        if not isinstance(data, dict):
            raise RuntimeError(f'Invalid signup data in {self.path}: expected an object.')
        if data.get('schema_version') != 1:
            raise RuntimeError(f'Unsupported signup data schema in {self.path}.')
        for event in data.get('events', []):
            event.setdefault('positions', POSITION_CAPACITIES.copy())
            event.setdefault('capacity', sum(event['positions'].values()))
        return data

    def _write(self, data):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.path.parent,
                prefix=f'.{self.path.name}.',
                delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(data, file, indent=2)
                file.write('\n')
            os.replace(temp_path, self.path)
        except OSError as error:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f'Could not save signup data to {self.path}: {error}') from error

    def _update(self, operation):
        with self._lock:
            data = self._read()
            original = json.dumps(data, sort_keys=True)
            result = operation(data)
            if json.dumps(data, sort_keys=True) != original:
                self._write(data)
            return result

    def events(self, now=None):
        """Return all future events in chronological order."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            data = self._read()
        return sorted(
            (
                event for event in data['events']
                if datetime.fromisoformat(event['starts_at']) > now
            ),
            key=lambda event: event['starts_at'],
        )

    def add_user(self, name, email):
        """Register a unique name/email pair."""
        clean_name = ' '.join(name.split())
        clean_email = normalize_email(email)
        if (
            not clean_name
            or '@' not in clean_email
            or any(character.isspace() for character in clean_email)
            or not all(clean_email.rsplit('@', 1))
        ):
            raise ValueError('Enter your name and a valid email address.')

        def operation(data):
            if any(
                normalize_email(user['email']) == clean_email
                for user in data['users']
            ):
                raise ValueError('That email is already registered. Use Returning sign in.')
            data['users'].append({
                'name': clean_name,
                'email': clean_email,
                'created_at': utc_now(),
            })
            return clean_email

        return self._update(operation)

    def authenticate(self, name, email):
        """Return the registered user only when both name and email match."""
        clean_email = normalize_email(email)
        clean_name = ' '.join(name.split()).casefold()
        with self._lock:
            data = self._read()
        for user in data['users']:
            if (
                normalize_email(user['email']) == clean_email
                and ' '.join(user['name'].split()).casefold() == clean_name
            ):
                return user.copy()
        return None

    def signup(self, event_id, email, preferences):
        """Save ranked preferences, assign an available position, and queue offers."""
        clean_email = normalize_email(email)
        validated = self._validate_preferences(preferences)

        def operation(data):
            event = self._find_event(data, event_id)
            user = self._find_user(data, clean_email)
            event_signups = data['signups'].setdefault(event_id, {})
            entry = event_signups.get(clean_email)
            if entry is None:
                entry = {
                    'created_at': utc_now(),
                    'rejected_positions': [],
                }
                event_signups[clean_email] = entry
            elif entry.get('preferences') != validated:
                entry['rejected_positions'] = []
            for offer in data['offers']:
                if (
                    offer['event_id'] == event_id
                    and offer['email'] == clean_email
                    and offer['status'] == 'pending'
                ):
                    offer['status'] = 'cancelled'
            old_position = entry.get('position')
            entry.update({
                'preferences': validated,
                'status': 'waitlisted',
                'position': None,
            })
            position = self._choose_position(
                event,
                event_signups,
                clean_email,
                validated,
                data['offers'],
            )
            if position is not None:
                entry.update({'status': 'assigned', 'position': position})
            new_offers = self._offer_waitlist(data, event)
            return {
                'status': entry['status'],
                'position': entry['position'],
                'old_position': old_position,
                'new_offers': new_offers,
                'name': user['name'],
            }

        return self._update(operation)

    def event_status(self, event_id):
        """Return assignment and waitlist details for an event."""
        with self._lock:
            data = self._read()
        event = self._find_event(data, event_id)
        signups = data['signups'].get(event_id, {})
        users = {
            normalize_email(user['email']): user['name']
            for user in data['users']
        }
        details = []
        for email, entry in sorted(
            signups.items(),
            key=lambda item: item[1]['created_at'],
        ):
            details.append({
                'name': users[email],
                'email': email,
                **entry,
            })
        return event.copy(), details

    def pending_offer(self, event_id, email):
        """Return the signed-in user's pending offer, if any."""
        clean_email = normalize_email(email)
        with self._lock:
            data = self._read()
        for offer in data['offers']:
            if (
                offer['event_id'] == event_id
                and offer['email'] == clean_email
                and offer['status'] == 'pending'
            ):
                return {
                    'id': offer['id'],
                    'position': offer['position'],
                }
        return None

    def create_offer_links(self, event_id):
        """Create fresh action tokens for unsent offers."""
        def operation(data):
            results = []
            for offer in data['offers']:
                if (
                    offer['event_id'] == event_id
                    and offer['status'] == 'pending'
                    and not offer.get('email_sent')
                ):
                    token = token_urlsafe(32)
                    offer['token_hash'] = self._hash_token(token)
                    results.append({
                        'offer_id': offer['id'],
                        'email': offer['email'],
                        'position': offer['position'],
                        'token': token,
                    })
            return results

        return self._update(operation)

    def mark_offer_sent(self, offer_id):
        """Record that the offer email was delivered to the SMTP server."""
        def operation(data):
            offer = self._find_offer(data, offer_id)
            if offer['status'] != 'pending':
                raise ValueError('This offer is no longer pending.')
            offer['email_sent'] = True

        self._update(operation)

    def respond_to_offer(self, token, accept):
        """Accept or reject an offer using its one-time emailed token."""
        token_hash = self._hash_token(token)

        def operation(data):
            offer = next(
                (
                    candidate for candidate in data['offers']
                    if hmac.compare_digest(candidate['token_hash'], token_hash)
                ),
                None,
            )
            if offer is None or offer['status'] != 'pending':
                raise ValueError('This offer link is invalid or has already been used.')
            return self._respond(data, offer, accept)

        return self._update(operation)

    def respond_to_offer_as_user(self, offer_id, email, accept):
        """Accept or reject a simulated offer for the signed-in user."""
        clean_email = normalize_email(email)

        def operation(data):
            offer = next(
                (
                    candidate for candidate in data['offers']
                    if candidate['id'] == offer_id
                    and candidate['email'] == clean_email
                ),
                None,
            )
            if offer is None or offer['status'] != 'pending':
                raise ValueError('This offer is no longer available.')
            return self._respond(data, offer, accept)

        return self._update(operation)

    @classmethod
    def _respond(cls, data, offer, accept):
        event = cls._find_event(data, offer['event_id'])
        entry = data['signups'][offer['event_id']][offer['email']]
        if entry['status'] != 'offered':
            raise ValueError('This offer is no longer available.')
        if datetime.fromisoformat(event['starts_at']) <= datetime.now(timezone.utc):
            offer['status'] = 'expired'
            entry.update({'status': 'waitlisted', 'position': None})
            return {
                'event_id': event['id'],
                'accepted': False,
                'expired': True,
                'position': offer['position'],
                'new_offers': [],
            }
        if accept:
            entry.update({'status': 'assigned', 'position': offer['position']})
            offer['status'] = 'accepted'
        else:
            entry.update({'status': 'waitlisted', 'position': None})
            rejected = set(entry.get('rejected_positions', []))
            rejected.add(offer['position'])
            entry['rejected_positions'] = sorted(rejected)
            offer['status'] = 'rejected'
        new_offers = cls._offer_waitlist(data, event)
        return {
            'event_id': event['id'],
            'accepted': accept,
            'expired': False,
            'position': offer['position'],
            'new_offers': new_offers,
        }

    @staticmethod
    def _validate_preferences(preferences):
        if not isinstance(preferences, dict):
            raise ValueError('Select a rank for each position.')
        result = {}
        used_ranks = set()
        for position, rank in preferences.items():
            if position not in POSITION_CAPACITIES:
                raise ValueError(f'Unknown position: {position}.')
            if rank in (None, ''):
                continue
            if isinstance(rank, bool):
                raise ValueError('Position ranks must be whole numbers from 1 to 5.')
            if rank == 0:
                continue
            if not isinstance(rank, int) or not 1 <= rank <= 5:
                raise ValueError('Position ranks must be whole numbers from 1 to 5.')
            if rank in used_ranks:
                raise ValueError('Each preferred position must have a unique rank.')
            used_ranks.add(rank)
            result[position] = rank
        if not result:
            raise ValueError('Rank at least one preferred position.')
        return result

    @staticmethod
    def _choose_position(event, signups, email, preferences, offers):
        occupied = {
            position: 0 for position in event['positions']
        }
        occupied_total = 0
        for other_email, entry in signups.items():
            if other_email != email and entry.get('status') == 'assigned':
                occupied[entry['position']] += 1
                occupied_total += 1
        for offer in offers:
            if (
                offer['event_id'] == event['id']
                and offer['status'] == 'pending'
            ):
                occupied[offer['position']] += 1
                occupied_total += 1
        for position, _ in sorted(
            preferences.items(),
            key=lambda item: (item[1], list(POSITION_CAPACITIES).index(item[0])),
        ):
            if (
                occupied_total < event['capacity']
                and occupied[position] < event['positions'][position]
            ):
                return position
        return None

    @classmethod
    def _offer_waitlist(cls, data, event):
        """Reserve open spots for the first eligible waitlisted signups."""
        event_id = event['id']
        signups = data['signups'].get(event_id, {})
        occupied = {position: 0 for position in event['positions']}
        occupied_total = 0
        pending_emails = set()
        for email, entry in signups.items():
            if entry.get('status') == 'assigned':
                occupied[entry['position']] += 1
                occupied_total += 1
            elif entry.get('status') == 'offered':
                pending = next(
                    (
                        offer for offer in data['offers']
                        if offer['event_id'] == event_id
                        and offer['email'] == email
                        and offer['status'] == 'pending'
                    ),
                    None,
                )
                if pending is not None:
                    occupied[pending['position']] += 1
                    occupied_total += 1
                    pending_emails.add(email)

        created = []
        waitlist = sorted(
            (
                (email, entry) for email, entry in signups.items()
                if entry.get('status') == 'waitlisted'
            ),
            key=lambda item: item[1]['created_at'],
        )
        for position, capacity in event['positions'].items():
            while (
                occupied[position] < capacity
                and occupied_total < event['capacity']
            ):
                candidate = next(
                    (
                        (email, entry) for email, entry in waitlist
                        if email not in pending_emails
                        and position in entry['preferences']
                        and position not in entry.get('rejected_positions', [])
                    ),
                    None,
                )
                if candidate is None:
                    break
                email, entry = candidate
                offer_id = uuid.uuid4().hex
                data['offers'].append({
                    'id': offer_id,
                    'event_id': event_id,
                    'email': email,
                    'position': position,
                    'token_hash': '',
                    'status': 'pending',
                    'email_sent': False,
                    'created_at': utc_now(),
                })
                entry.update({'status': 'offered', 'position': position})
                occupied[position] += 1
                occupied_total += 1
                pending_emails.add(email)
                created.append(offer_id)
        return created

    @staticmethod
    def _find_event(data, event_id):
        for event in data['events']:
            if event['id'] == event_id:
                return event
        raise ValueError('Event not found.')

    @staticmethod
    def _find_user(data, email):
        for user in data['users']:
            if normalize_email(user['email']) == email:
                return user
        raise ValueError('Register before signing up for an event.')

    @staticmethod
    def _find_offer(data, offer_id):
        for offer in data['offers']:
            if offer['id'] == offer_id:
                return offer
        raise ValueError('Offer not found.')

    @staticmethod
    def _hash_token(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()
