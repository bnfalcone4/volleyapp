"""Display Spond event assignments in a local or Streamlit interface.

The app fetches upcoming events, normalizes assignment results for the three
supported modes, and renders assignments, waiting lists, and position totals.
"""

import argparse
import asyncio
import hmac
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ASSIGNMENT_MODES = ('ranked', 'flexible', 'optimized', 'strict')
MIN_PLAYERS_FOR_FLEXIBLE_ASSIGNMENT = 12
POSITION_LABELS = {
    'setter': 'Setter',
    'middle': 'Middle',
    'outside': 'Outside',
    'opposite': 'Oppo',
    'libero': 'Lib',
    'unknown': 'Unknown',
}
POSITION_PLURAL_LABELS = {
    'setter': 'Setters',
    'middle': 'Middles',
    'outside': 'Outsides',
    'opposite': 'Oppos',
    'libero': 'Libs',
    'unknown': 'Unknown',
}


def position_label(position, plural=False):
    """Return a consistent display label without changing the position key."""
    labels = POSITION_PLURAL_LABELS if plural else POSITION_LABELS
    return labels.get(position, position.title())


def load_fetch_module():
    """Load and return the Spond event-fetching module beside this file.

    Returns:
        The loaded module containing event fetching and cache functions.

    Raises:
        ImportError: If the fetch module cannot be found or loaded.
    """
    fetch_path = Path(__file__).with_name('check_spond.py')
    spec = importlib.util.spec_from_file_location('_spond_fetch', fetch_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load Spond fetch logic from {fetch_path}.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_assignment_module():
    """Load and return the repository's volleyball assignment module.

    Returns:
        The loaded module containing assignment algorithms and position limits.

    Raises:
        ImportError: If the assignment module cannot be found or loaded.
    """
    assignment_path = Path(__file__).resolve().parents[1] / 'spond.py'
    spec = importlib.util.spec_from_file_location(
        '_volley_assignment',
        assignment_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load assignment logic from {assignment_path}.')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def first_name_label(full_name, counts, seen):
    """Return a first-name label, disambiguating duplicate first names.

    Args:
        full_name: Player's full name.
        counts: Mapping of first names to their occurrence counts.
        seen: Mutable mapping tracking labels already emitted in this output.

    Returns:
        The first name, with an occurrence number when that name is duplicated.
    """
    first_name = full_name.split()[0] if full_name.split() else 'Unknown'
    seen[first_name] = seen.get(first_name, 0) + 1
    if counts[first_name] > 1:
        return f'{first_name} #{seen[first_name]}'
    return first_name


def default_position_limits(assignment_module, player_count):
    """Return CSV minimums and calculated maximums for a player count."""
    minimums_path = Path(__file__).resolve().parents[1] / 'min_positions.csv'
    minimums = assignment_module.load_minimums(minimums_path, player_count)
    maximums = assignment_module.load_maximums(player_count)
    return {
        position: (minimums[position], maximums[position])
        for position in assignment_module.FLEXIBLE_MAXIMUM_FACTORS
    }


def calculate_assignments(
    mode,
    players,
    assignment_module,
    event_capacity=None,
    signup_count=None,
    position_limits=None,
):
    """Run one assignment mode and return its results and position limits.

    Args:
        mode: Assignment algorithm name: ``ranked``, ``strict``, ``flexible``,
            or ``optimized``.
        players: Mapping of full player names to position preference ranks.
        assignment_module: Loaded module providing assignment algorithms and
            position-limit configuration.
        event_capacity: Maximum number of players assigned to the event.
        signup_count: Number of selected players to use for minimum lookup.
        position_limits: Optional mapping of positions to custom
            (minimum, maximum) counts for Flexible and Optimized modes.

    Returns:
        A pair of the algorithm's (assignments, waiting list) result and a
        mapping of positions to (minimum, maximum) counts.

    Raises:
        OSError, RuntimeError, ValueError: If limits cannot be loaded, the
            selected algorithm cannot run, or ``mode`` is unsupported.
    """
    if event_capacity is None:
        event_capacity = assignment_module.EVENT_CAPACITY

    if mode == 'ranked':
        limits = {
            position: (capacity, capacity)
            for position, capacity in assignment_module.EVENT_POSITIONS.items()
            if position != 'unknown'
        }
        return assignment_module.ranked_assignments(
            players,
            event_capacity=event_capacity,
        ), limits

    if mode == 'strict':
        limits = {
            position: (0, capacity)
            for position, capacity in assignment_module.EVENT_POSITIONS.items()
            if position != 'unknown'
        }
        return assignment_module.assign_strict(
            list(players.items()),
            event_capacity=event_capacity,
        ), limits

    if signup_count is None:
        signup_count = len(players)
    total = min(signup_count, event_capacity)
    default_limits = default_position_limits(assignment_module, total)
    if position_limits is None:
        position_limits = default_limits
    minimums = {
        position: limits[0] for position, limits in position_limits.items()
    }
    maximums = {
        position: limits[1] for position, limits in position_limits.items()
    }
    signup_order = list(players.items())
    limits = position_limits
    if mode == 'flexible':
        return assignment_module.assign_flexible(
            signup_order,
            minimums,
            event_capacity=event_capacity,
            maximums=maximums,
        ), limits
    if mode == 'optimized':
        return assignment_module.assign_hungarian(
            signup_order,
            minimums,
            event_capacity=event_capacity,
            maximums=maximums,
        ), limits
    raise ValueError(f'Unsupported assignment mode: {mode}.')


def edit_position_limits(mode, event, defaults, player_count, streamlit):
    """Render feasible position limits for one assignment mode."""
    limits = {}
    state = streamlit.session_state
    event_id = event.get('id', 'event')
    count_key = f'position_limit:{event_id}:{mode}:player_count'
    if state.get(count_key) != player_count:
        for position, (minimum, maximum) in defaults.items():
            state[
                f'position_limit_widget:{event_id}:{mode}:{position}:min'
            ] = minimum
            state[
                f'position_limit_widget:{event_id}:{mode}:{position}:max'
            ] = maximum
        state[count_key] = player_count

    for position, (default_minimum, default_maximum) in defaults.items():
        minimum_key = f'position_limit_widget:{event_id}:{mode}:{position}:min'
        maximum_key = f'position_limit_widget:{event_id}:{mode}:{position}:max'
        state.setdefault(minimum_key, default_minimum)
        state.setdefault(maximum_key, default_maximum)
        maximum = min(max(0, state[maximum_key]), player_count)
        minimum = min(max(0, state[minimum_key]), maximum)
        state[minimum_key] = minimum
        state[maximum_key] = maximum
        limits[position] = [minimum, maximum]

    minimum_total = sum(values[0] for values in limits.values())
    for values in reversed(list(limits.values())):
        reduction = min(values[0], minimum_total - player_count)
        values[0] -= max(0, reduction)
        minimum_total -= max(0, reduction)

    maximum_total = sum(values[1] for values in limits.values())
    for values in limits.values():
        increase = min(player_count - values[1], player_count - maximum_total)
        values[1] += max(0, increase)
        maximum_total += max(0, increase)

    with streamlit.expander('Adjust min/max position limits'):
        streamlit.caption(
            f'{player_count} active players (excluding the waitlist). '
            'Minimum and maximum totals must accommodate them.'
        )
        for position, values in limits.items():
            minimum_key = (
                f'position_limit_widget:{event_id}:'
                f'{mode}:{position}:min'
            )
            maximum_key = minimum_key[:-3] + 'max'
            state[minimum_key], state[maximum_key] = values
            other_minimums = sum(
                limits[other][0] for other in limits if other != position
            )
            minimum_maximum = min(
                state[maximum_key],
                player_count - other_minimums,
            )
            minimum = state[minimum_key]
            other_maximums = sum(
                limits[other][1] for other in limits if other != position
            )
            maximum_minimum = max(
                minimum,
                player_count - other_maximums,
            )
            maximum = state[maximum_key]
            with streamlit.container(
                horizontal=True,
                wrap=False,
                vertical_alignment='center',
                gap='small',
            ):
                streamlit.markdown(
                    f'**{position_label(position, plural=True)}:**',
                    width=96,
                    wrap=False,
                )
                minimum = streamlit.number_input(
                    'Min',
                    min_value=0,
                    max_value=minimum_maximum,
                    step=1,
                    key=minimum_key,
                    width=150, #120 shows +/- in desktop but not android
                    label_visibility='collapsed',
                )
                limits[position][0] = minimum
                maximum_minimum = max(
                    minimum,
                    player_count - other_maximums,
                )
                maximum = streamlit.number_input(
                    'Max',
                    min_value=maximum_minimum,
                    max_value=player_count,
                    step=1,
                    key=maximum_key,
                    width=150,
                    label_visibility='collapsed',
                )
                limits[position][1] = maximum

    return {
        position: (minimum, maximum)
        for position, (minimum, maximum) in limits.items()
    }


def order_events_from_today(events, today=None):
    """Order upcoming events chronologically, then past events newest first."""
    if today is None:
        today = datetime.now(timezone.utc).date()

    def sort_key(indexed_event):
        index, event = indexed_event
        start = datetime.fromisoformat(
            event['startTimestamp'].replace('Z', '+00:00')
        )
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        start = start.astimezone(timezone.utc)
        if start.date() >= today:
            return (0, start.timestamp(), index)
        return (1, -start.timestamp(), index)

    return [
        event
        for _, event in sorted(enumerate(events), key=sort_key)
    ]


def assignment_rows(mode, result, players):
    """Normalize an algorithm result into assignment and waiting-list rows.

    Args:
        mode: Assignment algorithm name.
        result: Pair returned by the selected assignment algorithm.
        players: Mapping of full player names to position preference ranks.

    Returns:
        A pair of assignment rows (name, position, rank) and waiting rows
        (name, preferred positions).
    """
    assignments, waiting = result
    if mode == 'ranked':
        rows = [
            (name, position, players[name].get(position))
            for name, position in assignments.items()
        ]
        waiting_rows = list(waiting.items())
    else:
        rows = assignments
        waiting_rows = waiting
    return rows, waiting_rows


def cascade_rows(assignments, limits, players):
    """Return assigned players waiting for a better-ranked position.

    Players are returned in signup order, and only blocked preferences ranked
    higher than their current assignment are included.
    """
    assigned_positions = {
        name: position for name, position, _ in assignments
    }
    position_counts = {
        position: sum(
            assigned_position == position
            for assigned_position in assigned_positions.values()
        )
        for position in limits
    }
    full_positions = {
        position
        for position, (_, maximum) in limits.items()
        if position_counts[position] >= maximum
    }
    cascade = []
    for name, preferences in players.items():
        if name not in assigned_positions:
            continue
        current_position = assigned_positions[name]
        current_rank = preferences.get(current_position)
        improvements = [
            (position, preferences[position])
            for position in preferences
            if position in full_positions
            and (
                current_rank is None
                or preferences[position] < current_rank
            )
        ]
        if improvements:
            cascade.append((name, improvements))
    return cascade


def display_assignments(
    assignments,
    waiting,
    limits,
    players,
    assignment_module,
    streamlit=None,
    visualization='positions',
    cascade=(),
):
    """Render assignments in position or signup order, plus assignment totals.

    Args:
        assignments: Iterable of (name, position, preference rank) rows.
        waiting: Iterable of (name, preferred positions) rows.
        limits: Mapping of positions to (minimum, maximum) counts.
        players: Mapping of all full player names to their preferences, used
            to disambiguate duplicate first names.
        assignment_module: Loaded module providing the preference-rank tally.
        streamlit: Optional Streamlit API object. When omitted, output is
            printed to the terminal.
        visualization: ``positions`` to group by position or ``order`` to list
            assignments in signup order.
        cascade: Assigned players and their blocked, better-ranked positions.

    Returns:
        None. Writes the result to Streamlit or standard output.
    """
    counts = {}
    for full_name in players:
        first_name = full_name.split()[0] if full_name.split() else 'Unknown'
        counts[first_name] = counts.get(first_name, 0) + 1
    seen = {}

    write = streamlit.write if streamlit else print
    markdown = streamlit.markdown if streamlit else print
    if visualization == 'positions':
        position_sections = (
            ('setter', position_label('setter', plural=True), '👐'),
            ('middle', position_label('middle', plural=True), '🙌'),
            ('outside', position_label('outside', plural=True), '🤚'),
            ('opposite', position_label('opposite', plural=True), '✋'),
            ('libero', position_label('libero', plural=True), '👊'),
        )
        assignments_by_position = {
            position: [] for position, _, _ in position_sections
        }
        unknown_assignments = []
        for assignment in assignments:
            if assignment[1] == 'unknown':
                unknown_assignments.append(assignment)
            elif assignment[1] in assignments_by_position:
                assignments_by_position[assignment[1]].append(assignment)

        for position, label, emoji in position_sections:
            markdown(f'**{label}: {emoji}**' if streamlit else f'{label}: {emoji}')
            for index, (full_name, _, rank) in enumerate(
                assignments_by_position[position], start=1
            ):
                name = first_name_label(full_name, counts, seen)
                rank_text = f'(rank {rank})' if rank is not None else '(no preference)'
                write(f'{index}. {name} {rank_text}')

        if unknown_assignments:
            markdown('**Unknown: ❓**' if streamlit else 'Unknown: ❓')
            for index, (full_name, _, rank) in enumerate(
                unknown_assignments, start=1
            ):
                name = first_name_label(full_name, counts, seen)
                rank_text = f'(rank {rank})' if rank is not None else '(no preference)'
                write(f'{index}. {name} {rank_text}')

        assigned_names = {name for name, _, _ in assignments}
        unassigned_waiting = [
            (name, preferences)
            for name, preferences in waiting
            if name not in assigned_names
        ]
        if unassigned_waiting:
            markdown('**📝 Waitlist:**' if streamlit else '📝 Waitlist:')
            for full_name, _ in unassigned_waiting:
                write(first_name_label(full_name, counts, seen))
    else:
        markdown('**Assignments**' if streamlit else 'Assignments:')
        for index, (full_name, position, rank) in enumerate(assignments, start=1):
            first_name = first_name_label(full_name, counts, seen)
            rank_text = f' (rank {rank})' if rank is not None else ''
            separator = ' — ' if streamlit else ' - '
            write(
                f'{index}. {first_name}{separator}'
                f'{position_label(position)}{rank_text}'
            )

        markdown('**Waiting list**' if streamlit else 'Waiting list:')
        assigned_names = {name for name, _, _ in assignments}
        actual_waiting = [
            (name, preferences)
            for name, preferences in waiting
            if name not in assigned_names
        ]
        if actual_waiting:
            for full_name, preferences in actual_waiting:
                first_name = first_name_label(full_name, counts, seen)
                preference_text = (
                    f' — {", ".join(position_label(position) for position in preferences)}'
                    if preferences
                    else ''
                )
                write(f'{first_name}{preference_text}')
        else:
            write('Nobody waiting.')

    if cascade:
        write('')
        markdown('**Cascade:**' if streamlit else 'Cascade:')
        for full_name, improvements in cascade:
            name = first_name_label(full_name, counts, seen)
            positions = ', '.join(
                position_label(position) for position, _ in improvements
            )
            write(f'{name} — {positions}')

    write('')
    markdown('**Position totals:**' if streamlit else 'Position totals:')
    for position, (minimum, maximum) in limits.items():
        total = sum(row[1] == position for row in assignments)
        write(
            f'{position_label(position, plural=True)}: {total} '
            f'(min {minimum}, max {maximum})'
        )

    write('')
    rank_totals, rank_total = assignment_module.preference_rank_totals(assignments)
    markdown('**Preference rank totals:**' if streamlit else 'Preference rank totals:')
    for rank, total in rank_totals.items():
        write(f'Rank {rank}: {total}')
    write(f'Total: {rank_total}')
    ranked_player_count = sum(rank_totals.values())
    average_rank = (
        rank_total / ranked_player_count if ranked_player_count else 0
    )
    write(f'Average: {average_rank:.2f}')


def edit_event_attendance(
    event,
    players,
    assignment_module,
    streamlit,
    event_capacity=None,
):
    """Render attendance checkboxes and return only selected players.

    The first event-capacity players default to attending; later players
    (initially on the waiting list) default to not attending. Checkbox state is
    stored per event and player in Streamlit's session state. Each checkbox
    change reruns the app and recalculates the assignment lists.

    Args:
        event: Event mapping used to create stable attendance widget keys.
        players: Mapping of player names to normalized preference ranks.
        assignment_module: Loaded module providing event-capacity settings.
        streamlit: Streamlit API object providing session state and widgets.

    Returns:
        A player-to-preferences mapping containing only checked players, in
        their original signup order.
    """
    selected_players = {}
    if event_capacity is None:
        event_capacity = assignment_module.EVENT_CAPACITY
    with streamlit.expander('Edit attendance'):
        streamlit.caption(
            'Checked players are attending. Players beyond event capacity '
            'start unchecked. Assignments update when attendance changes.'
        )
        for index, (name, preferences) in enumerate(players.items()):
            key = f'attendance:{event.get("id", "event")}:{name}'
            if key not in streamlit.session_state:
                streamlit.session_state[key] = (
                    index < event_capacity
                )
            if streamlit.checkbox(name, key=key):
                selected_players[name] = preferences
        streamlit.caption(
            f'{len(selected_players)} of {len(players)} players marked attending.'
        )
    return selected_players


def display_event(event, assignment_module, streamlit=None):
    """Calculate and display all assignment modes for one event.

    Args:
        event: Event mapping with heading, start/end timestamps, and a
            ``players`` preference mapping.
        assignment_module: Loaded module providing assignment algorithms.
        streamlit: Optional Streamlit API object. When omitted, output is
            printed to the terminal.

    Returns:
        None. Displays the event's assignments and reports per-mode calculation
        errors through the selected output interface.
    """
    players = assignment_module.normalize_player_preferences(event['players'])
    signup_players = players
    if streamlit:
        capacity_key = f'player_cap:{event.get("id", "event")}'
        spond_capacity = event.get('maxAccepted')
        if spond_capacity is None:
            spond_capacity = assignment_module.EVENT_CAPACITY
        if (
            isinstance(spond_capacity, bool)
            or not isinstance(spond_capacity, int)
            or spond_capacity < 1
        ):
            raise ValueError(
                f'Invalid maximum number of participants for event '
                f'{event.get("id", "event")}: {spond_capacity!r}.'
            )
        if capacity_key not in streamlit.session_state:
            streamlit.session_state[capacity_key] = spond_capacity
        event_capacity = streamlit.session_state[capacity_key]
        players = edit_event_attendance(
            event,
            players,
            assignment_module,
            streamlit,
            event_capacity,
        )
    else:
        event_capacity = assignment_module.EVENT_CAPACITY
    signup_count = len(players)
    start = datetime.fromisoformat(event['startTimestamp'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(event['endTimestamp'].replace('Z', '+00:00'))
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    title = event.get('heading') or 'Untitled event'
    date_line = f'{start:%Y-%m-%d} · {start:%H:%M}–{end:%H:%M} UTC'

    if streamlit:
        streamlit.subheader(title)
        streamlit.caption(date_line)
        attending_count = min(len(players), event_capacity)
        waiting_count = max(0, len(players) - event_capacity)
        absent_count = len(signup_players) - len(players)
        summary = (
            f'Attending: {attending_count} ({event_capacity} cap)  \n'
            f'Waiting list: {waiting_count}'
        )
        if absent_count:
            summary += f'  \nAbsent: {absent_count}'
        streamlit.markdown(summary)
        visualization_key = f'list_visualization:{event.get("id", "event")}'
        visualization = streamlit.session_state.get(
            visualization_key,
            'positions',
        )
        cascade_key = f'show_cascade:{event.get("id", "event")}'
        show_cascade = streamlit.session_state.get(cascade_key, 'no') == 'yes'
        active_player_count = min(len(players), event_capacity)
        mode_descriptions = {
            'ranked': 'First come first based',
            'strict': (
                'Assigns top preference in sign up order and stops when not possible'
            ),
            'flexible': 'First come first based with flexible position limits',
            'optimized': "Optimized to maximize players' preferences",
        }
        tabs = streamlit.tabs([mode.title() for mode in ASSIGNMENT_MODES])
        for mode, tab in zip(ASSIGNMENT_MODES, tabs):
            with tab:
                streamlit.caption(mode_descriptions[mode])
                if (
                    mode in ('flexible', 'optimized')
                    and active_player_count < MIN_PLAYERS_FOR_FLEXIBLE_ASSIGNMENT
                ):
                    streamlit.info(
                        'Cannot assign Flexible/Optimized positions with less than '
                        '12 players, use Ranked mode'
                    )
                    continue
                try:
                    position_limits = None
                    if mode in ('flexible', 'optimized'):
                        defaults = default_position_limits(
                            assignment_module,
                            active_player_count,
                        )
                        position_limits = edit_position_limits(
                            mode,
                            event,
                            defaults,
                            active_player_count,
                            streamlit,
                        )
                    result, limits = calculate_assignments(
                        mode,
                        players,
                        assignment_module,
                        event_capacity=event_capacity,
                        signup_count=signup_count,
                        position_limits=(
                            position_limits
                            if mode in ('flexible', 'optimized')
                            else None
                        ),
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    streamlit.error(f'Could not calculate {mode} assignments: {error}')
                    continue
                assignments, waiting = assignment_rows(
                    mode, result, players
                )
                display_assignments(
                    assignments,
                    waiting,
                    limits,
                    players,
                    assignment_module,
                    streamlit=streamlit,
                    visualization=visualization,
                    cascade=(
                        cascade_rows(assignments, limits, players)
                        if show_cascade
                        else ()
                    ),
                )
        streamlit.markdown('**Visualize by:**')
        streamlit.radio(
            'Visualize by',
            ('positions', 'order'),
            format_func=str.title,
            horizontal=True,
            label_visibility='collapsed',
            key=visualization_key,
        )
        streamlit.markdown('**Show cascade:**')
        streamlit.radio(
            'Show cascade',
            ('no', 'yes'),
            format_func=str.title,
            horizontal=True,
            label_visibility='collapsed',
            key=cascade_key,
        )
        streamlit.markdown('**Player cap:**')
        streamlit.number_input(
            'Player cap',
            min_value=1,
            step=1,
            label_visibility='collapsed',
            key=capacity_key,
        )
        return

    print(f'\n{title}')
    print(date_line)
    for mode in ASSIGNMENT_MODES:
        print(f'\n{mode.title()}')
        try:
            result, limits = calculate_assignments(
                mode,
                players,
                assignment_module,
                event_capacity=event_capacity,
                signup_count=signup_count,
            )
        except (OSError, RuntimeError, ValueError) as error:
            print(f'Could not calculate {mode} assignments: {error}')
            continue
        assignments, waiting = assignment_rows(mode, result, players)
        display_assignments(
            assignments,
            waiting,
            limits,
            players,
            assignment_module,
        )


def local_main(from_json=False):
    """Load cached or live Spond events and print every assignment mode.

    Reads the event cache when ``from_json`` is true. Otherwise, reads Spond
    credentials from the repository-root ``.env``, fetches events, and saves
    the event cache before printing assignments.

    Returns:
        None.

    Raises:
        SystemExit: If required credentials are missing for a live fetch.
    """
    fetch_module = load_fetch_module()
    if from_json:
        events = fetch_module.load_event_cache()
        print('Loaded saved event data from upcoming_events.json.')
    else:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / '.env')
        username = os.environ.get('SPOND_USERNAME')
        password = os.environ.get('SPOND_PASSWORD')
        group_id = os.environ.get('SPOND_GROUP_ID')
        if not username or not password or not group_id:
            raise SystemExit(
                'Set SPOND_USERNAME, SPOND_PASSWORD, and SPOND_GROUP_ID before running locally.'
            )

        events = asyncio.run(
            fetch_module.fetch_upcoming_events(username, password, group_id)
        )
        cache_path = fetch_module.save_event_cache(events, group_id)
        print(f'Saved live event data to {cache_path}.')

    if not events:
        print('No events were found in the selected source.')
        return

    assignment_module = load_assignment_module()
    for event in events:
        display_event(event, assignment_module)


def streamlit_main(from_json=False):
    """Run the password-protected Streamlit interface for Spond events.

    Reads cached events when ``from_json`` is true. Otherwise, reads app and
    Spond credentials from Streamlit secrets or environment variables, fetches
    events, saves the event cache, and renders the selected event.

    Returns:
        None. Writes UI content and authentication state through Streamlit.
    """
    import streamlit as st

    fetch_module = load_fetch_module()
    st.set_page_config(page_title='VolleyApp', page_icon='🏐')
    st.title('VolleyApp 🏐')
    st.write(
        'Event assignments from saved JSON data.'
        if from_json
        else 'Upcoming open events and position assignments from live Spond data.'
    )

    try:
        configured = st.secrets
    except (FileNotFoundError, KeyError):
        configured = {}

    app_password = configured.get('app_password') or os.environ.get(
        'STREAMLIT_APP_PASSWORD'
    )
    if not app_password:
        st.error('Configure STREAMLIT_APP_PASSWORD before making this app available.')
        return

    if not st.session_state.get('authenticated'):
        with st.form('app_login'):
            supplied_password = st.text_input('App password', type='password')
            login_submitted = st.form_submit_button('Log in')
        if login_submitted:
            if hmac.compare_digest(supplied_password, app_password):
                st.session_state['authenticated'] = True
                st.rerun()
            st.error('Incorrect app password.')
        return

    if (
        'events' not in st.session_state
        and 'events_load_error' not in st.session_state
    ):
        if from_json:
            try:
                events = fetch_module.load_event_cache()
            except (OSError, ValueError) as error:
                st.session_state['events_load_error'] = str(error)
        else:
            spond_config = configured.get('spond', {})
            username = spond_config.get('username') or os.environ.get('SPOND_USERNAME')
            password = spond_config.get('password') or os.environ.get('SPOND_PASSWORD')
            group_id = spond_config.get('group_id') or os.environ.get('SPOND_GROUP_ID')
            if not username or not password or not group_id:
                st.error('Configure Spond credentials and group ID in Streamlit secrets.')
                return

            try:
                events = asyncio.run(
                    fetch_module.fetch_upcoming_events(username, password, group_id)
                )
                fetch_module.save_event_cache(events, group_id)
            except (ImportError, OSError, ValueError, KeyError) as error:
                st.session_state['events_load_error'] = str(error)

        if 'events_load_error' not in st.session_state:
            st.session_state['events'] = [
                {
                    'id': event['id'],
                    'heading': event['heading'],
                    'startTimestamp': event['startTimestamp'],
                    'endTimestamp': event['endTimestamp'],
                    'maxAccepted': event.get('maxAccepted'),
                    'players': event['players'],
                }
                for event in events
            ]

    if 'events_load_error' in st.session_state:
        st.error(
            'Could not load Spond events: '
            f'{st.session_state["events_load_error"]} Reload the app to retry.'
        )
        return

    events = order_events_from_today(st.session_state.get('events', []))
    if not events:
        st.info('No upcoming events with open sign-up were found.')
        return

    def event_label(event):
        """Format an event's heading and UTC start time for the selector.

        Args:
            event: Event mapping with an optional heading and start timestamp.

        Returns:
            A display label containing the event title and UTC date and time.
        """
        start = datetime.fromisoformat(event['startTimestamp'].replace('Z', '+00:00'))
        return f"{event.get('heading') or 'Untitled event'} — {start:%Y-%m-%d %H:%M} UTC"

    selected_index = st.selectbox(
        'Event',
        range(len(events)),
        format_func=lambda index: event_label(events[index]),
    )
    assignment_module = load_assignment_module()
    display_event(events[selected_index], assignment_module, streamlit=st)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--from-json',
        action='store_true',
        help='Load saved events from check_spond/upcoming_events.json without accessing Spond.',
    )
    args, _ = parser.parse_known_args()

    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        get_script_run_ctx = None

    if get_script_run_ctx is not None and get_script_run_ctx() is not None:
        streamlit_main(from_json=args.from_json)
    else:
        local_main(from_json=args.from_json)
