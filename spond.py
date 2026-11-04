import pandas as pd
import argparse
import sys

EVENT_CAPACITY = 21
FLEXIBLE_LIMITS = {'setter': (2, 3), 'outside': (4, 9), 'middle': (2, 6), 'libero': (2, 3)}

PREFERENCE_COLUMNS = {
    'setter': 'Playing as setter preference rank from 1 (best) to 5 (worst)',
    'outside': 'Outside rank from 1 to 5',
    'middle': 'Middle rank from 1 to 5',
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


def is_woman(name):

    if name in ['Eloise Vint', 'abigail Osoba', 'Rama Alrawi']:
        return 1

    return 0


def assign_flexible(players):
    minimum_total = sum(minimum for minimum, _ in FLEXIBLE_LIMITS.values())
    if len(players) < minimum_total:
        raise ValueError(
            f'Flexible mode needs at least {minimum_total} sign-ups to meet all minimums; '
            f'only {len(players)} were provided.'
        )

    assigned_players = players[:EVENT_CAPACITY]
    if len(assigned_players) < minimum_total:
        raise ValueError(
            f'Flexible mode needs at least {minimum_total} sign-ups to meet all minimums; '
            f'only {len(assigned_players)} can be assigned.'
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
                for role, (minimum, _) in FLEXIBLE_LIMITS.items()
            )
            if minimums_still_needed <= remaining_players:
                rank = preferences.get(position)
                assignments.append((name, position, rank))
                break
            counts[position] -= 1
        else:
            raise ValueError(
                f'Could not assign {name} while meeting the flexible position minimums.'
            )

    return assignments, players[EVENT_CAPACITY:]


def run_flexible(df):
    players = []
    for _, row in df.iterrows():
        preferences = {}
        for position, column in PREFERENCE_COLUMNS.items():
            rank = row[column]
            if pd.notna(rank) and 1 <= rank <= 5:
                preferences[position] = int(rank)
        players.append((row['Name'], preferences))

    assignments, waiting = assign_flexible(players)
    counts = {position: 0 for position in FLEXIBLE_LIMITS}

    print('Flexible assignments (signup order):')
    for number, (name, position, rank) in enumerate(assignments, start=1):
        counts[position] += 1
        score = rank if rank is not None else 'no preference'
        print(f'{number}. {name} - {position} - {score}')

    print('\nPosition totals:')
    for position, (minimum, maximum) in FLEXIBLE_LIMITS.items():
        print(f'{position}: {counts[position]} (minimum {minimum}, maximum {maximum})')

    if waiting:
        print('\nWaiting:')
        for name, _ in waiting:
            print(name)


def main():
    parser = argparse.ArgumentParser(description='Assign players to volleyball positions.')
    parser.add_argument('csv_file', help='Spond sign-up CSV file')
    parser.add_argument(
        '--mode',
        choices=('ranked', 'flexible'),
        default='ranked',
        help='Use flexible position limits and signup-order assignment',
    )
    args = parser.parse_args()
    df = pd.read_csv(args.csv_file)

    if args.mode == 'flexible':
        run_flexible(df)
        return

    EVENT_POSITIONS = {'setter': 3, 'outside': 6, 'middle': 6, 'opposite': 3, 'libero': 3, 'unknown': EVENT_CAPACITY}

    setter_col = PREFERENCE_COLUMNS['setter']
    outside_col = PREFERENCE_COLUMNS['outside']
    middle_col = PREFERENCE_COLUMNS['middle']
    opposite_col = 'Opposite rank from 1 to 5'
    libero_col = PREFERENCE_COLUMNS['libero']

    df['Order'] = range(1, len(df)+1)
    df['Woman'] = df['Name'].apply(is_woman)
    df['Sum_preferences'] = df[[setter_col, outside_col, middle_col, opposite_col, libero_col]].sum(axis=1)
    df['Sum_preferences'] = df['Sum_preferences'].fillna(0)
    df['Missing'] = (df['Sum_preferences'] < 1).astype(int)
    df['Waiting'] = (df['Order'] > EVENT_CAPACITY).astype(int)

    print(df)
    df = df.sort_values(
        ['Waiting', 'Woman', 'Missing', 'Order'],
        ascending=[True, False, True, True],
        na_position='first',
    )
    print(df)
    df = df.fillna(999)
    print(df)

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