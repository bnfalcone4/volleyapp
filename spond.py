"""Assign Spond sign-ups to volleyball positions.

The module supports ranked, signup-order flexible, and optimized assignments.
Its command-line interface accepts either a Spond CSV export or cached event
preferences; assignment helpers return player assignments and waiting lists,
while the ``run_*`` helpers and CLI print results. Submitted preference scores
are compressed per player into consecutive ranks, with missing scores omitted.
"""

import pandas as pd
import argparse
import sys
from pathlib import Path

EVENT_CAPACITY = 21
EVENT_POSITIONS = {
    'setter': 3,
    'outside': 6,
    'middle': 6,
    'opposite': 3,
    'libero': 3,
    'unknown': EVENT_CAPACITY,
}
FLEXIBLE_LIMITS = {
    'setter': (2, 3),
    'outside': (4, 9),
    'middle': (2, 6),
    'opposite': (2, 3),
    'libero': (2, 3),
}

PREFERENCE_COLUMNS = {
    'setter': 'Playing as setter preference rank from 1 (best) to 5 (worst)',
    'outside': 'Outside rank from 1 to 5',
    'middle': 'Middle rank from 1 to 5',
    'opposite': 'Opposite rank from 1 to 5',
    'libero': 'Libero rank from 1 to 5',
}

def assign_position(
    player,
    preferences,
    positions,
    assignment,
    waiting,
    event_capacity=EVENT_CAPACITY,
):
    """Assign one player using ranked preferences and update assignment state.

    Args:
        player: Player's name.
        preferences: Ordered mapping of position names to preference ranks.
        positions: Mutable mapping of positions to remaining capacities.
        assignment: Mutable mapping of already-assigned players to positions.
        waiting: Mutable mapping of players to positions that were full.
        event_capacity: Maximum number of players assigned to the event.

    Returns:
        The updated ``(assignment, positions, waiting)`` mappings.
    """

    if len(assignment) >= event_capacity:
        waiting[player] = [pos for pos, val in preferences.items() if val <= 5]
        return assignment, positions, waiting

    for pos, val in preferences.items():
        if val > 5:
            break
        if positions[pos] > 0:
            assignment[player] = pos
            positions[pos] -= 1
            return assignment, positions, waiting
        else:
            if player in waiting:
                waiting[player].append(pos)
            else:
                waiting[player] = [pos]

    assignment[player] = 'unknown'
    positions['unknown'] -= 1

    return assignment, positions, waiting


def normalize_preference_ranks(preferences):
    """Compress submitted position scores to consecutive preference ranks.

    Positions are ordered by their submitted score, with ties resolved in the
    order defined by ``PREFERENCE_COLUMNS``. Positions without scores are
    omitted, so they remain empty rather than receiving a rank.

    Args:
        preferences: Mapping of position names to submitted numeric scores.

    Returns:
        A new mapping of scored positions to consecutive ranks starting at 1.
    """
    position_order = {
        position: index for index, position in enumerate(PREFERENCE_COLUMNS)
    }
    scored = [
        (position, score)
        for position, score in preferences.items()
        if pd.notna(score)
    ]
    scored.sort(
        key=lambda item: (
            item[1],
            position_order.get(item[0], len(position_order)),
        )
    )
    return {
        position: rank
        for rank, (position, _) in enumerate(scored, start=1)
    }


def normalize_player_preferences(players):
    """Normalize every player's submitted preference scores.

    Args:
        players: Mapping of player names to position-to-score mappings.

    Returns:
        A new player mapping with each player's scored positions ranked
        consecutively from 1, leaving unscored positions absent.
    """
    return {
        name: normalize_preference_ranks(preferences)
        for name, preferences in players.items()
    }


def normalize_preference_columns(df):
    """Normalize preference scores in a Spond sign-up DataFrame.

    Args:
        df: DataFrame containing the position columns in
            ``PREFERENCE_COLUMNS``.

    Returns:
        A copy of ``df`` with each player's submitted scores compressed to
        consecutive ranks and missing scores left empty.
    """
    normalized_df = df.copy()
    columns = list(PREFERENCE_COLUMNS.values())
    normalized_rows = []
    for row in normalized_df[columns].itertuples(index=False, name=None):
        preferences = {
            position: score
            for position, score in zip(PREFERENCE_COLUMNS, row)
        }
        normalized = normalize_preference_ranks(preferences)
        normalized_rows.append(
            [
                normalized.get(position, pd.NA)
                for position in PREFERENCE_COLUMNS
            ]
        )
    normalized_df[columns] = pd.DataFrame(
        normalized_rows,
        index=normalized_df.index,
        columns=columns,
    )
    return normalized_df


def preference_rank_totals(assignments):
    """Count assigned players by rank and return the sum of their rank scores.

    Args:
        assignments: Iterable of ``(name, position, rank)`` rows.

    Returns:
        A pair containing counts for ranks 1 through 5 and the sum of all
        assigned rank values. Assignments without a rank are excluded.
    """
    totals = {rank: 0 for rank in range(1, 6)}
    for _, _, rank in assignments:
        if rank is not None and rank in totals:
            totals[rank] += 1
    return totals, sum(rank * count for rank, count in totals.items())


def print_preference_rank_totals(assignments):
    """Print counts by assigned preference rank, total, and average.

    Args:
        assignments: Iterable of ``(name, position, rank)`` rows.

    Returns:
        None. Writes rank counts, their sum, and average to standard output.
    """
    totals, total = preference_rank_totals(assignments)
    for rank, count in totals.items():
        print(f'Rank {rank}: {count}')
    print(f'Total: {total}')
    player_count = sum(totals.values())
    average = total / player_count if player_count else 0
    print(f'Average: {average:.2f}')


def ranked_assignments(players, event_capacity=EVENT_CAPACITY):
    """Assign players to fixed-capacity positions in input order.

    Args:
        players: Mapping of player names to ordered position preference ranks.
        event_capacity: Maximum number of players assigned to the event.

    Returns:
        A pair of the player-to-position assignment mapping and a waiting-list
        mapping from player names to preferred positions that were full.
    """
    players = normalize_player_preferences(players)
    positions = EVENT_POSITIONS.copy()
    positions['unknown'] = event_capacity
    assignment = {}
    waiting = {}
    for player, preferences in players.items():
        assignment, positions, waiting = assign_position(
            player,
            preferences,
            positions,
            assignment,
            waiting,
            event_capacity,
        )
    return assignment, waiting


def assign_ranked_players(players):
    """Print ranked assignments and waiting players, then return both results.

    Args:
        players: Mapping of player names to position preference ranks.

    Returns:
        The assignment and waiting-list mappings from ``ranked_assignments``.
    """
    players = normalize_player_preferences(players)
    assignment, waiting = ranked_assignments(players)
    for number, (player, position) in enumerate(assignment.items(), start=1):
        rank = players[player].get(position)
        score = '' if rank is None else rank
        print(f'{number}. {player.split()[0]} - {position} - {score}')

    if waiting:
        print('Waiting:')
        for player, preferences in waiting.items():
            print(player.split()[0], '-'.join(preferences))
    rows = [
        (player, position, players[player].get(position))
        for player, position in assignment.items()
    ]
    print_preference_rank_totals(rows)
    return assignment, waiting


def is_woman(name):
    """Return whether a name is in the configured signup-priority list.

    Args:
        name: Player's full name.

    Returns:
        ``1`` if the name is in the configured list; otherwise ``0``.
    """

    if name in ['Eloise Vint', 'abigail Osoba', 'Rama Alrawi']:
        return 1

    return 0


def assign_flexible(players, minimums, event_capacity=EVENT_CAPACITY):
    """Assign the first event-capacity players in signup order.

    Preference ranks are considered while respecting configured minimums and
    the maximum for each position.

    Args:
        players: Ordered sequence of ``(name, preferences)`` pairs.
        minimums: Mapping of position names to required minimum counts.
        event_capacity: Maximum number of players assigned to the event.

    Returns:
        A pair of assignment rows ``(name, position, rank)`` and the players
        beyond event capacity as ``(name, preferences)`` pairs.

    Raises:
        ValueError: If the players cannot satisfy position minimums.
    """
    players = [
        (name, normalize_preference_ranks(preferences))
        for name, preferences in players
    ]
    assigned_players = players[:event_capacity]
    minimum_total = sum(minimums.values())
    if len(assigned_players) < minimum_total:
        raise ValueError(
            f'The configured position minimums total {minimum_total}, but only '
            f'{len(assigned_players)} players can be assigned.'
        )

    counts = {position: 0 for position in FLEXIBLE_LIMITS}
    assignments = []

    for index, (name, preferences) in enumerate(assigned_players):
        remaining_players = len(assigned_players) - index - 1
        ranked_positions = sorted(
            FLEXIBLE_LIMITS,
            key=lambda position: preferences.get(position, 6),
        )

        for position in ranked_positions:
            _, maximum = FLEXIBLE_LIMITS[position]
            if counts[position] >= maximum:
                continue

            counts[position] += 1
            minimums_still_needed = sum(
                max(0, minimum - counts[role])
                for role, minimum in minimums.items()
            )
            available_slots = sum(
                maximum - counts[role]
                for role, (_, maximum) in FLEXIBLE_LIMITS.items()
            )
            if (
                minimums_still_needed <= remaining_players
                and remaining_players <= available_slots
            ):
                rank = preferences.get(position)
                assignments.append((name, position, rank))
                break
            counts[position] -= 1
        else:
            raise ValueError(
                f'Could not assign {name} while meeting the flexible position minimums.'
            )

    return assignments, players[event_capacity:]


def assign_hungarian(players, minimums, event_capacity=EVENT_CAPACITY):
    """Find a preference-optimized assignment within position limits.

    Unscored positions receive the next rank after each player's submitted
    preferences.

    Args:
        players: Ordered sequence of ``(name, preferences)`` pairs.
        minimums: Mapping of position names to required minimum counts.
        event_capacity: Maximum number of players assigned to the event.

    Returns:
        A pair of assignment rows ``(name, position, rank)`` and the players
        beyond event capacity as ``(name, preferences)`` pairs.

    Raises:
        RuntimeError: If the optional ``munkres`` package is unavailable.
        ValueError: If the player count cannot satisfy the configured limits.
    """
    try:
        from munkres import Munkres
    except ImportError as error:
        raise RuntimeError(
            'Optimized mode requires the munkres package. Install it with '
            '`python -m pip install munkres`.'
        ) from error

    players = [
        (name, normalize_preference_ranks(preferences))
        for name, preferences in players
    ]
    assigned_players = players[:event_capacity]
    player_count = len(assigned_players)
    minimum_total = sum(minimums.values())
    maximum_total = sum(maximum for _, maximum in FLEXIBLE_LIMITS.values())
    if not minimum_total <= player_count <= maximum_total:
        raise ValueError(
            f'Position limits cannot assign {player_count} players; the configured '
            f'minimums total {minimum_total} and maximums total {maximum_total}.'
        )

    slots = []
    for position, (minimum, maximum) in FLEXIBLE_LIMITS.items():
        slots.extend((position, True) for _ in range(minimums[position]))
        slots.extend((position, False) for _ in range(maximum - minimums[position]))

    missing_ranks = [
        len(preferences) + 1 for _, preferences in assigned_players
    ]
    worst_preference_rank = max(missing_ranks, default=1)
    tie_break_max = worst_preference_rank * sum(
        range(1, player_count + 1)
    )
    preference_scale = tie_break_max + 1
    largest_player_cost = (
        worst_preference_rank * preference_scale
        + worst_preference_rank * player_count
    )
    mandatory_slot_penalty = largest_player_cost * (len(slots) + 1)

    costs = []
    for index, (_, preferences) in enumerate(assigned_players):
        order_weight = player_count - index
        missing_rank = len(preferences) + 1
        costs.append([
            (preferences.get(position, missing_rank) * preference_scale)
            + (preferences.get(position, missing_rank) * order_weight)
            for position, _ in slots
        ])

    dummy_count = len(slots) - player_count
    costs.extend([
        [
            mandatory_slot_penalty if mandatory else 0
            for _, mandatory in slots
        ]
        for _ in range(dummy_count)
    ])

    indexes = Munkres().compute(costs)
    indexes.sort()
    assignments = []
    for row_index, slot_index in indexes:
        if row_index >= player_count:
            continue
        name, preferences = assigned_players[row_index]
        position = slots[slot_index][0]
        assignments.append((name, position, preferences.get(position)))

    return assignments, players[event_capacity:]


def load_minimums(csv_path, total):
    """Load and validate position minimums for a specific player count.

    Args:
        csv_path: Path to the CSV containing per-total position minimums.
        total: Number of players to accommodate.

    Returns:
        A mapping of flexible position names to minimum player counts.

    Raises:
        ValueError: If required columns or a unique valid row are missing, or
            the resulting limits cannot accommodate ``total``.
    """
    minimums_df = pd.read_csv(csv_path)
    required_columns = {'total', *FLEXIBLE_LIMITS}
    missing_columns = required_columns - set(minimums_df.columns)
    if missing_columns:
        raise ValueError(
            f'{csv_path} is missing required columns: {", ".join(sorted(missing_columns))}'
        )

    totals = pd.to_numeric(minimums_df['total'], errors='coerce')
    matching_rows = minimums_df.loc[totals == total]
    if len(matching_rows) != 1:
        raise ValueError(
            f'{csv_path} must contain exactly one row for total={total}; '
            f'found {len(matching_rows)}.'
        )

    row = matching_rows.iloc[0]
    minimums = {}
    for position in FLEXIBLE_LIMITS:
        value = pd.to_numeric(row[position], errors='coerce')
        if pd.isna(value) or value < 0 or not float(value).is_integer():
            raise ValueError(
                f'{csv_path} has an invalid minimum for {position} at total={total}.'
            )
        minimum = int(value)
        if minimum > FLEXIBLE_LIMITS[position][1]:
            raise ValueError(
                f'{csv_path} sets {position} minimum to {minimum}, above its maximum '
                f'of {FLEXIBLE_LIMITS[position][1]}.'
            )
        minimums[position] = minimum

    minimum_total = sum(minimums.values())
    if minimum_total > total:
        raise ValueError(
            f'{csv_path} minimums for total={total} sum to {minimum_total}, '
            f'which exceeds the total.'
        )
    if sum(maximum for _, maximum in FLEXIBLE_LIMITS.values()) < total:
        raise ValueError(
            f'{csv_path} position maximums cannot accommodate total={total}.'
        )
    return minimums


def run_flexible(df, minimums):
    """Assign a Spond DataFrame in signup order and print results.

    Args:
        df: DataFrame with player names and preference-rank columns.
        minimums: Mapping of position names to required minimum counts.

    Returns:
        None. Prints assignments, position totals, and any waiting players.
    """
    players = []
    for _, row in df.iterrows():
        preferences = {}
        for position, column in PREFERENCE_COLUMNS.items():
            rank = row[column]
            if pd.notna(rank) and 1 <= rank <= 5:
                preferences[position] = int(rank)
        players.append((row['Name'], preferences))

    assignments, waiting = assign_flexible(players, minimums)
    counts = {position: 0 for position in FLEXIBLE_LIMITS}

    print('Flexible assignments (signup order):')
    for number, (name, position, rank) in enumerate(assignments, start=1):
        counts[position] += 1
        score = rank if rank is not None else 'no preference'
        print(f'{number}. {name} - {position} - {score}')

    print('\nPosition totals:')
    for position, (_, maximum) in FLEXIBLE_LIMITS.items():
        minimum = minimums[position]
        print(f'{position}: {counts[position]} (minimum {minimum}, maximum {maximum})')

    if waiting:
        print('\nWaiting:')
        for name, _ in waiting:
            print(name)
    print_preference_rank_totals(assignments)


def run_optimized(df, minimums):
    """Assign a Spond DataFrame with preference optimization and print results.

    Args:
        df: DataFrame with player names and preference-rank columns.
        minimums: Mapping of position names to required minimum counts.

    Returns:
        None. Prints assignments, position totals, and any waiting players.
    """
    players = []
    for _, row in df.iterrows():
        preferences = {}
        for position, column in PREFERENCE_COLUMNS.items():
            rank = row[column]
            if pd.notna(rank) and 1 <= rank <= 5:
                preferences[position] = int(rank)
        players.append((row['Name'], preferences))

    assignments, waiting = assign_hungarian(players, minimums)
    counts = {position: 0 for position in FLEXIBLE_LIMITS}

    print('Optimized assignments:')
    for number, (name, position, rank) in enumerate(assignments, start=1):
        counts[position] += 1
        score = rank if rank is not None else 'no preference'
        print(f'{number}. {name} - {position} - {score}')

    print('\nPosition totals:')
    for position, (_, maximum) in FLEXIBLE_LIMITS.items():
        print(
            f'{position}: {counts[position]} '
            f'(minimum {minimums[position]}, maximum {maximum})'
        )

    if waiting:
        print('\nWaiting:')
        for name, _ in waiting:
            print(name)
    print_preference_rank_totals(assignments)


def sort_signups(df, print_frames=False):
    """Order sign-ups for ranked/optimized assignment and normalize ranks.

    Args:
        df: Spond sign-up DataFrame containing names and preference columns.
        print_frames: If true, print intermediate DataFrame states.

    Returns:
        A copied DataFrame ordered by waiting status, configured priority,
        preference completeness, and original signup order.
    """
    df = normalize_preference_columns(df)
    df['Order'] = range(1, len(df) + 1)
    df['Woman'] = df['Name'].apply(is_woman)
    df['Sum_preferences'] = df[list(PREFERENCE_COLUMNS.values())].sum(axis=1)
    df['Sum_preferences'] = df['Sum_preferences'].fillna(0)
    df['Missing'] = (df['Sum_preferences'] < 1).astype(int)
    df['Waiting'] = (df['Order'] > EVENT_CAPACITY).astype(int)
    if print_frames:
        print(df)

    df = df.sort_values(
        ['Waiting', 'Woman', 'Missing', 'Order'],
        ascending=[True, False, True, True],
        na_position='first',
    )
    if print_frames:
        print(df)
    df[list(PREFERENCE_COLUMNS.values())] = df[list(PREFERENCE_COLUMNS.values())].fillna(999)
    if print_frames:
        print(df)
    return df


def main():
    """Parse command-line options and run the selected assignment workflow.

    Returns:
        None. Prints assignment results; argparse exits for invalid arguments.
    """
    parser = argparse.ArgumentParser(description='Assign players to volleyball positions.')
    parser.add_argument('csv_file', nargs='?', help='Spond sign-up CSV file')
    parser.add_argument(
        '--preferences-json',
        help='Use cached Spond preferences from check_spond/upcoming_events.json.',
    )
    parser.add_argument(
        '--event-index',
        type=int,
        default=0,
        help='Zero-based event index in the preferences JSON file (default: 0).',
    )
    parser.add_argument(
        '--mode',
        choices=('ranked', 'flexible', 'optimized'),
        default='ranked',
        help='Use ranked, signup-order flexible, or optimized assignment',
    )
    parser.add_argument(
        '--minimums-csv',
        default=str(Path(__file__).with_name('min_positions.csv')),
        help='CSV with per-total minimums used by flexible mode',
    )
    args = parser.parse_args()

    if args.preferences_json:
        if args.csv_file:
            parser.error('Do not provide csv_file together with --preferences-json.')
        if args.mode != 'ranked':
            parser.error('--preferences-json currently supports ranked mode only.')
        from check_spond.check_spond import load_players_from_json

        players = normalize_player_preferences(
            load_players_from_json(args.preferences_json, args.event_index)
        )
        assign_ranked_players(players)
        return

    if not args.csv_file:
        parser.error('csv_file is required unless --preferences-json is provided.')
    df = normalize_preference_columns(pd.read_csv(args.csv_file))

    if args.mode in ('flexible', 'optimized'):
        total = min(len(df), EVENT_CAPACITY)
        minimums = load_minimums(args.minimums_csv, total)
        if args.mode == 'flexible':
            run_flexible(df, minimums)
        else:
            run_optimized(sort_signups(df), minimums)
        return

    setter_col = PREFERENCE_COLUMNS['setter']
    outside_col = PREFERENCE_COLUMNS['outside']
    middle_col = PREFERENCE_COLUMNS['middle']
    opposite_col = PREFERENCE_COLUMNS['opposite']
    libero_col = PREFERENCE_COLUMNS['libero']

    df = sort_signups(df, print_frames=True)

    players = {}
    for _, row in df.iterrows():
        name = row['Name']
        preferences = {
            'setter': row[setter_col],
            'outside': row[outside_col],
            'middle': row[middle_col],
            'opposite': row[opposite_col],
            'libero': row[libero_col],
        }
        players[name] = {
            position: value
            for position, value in sorted(preferences.items(), key=lambda item: item[1])
            if pd.notna(value) and value <= 5
        }
    players = normalize_player_preferences(players)

    positions = EVENT_POSITIONS.copy()
    assignment = {}
    waiting = {}
    for player, preferences in players.items():
        assignment, positions, waiting = assign_position(
            player, preferences, positions, assignment, waiting
        )

    for number, (player, position) in enumerate(assignment.items(), start=1):
        score = '' if position == 'unknown' else int(players[player][position])
        print(f'{number}. {player} - {position} - {score}')

    print(assignment)
    inverted_assignment = {
        position: [] for position in EVENT_POSITIONS
    }
    for player, position in assignment.items():
        inverted_assignment[position].append(player)
    print(inverted_assignment)

    for position, player_list in inverted_assignment.items():
        print(f'{position}:')
        for number, player in enumerate(player_list, start=1):
            print(f'{number}. {player}  {int(players[player][position])}')
        print()

    print('Waiting:')
    for key, value in waiting.items():
        print(key, '-'.join(value))
    print(players)
    rows = [
        (player, position, players[player].get(position))
        for player, position in assignment.items()
    ]
    print_preference_rank_totals(rows)


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(str(error))