import pandas as pd
import sys

EVENT_CAPACITY = 21

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

positions = {'setter': 3, 'outside': 6, 'middle': 6, 'opposite': 3, 'libero': 3, 'unknown': EVENT_CAPACITY}

setter_col = 'Playing as setter preference rank from 1 (best) to 5 (worst)'
outside_col = 'Outside rank from 1 to 5'
middle_col = 'Middle rank from 1 to 5'
opposite_col = 'Opposite rank from 1 to 5'
libero_col = 'Libero rank from 1 to 5'

df = pd.read_csv(sys.argv[1])

df['Order'] = range(1, len(df)+1)

df['Woman'] = df['Name'].apply(is_woman)

df['Sum_preferences'] = df[[setter_col, outside_col, middle_col, opposite_col, libero_col]].sum(axis=1)

df['Sum_preferences'] = df['Sum_preferences'].fillna(0)

df['Missing'] = (df['Sum_preferences'] < 1).astype(int)

df['Waiting'] = (df['Order'] > EVENT_CAPACITY).astype(int)

print(df)

df = df.sort_values(['Waiting', 'Woman', 'Missing', 'Order'], ascending=[True, False, True, True], na_position='first')

print(df)

df = df.fillna(999)

print(df)

players = {}

for index, row in df.iterrows():

    name = row['Name']
    setter = row[setter_col]
    outside = row[outside_col]
    middle = row[middle_col]
    opposite = row[opposite_col]
    libero = row[libero_col]

    pref = {'setter': setter, 'outside': outside, 'middle': middle, 'opposite': opposite, 'libero':libero}
    sorted_pref = {k: v for k, v in sorted(pref.items(), key=lambda item: item[1])}

    players[name] = sorted_pref

assignment = {}
waiting = {}

for player, preferences in players.items():
    #print(player, preferences)

    assignment, positions, waiting = assign_position(player, preferences, positions, assignment, waiting)
    #print(assignment, positions)

for n, (player, pos) in enumerate(assignment.items()):
    if pos == 'unknown':
        score = ''
    else:
        score = int(players[player][pos])
    print(f'{n+1}. {player} - {pos} - {score}')

print(assignment)

inverted_assignment = {'setter': [], 'outside': [], 'middle': [], 'opposite': [], 'libero': [], 'unknown': []}

for player, pos in assignment.items():

    inverted_assignment[pos].append(player)

print(inverted_assignment)

for pos, player_list in inverted_assignment.items():

    print(f'{pos}:')
    for n, player in enumerate(player_list):
        print(f'{n+1}. {player}  {int(players[player][pos])}')
    print()


print('Waiting:')
for key, val in waiting.items():

    print(key, '-'.join(val))

print(players)