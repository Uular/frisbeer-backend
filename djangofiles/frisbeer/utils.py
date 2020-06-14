import itertools
from operator import itemgetter
from typing import Sequence

from django.conf import settings


def calculate_team_elo(players):
    return int(sum([player.elo for player in players]) / len(players))


def calculate_elo_change(my_elo, opponent_elo, win):
    """
    Calculates the elo change that should be applied
    :param my_elo: Elo of the entity whose elo change is being calculated
    :param opponent_elo: Elo of the opposing entity
    :param win: True if the first player won, False if lost.
    :return: Elo change to be applied to the first entity.
             Opposing player's change is given through multiplication by -1
    """
    if win:
        actual_score = 1
    else:
        actual_score = 0
    Ra = my_elo
    Rb = opponent_elo
    Ea = 1 / (1 + 10 ** ((Rb - Ra) / 400))
    return settings.ELO_K * (actual_score - Ea)


def create_equal_teams(players):
    """
    Creates teams with as close elo average as possible
    :param players: Sequence of players to create teams from
    :return: Tuple containing: Elo difference between the teams; players in team 1; players in team 2
    """

    elo_list = []
    players_in_team = len(players) // 2
    possibilities = itertools.combinations(players, players_in_team)

    for team1 in possibilities:
        team2 = players - set(team1)
        elo1 = calculate_team_elo(team1)
        elo2 = calculate_team_elo(team2)
        elo_list.append((abs(elo1 - elo2), team1, team2))
    ideal_teams = sorted(elo_list, key=itemgetter(0))[0]
    return ideal_teams
