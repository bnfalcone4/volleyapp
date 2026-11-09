"""Tests for the signup app's JSON store."""

import tempfile
import unittest
from pathlib import Path

from signup_app.store import JsonSignupStore


class SignupStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JsonSignupStore(Path(self.temp_dir.name) / 'signups.json')
        self.event_id = 'test-event-2026-11-10'

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_player(self, number):
        email = f'player{number}@example.test'
        self.store.add_user(f'Player {number}', email)
        return email

    def test_registration_requires_matching_name_and_email(self):
        email = self.add_player(1)

        self.assertIsNone(self.store.authenticate('Someone else', email))
        self.assertEqual('Player 1', self.store.authenticate('player 1', email)['name'])
        with self.assertRaisesRegex(ValueError, 'already registered'):
            self.store.add_user('Player 1', email)

    def test_assignment_uses_ranked_positions_only(self):
        first_email = self.add_player(1)
        result = self.store.signup(
            self.event_id,
            first_email,
            {'setter': 2, 'outside': 1},
        )

        self.assertEqual('assigned', result['status'])
        self.assertEqual('outside', result['position'])
        self.assertEqual([], result['new_offers'])

    def test_vacancy_offers_position_and_rejection_advances_waitlist(self):
        emails = [self.add_player(number) for number in range(1, 6)]
        for email in emails:
            result = self.store.signup(self.event_id, email, {'setter': 1})
        self.assertEqual('waitlisted', result['status'])

        self.store.signup(self.event_id, emails[0], {'outside': 1})
        _, entries = self.store.event_status(self.event_id)
        first_offer = next(
            entry for entry in entries if entry['email'] == emails[3]
        )
        self.assertEqual('offered', first_offer['status'])
        self.assertEqual('setter', first_offer['position'])

        links = self.store.create_offer_links(self.event_id)
        token = next(
            link['token'] for link in links if link['email'] == emails[3]
        )
        result = self.store.respond_to_offer(token, accept=False)
        self.assertFalse(result['accepted'])
        _, entries = self.store.event_status(self.event_id)
        second_offer = next(
            entry for entry in entries if entry['email'] == emails[4]
        )
        self.assertEqual('offered', second_offer['status'])
        self.assertEqual('setter', second_offer['position'])

    def test_duplicate_ranks_are_rejected(self):
        email = self.add_player(1)
        with self.assertRaisesRegex(ValueError, 'unique rank'):
            self.store.signup(
                self.event_id,
                email,
                {'setter': 1, 'outside': 1},
            )

    def test_simulated_offer_response_is_scoped_to_signed_in_user(self):
        emails = [self.add_player(number) for number in range(1, 5)]
        for email in emails:
            self.store.signup(self.event_id, email, {'setter': 1})
        self.store.signup(self.event_id, emails[0], {'outside': 1})

        offer = self.store.pending_offer(self.event_id, emails[3])
        self.assertIsNotNone(offer)
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            self.store.respond_to_offer_as_user(
                offer['id'],
                emails[2],
                accept=True,
            )

        result = self.store.respond_to_offer_as_user(
            offer['id'],
            emails[3],
            accept=True,
        )
        self.assertTrue(result['accepted'])
        self.assertEqual('setter', result['position'])


if __name__ == '__main__':
    unittest.main()
