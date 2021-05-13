import logging

from collections import OrderedDict, defaultdict

from scipy.stats import zscore
from django.contrib.auth.models import User
from django.db.models import F, Sum
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token

from frisbeer.models import *
from frisbeer.utils import *


@receiver(m2m_changed, sender=Game.players.through)
@receiver(post_save, sender=Game)
def update_statistics(sender, instance, **kwargs):
    if not instance or not instance.can_score():
        logging.debug("Game was saved, but hasn't been played yet. Sender %s, instance %s", sender, instance)
        return

    update_elo()
    update_score()
    calculate_ranks()
    update_team_score()


def update_elo():
    """
    Calculate new elos for all players.

    Update is done for all players because matches are possibly added in non-chronological order
    """

    logging.info("Updating elos (mabby)")

    def _elo_decay():
        # Halves the distance from median elo for all players
        Player.objects.all().update(elo=(F('elo') - 1500) / 2 + 1500, season_best=0)

    games = Game.objects.filter(state=Game.APPROVED).order_by("date")

    Player.objects.all().update(elo=1500, season_best=0)

    season = None

    for game in games:
        if not game.can_score():
            continue
        # Perform elo decay before first game of each season
        if season is None:
            season = game.season
        elif game.season and game.season != season:
            logging.debug(f'Doing elo decay between seasons {season.name} and {game.season.name}')
            _elo_decay()
            season = game.season

        team1 = [r.player for r in list(game.gameplayerrelation_set.filter(team=1))]
        team2 = [r.player for r in list(game.gameplayerrelation_set.filter(team=2))]
        team2_pregame_elo = calculate_team_elo(team2)
        team1_pregame_elo = calculate_team_elo(team1)

        # We only need to calculate elo change for one team, since elo change is the same for all players
        # and symmetrical between losing and winning sides
        team1_elo_change = (game.team1_score * calculate_elo_change(team1_pregame_elo, team2_pregame_elo, True)
                            + game.team2_score * calculate_elo_change(team1_pregame_elo, team2_pregame_elo, False))

        for player in team1:
            player.elo += team1_elo_change
            # logging.debug("{0} elo changed {1:0.2f}".format(player.name, team1_elo_change))
            if player.elo > player.season_best:
                player.season_best = player.elo
            player.save()
        for player in team2:
            player.elo -= team1_elo_change
            # logging.debug("{0} elo changed {1:0.2f}".format(player.name, -team1_elo_change))
            if player.elo > player.season_best:
                player.season_best = player.elo
            player.save()

    # New season has begun, but no games yet played -> decay
    if season != Season.current():
        _elo_decay()


def update_score():
    logging.info("Updating scores (mabby)")

    season = Season.current()
    games = Game.objects.filter(season_id=season.id, state=Game.APPROVED)

    # Reset all scores to 0
    Player.objects.all().update(score=0)

    players = {}
    for game in games:
        team1 = [r.player for r in game.gameplayerrelation_set.filter(team=1)]
        team2 = [r.player for r in game.gameplayerrelation_set.filter(team=2)]
        for team in [team1, team2]:
            for player in team:
                if not player in players:
                    players[player] = defaultdict(int)
                players[player]['games'] += 1
                players[player]['wins'] += game.team1_score if team is team1 else game.team2_score
                players[player]['rounds'] += game.team1_score + game.team2_score

    for player, data in players.items():
        old_score = player.score
        player.score = season.score(games_played=data['games'],
                                    rounds_played=data['rounds'],
                                    rounds_won=data['wins'],
                                    player=player)
        if old_score != player.score:
            logging.debug("{} old score: {}, new score {}".format(player.name, old_score, player.score))
            player.save()


BACKUP_PENALTY_PERCENT = 22.45


def update_team_score():
    Team.objects.filter(virtual=True).delete()
    Team.objects.all().update(elo=1500, season_best=0)
    season = Season.current()
    games = Game.objects.filter(season=season, state=Game.APPROVED).order_by("date")

    for game in games:
        if not game.can_score():
            continue
        team1 = Team.find_or_create(season, [r.player for r in list(game.gameplayerrelation_set.filter(team=1))])
        team2 = Team.find_or_create(season, [r.player for r in list(game.gameplayerrelation_set.filter(team=2))])

        GameTeamRelation.objects.update_or_create(side=1, game=game, defaults={'team': team1})
        GameTeamRelation.objects.update_or_create(side=2, game=game, defaults={'team': team2})

        team1_elo_change = (game.team1_score * calculate_elo_change(team1.elo, team2.elo, True) +
                            game.team2_score * calculate_elo_change(team1.elo, team2.elo, False))

        team2_elo_change = -team1_elo_change

        winning_team = team1 if game.team1_score > game.team2_score else team2
        if any(p.backup for p in winning_team.team_players.all()):
            penalty_factor = 1 - (BACKUP_PENALTY_PERCENT / 100)
            if winning_team is team1 and team1_elo_change > 0:
                team1_elo_change *= penalty_factor
            elif team2_elo_change > 0:
                team2_elo_change *= penalty_factor

        team1.elo += team1_elo_change
        if team1.elo > team1.season_best:
            team1.season_best = team1.elo
        team1.save()
        team2.elo += team2_elo_change
        if team2.elo > team2.season_best:
            team2.season_best = team2.elo
        team2.save()


def calculate_ranks():
    """
    Calculate ranks new ranks
    :return: None
    """
    logging.info("Calculating new ranks")

    ranks = list(Rank.objects.all())
    rank_distribution = OrderedDict()
    step = 6 / (len(ranks) - 2)
    for i in range(len(ranks) - 2):
        rank_distribution[-3 + i * step] = ranks[i]

    season = Season.current()
    players = Player.objects.all()
    players.update(rank=None)
    ranked_players_list = []
    stat = season.rules.rank_statistic
    for player in players:
        logging.info(f'Calculating ranks for player {player} with stat {stat}')
        if stat == PlayerStatistic.GAMES_PLAYED:
            value = player.gameplayerrelation_set.filter(game__season_id=season.id).count()
        elif stat == PlayerStatistic.GAMES_WON:
            gw1 = player.gameplayerrelation_set.filter(team=1,
                   game__season_id=season.id,
                   game__team1_score__gt=F('game__team2_score')).count()
            gw2 = player.gameplayerrelation_set.filter(team=2,
                   game__season_id=season.id,
                   game__team2_score__gt=F('game__team1_score'))
            value = gw1 + gw2
        elif stat == PlayerStatistic.ROUNDS_WON:
            rw1 = player.gameplayerrelation_set.filter(team=1, game__season_id=season.id) \
                       .aggregate(Sum('game__team1_score'))["game__team1_score__sum"] or 0
            rw2 = player.gameplayerrelation_set.filter(team=2, game__season_id=season.id) \
                       .aggregate(Sum('game__team2_score'))["game__team2_score__sum"] or 0
            value = rw1 + rw2
        logging.info(f'Value is {value}, comparing to {season.rules.rank_min_value}')
        if value >= season.rules.rank_min_value:
            ranked_players_list.append(player)

    if not ranked_players_list:
        logging.debug("No players with rank criteria")
        for player in players:
            player.rank = None
            player.save()
        return

    scores = [player.score for player in ranked_players_list]
    if len(set(scores)) == 1:
        logging.debug("Only one player {} with rank".format(ranked_players_list[0]))
        z_scores = [0.0 for i in range(len(ranked_players_list))]
    else:
        z_scores = zscore(scores)
        logging.debug("Players: {}".format(ranked_players_list))
        logging.debug("Z_scores: {}".format(z_scores))

    for i in range(len(ranked_players_list)):
        player_z_score = z_scores[i]
        player = ranked_players_list[i]
        rank = None
        for required_z_score in rank_distribution.keys():
            if player_z_score > required_z_score:
                rank = rank_distribution[required_z_score]
            else:
                break
        logging.debug("Setting rank {} for {}".format(rank, player.name))
        player.rank = rank
        player.save()


@receiver(post_save, sender=User)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)
