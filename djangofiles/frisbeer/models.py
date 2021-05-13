import itertools
from operator import itemgetter
from math import exp, ceil
from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import ugettext_lazy as _
from django.utils.timezone import now
from django.db import models

from frisbeer import utils


class Rank(models.Model):
    name = models.CharField(max_length=100, blank=True, unique=True)
    image_url = models.CharField(max_length=1000, blank=True)
    numerical_value = models.IntegerField(unique=True)

    def __str__(self):
        return self.name


class Player(models.Model):
    elo = models.IntegerField(default=1500)
    score = models.IntegerField(default=0)
    season_best = models.IntegerField(default=0)
    name = models.CharField(max_length=100, unique=True)
    rank = models.ForeignKey(Rank, blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class GameRules(models.Model):
    name = models.CharField(max_length=50, unique=True)
    min_players = models.IntegerField(default=6, validators=[MinValueValidator(0)])
    max_players = models.IntegerField(default=6, validators=[MinValueValidator(0)])
    min_rounds = models.IntegerField(default=2, validators=[MinValueValidator(0)])
    max_rounds = models.IntegerField(default=3, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = 'Ruleset'

    def clean(self):
        if self.min_players > self.max_players:
            self.max_players = self.min_players
        if self.min_rounds > self.max_rounds:
            self.max_rounds = self.min_rounds

    def __str__(self):
        return self.name


class ScoreAlgorithm(models.TextChoices):
    S_2017 = '2017', _('Season 2017')
    S_2018 = '2018', _('Season 2018')
    ELO = 'elo', _('Elo')
    TOP_ELO = 'top_elo', _('Best elo')


class PlayerStatistic(models.TextChoices):
    ROUNDS_PLAYED = 'RP', _('Rounds played')
    ROUNDS_WON = 'RW', _('Rounds won')
    GAMES_PLAYED = 'GP', _('Games played')
    GAMES_WON = 'GW', _('Games won')


class SeasonRules(models.Model):
    name = models.CharField(max_length=100)
    elo_decay = models.BooleanField(default=True)
    score_algorithm = models.CharField(max_length=16, choices=ScoreAlgorithm.choices, default=ScoreAlgorithm.ELO)
    rank_statistic = models.CharField(max_length=3, choices=PlayerStatistic.choices, default=PlayerStatistic.ROUNDS_WON)
    rank_min_value = models.IntegerField(default=5)

    def __str__(self):
        return self.name or self.score_algorithm

    @property
    def algorithm(self):
        def score_2017(games_played, rounds_played, rounds_won, *args, **kwargs):
            win_rate = rounds_won / rounds_played if rounds_played != 0 else 0
            return int(win_rate * (1 - exp(-games_played / 4)) * 1000)

        def score_2018(games_played, rounds_played, rounds_won, *args, **kwargs):
            win_rate = rounds_won / rounds_played if rounds_played != 0 else 0
            return int(rounds_won + win_rate * (1 / (1 + exp(3 - games_played / 2.5))) * 1000)

        def score_best_elo(player, *args, **kwargs):
            return player.season_best

        def score_elo(player, *args, **kwargs):
            return player.elo

        if self.score_algorithm == ScoreAlgorithm.S_2017:
            return score_2017
        elif self.score_algorithm == ScoreAlgorithm.S_2018:
            return score_2018
        elif self.score_algorithm == ScoreAlgorithm.TOP_ELO:
            return score_best_elo
        else:
            return score_elo


class Season(models.Model):

    name = models.CharField(max_length=255, unique=True)
    start_date = models.DateField(default=now)
    end_date = models.DateField(null=True, blank=True)
    rules = models.ForeignKey(SeasonRules, null=True, on_delete=models.PROTECT)
    score_algorithm = models.CharField(max_length=255, choices=ScoreAlgorithm.choices)
    game_rules = models.ForeignKey(GameRules, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return self.name

    @staticmethod
    def current():
        return Season.objects.filter(start_date__lte=date.today()).order_by('-start_date').first()

    def score(self, *args, **kwargs):
        return self.rules.algorithm(*args, **kwargs)


class Team(models.Model):
    name = models.CharField(max_length=100)
    players = models.ManyToManyField(Player, through="TeamPlayerRelation")
    season = models.ForeignKey(Season, null=True, on_delete=models.SET_NULL)
    elo = models.IntegerField(default=1500)
    season_best = models.IntegerField(default=0)
    virtual = models.BooleanField(default=False)

    class Meta:
        ordering = ('-elo',)

    def __str__(self):
        return self.name

    @classmethod
    def find_or_create(cls, season, players):
        teams_queryset = cls.objects.filter(season=season)
        for player in players:
            teams_queryset = teams_queryset.filter(players=player)
        if teams_queryset:
            team = teams_queryset.order_by('virtual').first()
            return team
        else:
            name = "".join(p.name for p in players)
            new_team = cls.objects.create(name=name, season=season, virtual=True)
            for p in players:
                TeamPlayerRelation.objects.create(player=p, team=new_team)
            return new_team

    @property
    def games_played(self):
        season = Season.current()
        games = self.games.filter(season=season)
        return games.count()



class TeamPlayerRelation(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="team_players")
    backup = models.BooleanField(default=False)

    class Meta:
        unique_together = (("player", "team"))


class Game(models.Model):
    PENDING = 0
    READY = 1
    PLAYED = 2
    APPROVED = 3

    game_state_choices = ((PENDING, "Pending"),
                          (READY, "Ready"),
                          (PLAYED, "Played"),
                          (APPROVED, "Approved"))

    season = models.ForeignKey(Season, null=True, blank=True, on_delete=models.SET_NULL)
    _rules = models.ForeignKey(GameRules, null=True, blank=True, on_delete=models.SET_NULL)

    players = models.ManyToManyField(Player, related_name='games', through='GamePlayerRelation')
    date = models.DateTimeField(default=now)
    name = models.CharField(max_length=250, blank=True, null=True)
    description = models.TextField(max_length=2500, blank=True, null=True)
    location = models.ForeignKey('Location', blank=True, null=True, on_delete=models.SET_NULL)

    teams = models.ManyToManyField(Team, related_name='games', through='GameTeamRelation')

    team1_score = models.IntegerField(default=0, choices=((0, 0), (1, 1), (2, 2)))
    team2_score = models.IntegerField(default=0, choices=((0, 0), (1, 1), (2, 2)))
    state = models.IntegerField(choices=game_state_choices, default=PENDING,
                                help_text="0: pending - the game has been proposed but is still missing players. "
                                          "1: ready - the game can be played now. Setting this state creates teams. "
                                          "2: played - the game has been played and results are in. "
                                          "4: approved - admin has approved the game and "
                                          "it's results are used in calculating ranks.")

    class Meta:
        ordering = ('-date',)

    def _team(self, side):
        try:
            return GameTeamRelation.objects.get(game=self, side=side).team
        except GameTeamRelation.DoesNotExist:
            return None

    def clean(self):
        if self.rules is None and (self.season is None or self.season.game_rules is None):
            raise ValidationError({'rules': _('Rules or season with rules must be set')})

    @property
    def rules(self):
        return self._rules or self.season.game_rules

    @property
    def team1(self):
        return self._team(1)

    @property
    def team2(self):
        return self._team(2)

    def save(self, *args, **kwargs):
        if not self.season:
            self.season = Season.current()
        super().save(*args, **kwargs)

    def __str__(self):
        return "{0} {2} - {3} {1}".format(
            self.team1.name if self.team1 and not self.team1.virtual else ", ".join(
                self.players.filter(gameplayerrelation__team=GamePlayerRelation.Team1).values_list("name", flat=True)),
            self.team2.name if self.team2 and not self.team2.virtual else ", ".join(
                self.players.filter(gameplayerrelation__team=GamePlayerRelation.Team2).values_list("name", flat=True)),
            self.team1_score,
            self.team2_score,
        )

    def can_create_teams(self):
        player_count = self.players.count()
        return self.rules.min_players <= player_count <= self.rules.max_players \
            and player_count == self.players.filter(gameplayerrelation__team=0).count()

    def can_score(self):
        players_count = self.players.count()
        players_per_team = ceil(players_count / 2)
        rounds_played = self.team1_score + self.team2_score
        return self.state >= Game.APPROVED \
               and self.rules.min_rounds <= rounds_played <= self.rules.max_rounds \
               and self.rules.min_players <= players_count <= self.rules.max_players \
               and self.players.filter(gameplayerrelation__team=0).count() == 0 \
               and self.players.filter(gameplayerrelation__team=1).count() <= players_per_team \
               and self.players.filter(gameplayerrelation__team=2).count() <= players_per_team

    def create_teams(self):
        ideal_teams = utils.create_equal_teams(set(self.players.all()))
        self.gameplayerrelation_set \
            .filter(player__id__in=[player.id for player in ideal_teams[1]]).update(team=GamePlayerRelation.Team1)
        self.gameplayerrelation_set \
            .filter(player__id__in=[player.id for player in ideal_teams[2]]).update(team=GamePlayerRelation.Team2)
        self.save()


class GamePlayerRelation(models.Model):
    Team1 = 1
    Team2 = 2
    Unassigned = 0

    class Meta:
        unique_together = (("player", "game"),)

    _team_choices = ((0, Unassigned), (1, Team1), (2, Team2))

    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    team = models.IntegerField(choices=_team_choices, default=Unassigned)


class GameTeamRelation(models.Model):
    side = models.IntegerField(choices=((1, 1), (2, 2)))
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)

    class Meta:
        unique_together = (("team", "game"), ("side", "game"))


class Location(models.Model):
    name = models.CharField(max_length=255, unique=True)
    longitude = models.DecimalField(max_digits=8, decimal_places=5, blank=True, null=True)
    latitude = models.DecimalField(max_digits=8, decimal_places=5, blank=True, null=True)

    def __str__(self):
        return self.name
