"""Print position assignments and waiting lists from a YAML configuration.

Usage:
    python volley.py CONFIG.yaml

The YAML file is expected to map each position name to an ordered player list.
The script prints each position's capacity, assigned players, waiting players,
and a per-player summary of requested positions.
"""

import hashlib
import random
import yaml
import sys

from pathlib import Path

# text = Path('volley.txt').read_text()

# hashobj = hashlib.sha256(b"Friday 23rd Oct 12-2pm Gryphon.")
# val = int.from_bytes(hashobj.digest(), 'big')

# random.seed(val)
# random.random()

input = sys.argv[1]
with open(input) as f:
    config = yaml.safe_load(f)

#config = {'outside': ['Seb', 'Cy', 'Alif', 'Abdulaziz', 'Sid', 'Tarik', 'Bruno'], 'opposite': ['Cat', 'Yosef', 'Annalisa'], 'libero': ['Seb', 'Ryan', 'Gabriel'], 'middle': ['Kodi', 'Theo'], 'setter': ['Zoe']}
# print(config)

positions = {'Setters': 3, 'Middles': 6, 'Outsides': 6, 'Opposites': 3, 'Liberos': 3}

new_config = {}

for position, capacity in positions.items():

    players = list(reversed(config[position]))

    new_config[position] = players

    print(f'{position}:')

    for i, player in enumerate(players[:capacity]):

        print(f'{i+1}. {player}')

    if i + 1 < capacity:
        for j in range(i+1, capacity):
             print(f'{j+1}.')

    print()

for position, capacity in positions.items():

    print(f'Waiting {position}:')

    for player in new_config[position][capacity:]:
        print(player)

    print()


preferences = {}

print(config)

for position, players in config.items():

    for player in players:
        if player in preferences:
            preferences[player].append(position)
        else:
            preferences[player] = [position]


for key, val in preferences.items():
    print(key, val)
