from collections import OrderedDict, defaultdict
from math import exp

import logging
from django.contrib.auth.models import User
from django.db.models import Sum
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token

from server import settings

from frisbeer.models import *

from scipy.stats import zscore

ranks = list(Rank.objects.all())

rank_distribution = OrderedDict()
step = 6 / (len(ranks) - 2)
for i in range(len(ranks) - 2):
    rank_distribution[-3 + i * step] = ranks[i]


@receiver(m2m_changed, sender=Game.team2.through)
@receiver(m2m_changed, sender=Game.team1.through)
@receiver(post_save, sender=Game)
def update_statistics(sender, instance, **kwargs):
    if not instance.team1.exists() or not instance.team2.exists():
        logging.debug("Game was saved, but hasn't been played yet")
        return

    update_elo()
    update_score()
    calculate_ranks()


def update_elo():
    """
    Calculate new elos for all players. 
    
    Update is done for all players because matches are possibly added in non-chronological order
    """
    logging.info("Updating elos (mabby)")

    def calculate_elo_change(player, opponent_elo, win):
        if win:
            actual_score = 1
        else:
            actual_score = 0
        Ra = player
        Rb = opponent_elo
        Ea = 1 / (1 + 10 ** ((Rb - Ra) / 400))
        return settings.ELO_K * (actual_score - Ea)

    def calculate_team_elo(team):
        return sum([player.elo for player in team]) / len(team)

    games = Game.objects.filter(approved=True).order_by("date")
    Player.objects.all().update(elo=1500)

    for game in games:
        team1 = list(game.team1.all())
        team2 = list(game.team2.all())
        team2_pregame_elo = calculate_team_elo(team2)
        team1_pregame_elo = calculate_team_elo(team1)
        for player in team1:
            player_elo_change = 0
            player_elo_change += game.team1_score * calculate_elo_change(team1_pregame_elo, team2_pregame_elo, True)
            player_elo_change += game.team2_score * calculate_elo_change(team1_pregame_elo, team2_pregame_elo, False)
            player.elo += player_elo_change
            logging.debug("{0} elo changed {1:0.2f}".format(player.name, player_elo_change))
            player.save()
        for player in team2:
            player_elo_change = 0
            player_elo_change += game.team2_score * calculate_elo_change(team2_pregame_elo, team1_pregame_elo, True)
            player_elo_change += game.team1_score * calculate_elo_change(team2_pregame_elo, team1_pregame_elo, False)
            player.elo += player_elo_change
            logging.debug("{0} elo changed {1:0.2f}".format(player.name, player_elo_change))
            player.save()


def update_score():
    logging.info("Updating scores (mabby)")

    def calculate_score(player):
        if player['games'] == 0:
            return 0
        return int((player['wins'] / player['rounds']) * (1 - exp(-player['games'] / 4)) * 1000)

    games = Game.objects.all()

    players = {}
    for game in games:
        team1 = game.team1.all()
        team2 = game.team2.all()
        for team in [team1, team2]:
            for player in team:
                if not player in players:
                    players[player] = defaultdict(int)
                players[player]['games'] += 1
                players[player]['wins'] += game.team1_score if team is team1 else game.team2_score
                players[player]['rounds'] += game.team1_score + game.team2_score

    for player, data in players.items():
        old_score = player.score
        player.score = calculate_score(data)
        if old_score != player.score:
            logging.debug("{} old score: {}, new score {}".format(player.name, old_score, player.score))
            player.save()


def calculate_ranks():
    """
    Calculate new ranks for all layers
    """
    logging.info("Calculating new ranks")
    Player.objects.update(rank_link=None)
    team1_scores = Player.objects.annotate(score1=Sum('team1__team1_score'))
    team2_scores = Player.objects.annotate(score2=Sum('team2__team2_score'))
    player_list = []
    for player in list(team1_scores):
        s1 = player.score1 if player.score1 is not None else 0
        player2 = team2_scores.get(id=player.id)
        s2 = player2.score2 if player2.score2 is not None else 0
        if s1 + s2 >= 4:
            player_list.append(player)
    if not player_list:
        logging.debug("No players with four round victories")
        return
    scores = [player.score for player in player_list]
    if len(set(scores)) == 1:
        logging.debug("Only one player {} with rank".format(player_list[0]))
        z_scores = [0.0 for i in range(len(player_list))]
    else:
        z_scores = zscore(scores)
        logging.debug("Z_scores: {}".format(z_scores))

    for i in range(len(player_list)):
        player_z_score = z_scores[i]
        player = player_list[i]
        for required_z_score in rank_distribution.keys():
            if player_z_score > required_z_score:
                rank = rank_distribution[required_z_score]
                player.rank_link = rank
            else:
                break
        logging.debug("Setting rank {} for {}".format(player.rank_link, player.name))
        player.save()


@receiver(post_save, sender=User)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)
