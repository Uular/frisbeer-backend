from django.templatetags.static import static
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from frisbeer.models import Rank, Player, GamePlayerRelation, Game, Location, Team, GameTeamRelation, Season, GameRules


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = '__all__'

    def validate(self, attrs):
        su = super().validate(attrs)
        try:
            longitude = su.get("longitude", self.instance.longitude)
        except AttributeError:
            longitude = None

        try:
            latitude = su.get("latitude", self.instance.latitude)
        except AttributeError:
            latitude = None

        if latitude is not None and (latitude > 90 or latitude < -90):
            raise ValidationError("Latitude must be between -90 and 90")
        if longitude is not None and (longitude > 180 or longitude < -180):
            raise ValidationError("Longitude must be between -180 and 180")
        if (longitude is None and latitude is not None) or (longitude is not None and latitude is None):
            raise ValidationError(
                "If longitude is provided then latitude is required and vice versa. Both can be null.")

        return su


class RankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rank
        fields = ('name', 'image_url', 'numerical_value')
        read_only_fields = ["numerical_value", "name", "image_url"]

    def to_representation(self, instance):
        return {
            'numerical_value': instance.numerical_value,
            'name': instance.name,
            'image_url': self.context['request'].build_absolute_uri(static(instance.image_url))
        }


class PlayerSerializer(serializers.ModelSerializer):
    rank = RankSerializer(many=False, read_only=True, allow_null=True)

    class Meta:
        model = Player
        fields = ('id', 'name', 'score', 'rank', 'season_best')
        read_only_fields = ('score', 'rank', 'id', 'season_best')


class PlayersValidator:
    def __call__(self, values):
        players = values.get("players", None)
        if not players or len(players) != 6:
            raise ValidationError("Round requires exactly six players")


class PlayerInGameSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.IntegerField(source='player.id')
    name = serializers.ReadOnlyField(source='player.name', required=False)
    team = serializers.IntegerField(required=False, read_only=True)
    rank = RankSerializer(source='player.rank', required=False, allow_null=True)
    score = serializers.IntegerField(source='player.score', required=False, read_only=True)

    class Meta:
        model = GamePlayerRelation
        fields = ('id', 'name', 'team', 'rank', 'score')


class TeamInGameSerializer(serializers.ModelSerializer):
    name = serializers.ReadOnlyField(source='team.name')
    side = serializers.IntegerField(read_only=True)

    class Meta:
        model = GameTeamRelation
        fields = ('name', 'side')


class GameRulesSerializer(serializers.ModelSerializer):
    class Meta:
        model = GameRules
        fields = '__all__'


class GameSerializer(serializers.ModelSerializer):
    rules = GameRulesSerializer(read_only=True)
    location_repr = LocationSerializer(source='location', read_only=True)
    players = PlayerInGameSerializer(many=True, source='gameplayerrelation_set', partial=True, required=False)
    teams = TeamInGameSerializer(many=True, source='gameteamrelation_set', partial=True, required=False)

    class Meta:
        model = Game
        exclude = ['_rules']


    def validate(self, attrs):
        admin = self.context['request'].user.is_staff
        game = self.instance
        state = attrs.get('state', game.state if game else None)
        players = attrs.get('gameplayerrelation_set', None)

        team1 = []
        team2 = []

        if not players and game:
            players = game.players.values_list(flat=True)
            team1 = game.players.filter(gameplayerrelation__team=1).values_list(flat=True)
            team2 = game.players.filter(gameplayerrelation__team=2).values_list(flat=True)

        team1_score = attrs.get('team1_score', game.team1_score if game else 0)
        team2_score = attrs.get('team2_score', game.team2_score if game else 0)

        if state:
            if game and game.state > state and not admin:
                raise ValidationError("Only admins can roll back game state")
            if state >= Game.APPROVED and not admin:
                raise ValidationError("Only admins can approve games and edit approved games")
            if state >= Game.READY and not (game.rules.min_players <= len(players) <= game.rules.max_players):
                raise ValidationError("A game without exactly six players must be in pending state")
            if state >= Game.READY and (len(team1) + len(team2)) != len(players):
                raise ValidationError("Game that doesn't have teams must be in Pending state (0). "
                                      "Create teams manually or with create_teams endpoint")

            if state >= Game.PLAYED:
                if game.team1_score + game.team2_score > game.rules.max_rounds:
                    raise ValidationError("Too many round wins.")
                if team1_score != game.rules.min_rounds and team2_score != game.rules.min_rounds:
                    raise ValidationError("One team needs two round wins to win the game")

        if players and len(players) > game.rules.max_players:
            raise ValidationError(f"Game can't have more than {game.rules.max_players} players")

        return attrs

    def update(self, instance, validated_data):
        players = validated_data.pop('gameplayerrelation_set', None)
        location = validated_data.pop('location', None)
        old_state = instance.state
        new_state = validated_data.get('state', old_state)

        s = super().update(instance, validated_data)
        if players:
            GamePlayerRelation.objects.filter(game=s).delete()
            for player in players:
                p = Player.objects.get(id=player["player"]["id"])
                team = player.get("team", 0)
                g, created = GamePlayerRelation.objects.get_or_create(game=s, player=p)
                g.team = team
                g.save()

        if location:
            s.location = location.get('id', None)

        return s

    def create(self, validated_data):
        players = validated_data.pop('gameplayerrelation_set', [])
        s = super().create(validated_data)
        if players:
            GamePlayerRelation.objects.filter(game=s).delete()
            for player in players:
                p = Player.objects.get(id=player["player"]["id"])
                team = player.get("team", 0)
                g, created = GamePlayerRelation.objects.get_or_create(game=s, player=p)
                g.team = team
                g.save()

        if s.state >= Game.READY:
            s.create_teams()

        return s


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ('name', 'elo', 'season_best', 'games_played', 'virtual')
