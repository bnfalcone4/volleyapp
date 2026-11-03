import pandas as pd


def assign_position(player, preferences, positions, assignment):

    for pos, val in preferences.items():
        if val > 5:
            break
        if positions[pos] > 0:
            assignment[player] = pos
            positions[pos] -= 1
            return assignment, positions

    assignment[player] = 'unknown'

    return assignment, positions


def is_woman(name):

    if name in ['Eloise Vint', 'abigail Osoba']:
        return 1

    return 0


setter_col = 'Playing as setter preference rank from 1 (best) to 5 (worst)'
outside_col = 'Outside rank from 1 to 5'
middle_col = 'Middle rank from 1 to 5'
opposite_col = 'Opposite rank from 1 to 5'
libero_col = 'Libero rank from 1 to 5'

df = pd.read_csv('/Users/bruno/volleyball/26-11-03-spond.csv')

df['Order'] = range(0, len(df))

df['Woman'] = df['Name'].apply(is_woman)

df['Sum_preferences'] = df[setter_col] + df[outside_col] + df[middle_col] + df[opposite_col] + df[libero_col]

df['Sum_preferences'] = df['Sum_preferences'].fillna(0)

df = df.sort_values(['Woman', 'Missing', 'Order'], ascending=[False, False, True], na_position='first')

print(df)

df = df.fillna(999)

print(df)

positions = {'setter': 3, 'outside': 6, 'middle': 6, 'opposite': 3, 'libero': 3, 'unknown': 21}

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

for player, preferences in players.items():
    #print(player, preferences)

    assignment, positions = assign_position(player, preferences, positions, assignment)
    #print(assignment, positions)

for n, (player, pos) in enumerate(assignment.items()):
    if pos == 'unknown':
        score = ''
    else:
        score = int(players[player][pos])
    print(f'{n+1}. {player} - {pos} - {score}')