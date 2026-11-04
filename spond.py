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

def assign_position(player, preferences, positions, assignment, waiting):

    if len(assignment) >= EVENT_CAPACITY:
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


def ranked_assignments(players):
    positions = EVENT_POSITIONS.copy()
    assignment = {}
    waiting = {}
    for player, preferences in players.items():
        assignment, positions, waiting = assign_position(
            player, preferences, positions, assignment, waiting
        )
    return assignment, waiting


def assign_ranked_players(players):
    assignment, waiting = ranked_assignments(players)
    for number, (player, position) in enumerate(assignment.items(), start=1):
        rank = players[player].get(position)
        score = '' if rank is None else rank
        print(f'{number}. {player.split()[0]} - {position} - {score}')

    if waiting:
        print('Waiting:')
        for player, preferences in waiting.items():
            print(player.split()[0], '-'.join(preferences))
    return assignment, waiting


def is_woman(name):

    if name in ['Eloise Vint', 'abigail Osoba', 'Rama Alrawi']:
        return 1

    return 0


def assign_flexible(players, minimums):
    assigned_players = players[:EVENT_CAPACITY]
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

    return assignments, players[EVENT_CAPACITY:]


def assign_hungarian(players, minimums):
    try:
        from munkres import Munkres
    except ImportError as error:
        raise RuntimeError(
            'Hungarian mode requires the munkres package. Install it with '
            '`python -m pip install munkres`.'
        ) from error

    assigned_players = players[:EVENT_CAPACITY]
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

    tie_break_max = 6 * sum(range(1, player_count + 1))
    preference_scale = tie_break_max + 1
    largest_player_cost = 6 * preference_scale + 6 * player_count
    mandatory_slot_penalty = largest_player_cost * (len(slots) + 1)

    costs = []
    for index, (_, preferences) in enumerate(assigned_players):
        order_weight = player_count - index
        costs.append([
            (preferences.get(position, 6) * preference_scale)
            + (preferences.get(position, 6) * order_weight)
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

    return assignments, players[EVENT_CAPACITY:]


def load_minimums(csv_path, total):
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


def run_hungarian(df, minimums):
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

    print('Hungarian assignments (preference-optimized):')
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


def sort_signups(df, print_frames=False):
    df = df.copy()
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
        choices=('ranked', 'flexible', 'hungarian'),
        default='ranked',
        help='Use ranked, signup-order flexible, or preference-optimized assignment',
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

        players = load_players_from_json(args.preferences_json, args.event_index)
        assign_ranked_players(players)
        return

    if not args.csv_file:
        parser.error('csv_file is required unless --preferences-json is provided.')
    df = pd.read_csv(args.csv_file)

    if args.mode in ('flexible', 'hungarian'):
        total = min(len(df), EVENT_CAPACITY)
        minimums = load_minimums(args.minimums_csv, total)
        if args.mode == 'flexible':
            run_flexible(df, minimums)
        else:
            run_hungarian(sort_signups(df), minimums)
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
        }

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


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        sys.exit(str(error))