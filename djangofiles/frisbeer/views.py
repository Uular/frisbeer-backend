import logging
from django import forms
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.views.generic import FormView, ListView
from django.templatetags.static import static

from rest_framework import serializers, viewsets,  mixins
from rest_framework.viewsets import GenericViewSet

from frisbeer.models import *


class RankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rank
        fields = ('name', 'image_url', 'numerical_value')
        read_only_fields = ["numerical_value", "name", "image_url"]

    def to_representation(self, instance):
        return {
            'numerical_value': instance.numerical_value,
            'name': instance.name,
            'image_url': static(instance.image_url)
        }


class RankViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, GenericViewSet):
    queryset = Rank.objects.all()
    serializer_class = RankSerializer


class PlayerSerializer(serializers.ModelSerializer):
    rank = RankSerializer(many=False, read_only=True, allow_null=True)

    class Meta:
        model = Player
        fields = ('id', 'name', 'score', 'rank')
        read_only_fields = ('score', 'rank', 'id')


class PlayerViewSet(viewsets.ModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerSerializer


class PlayersValidator:
    def __call__(self, values):
        players = values.get("players", None)
        if not players or len(players) != 6:
            raise ValidationError("Round requires exactly six players")


class PlayerInGameSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.IntegerField(source='player.id')
    name = serializers.ReadOnlyField(source='player.name')
    team = serializers.IntegerField()
    rank = RankSerializer(source='player.rank')

    class Meta:
        model = GamePlayerRelation
        fields = ('id', 'name', 'team', 'rank')


class GameSerializer(serializers.ModelSerializer):
    players = PlayerInGameSerializer(many=True, source='gameplayerrelation_set', partial=True)

    class Meta:
        model = Game
        fields = "__all__"

    def update(self, instance, validated_data):
        try:
            players = validated_data.pop('gameplayerrelation_set')
        except KeyError:
            players = None
        s = super().update(instance, validated_data)
        if players:
            GamePlayerRelation.objects.filter(game=s).delete()
            for player in players:
                p = Player.objects.get(id=player["player"]["id"])
                team = player["team"] if player["team"] else 0
                g, created = GamePlayerRelation.objects.get_or_create(game=s, player=p)
                g.team = team
                g.save()
        return s

    def create(self, validated_data):
        players = validated_data.pop('gameplayerrelation_set')
        s = super().create(validated_data)
        if players:
            GamePlayerRelation.objects.filter(game=s).delete()
            for player in players:
                p = Player.objects.get(id=player["player"]["id"])
                team = player["team"] if player["team"] else 0
                g, created = GamePlayerRelation.objects.get_or_create(game=s, player=p)
                g.team = team
                g.save()
        return s


class PlayerInGameViewSet(viewsets.ModelViewSet):
    queryset = GamePlayerRelation.objects.all()
    serializer_class = PlayerInGameSerializer


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.all()
    serializer_class = GameSerializer


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


class LocationViewSet(viewsets.ModelViewSet):
    queryset = Location.objects.all()
    serializer_class = LocationSerializer


def validate_players(value):
    logging.debug("Validating players")
    if len(value) != 6 or len(set(value)) != 6:
        raise ValidationError("Select exactly six different players")


class EqualTeamForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['players'] = forms.MultipleChoiceField(
            choices=[(player.id, player.name) for player in list(Player.objects.all())],
            validators=[validate_players],
            widget=forms.CheckboxSelectMultiple)


class TeamCreateView(FormView):
    template_name = "frisbeer/team_select_form.html"
    form_class = EqualTeamForm

    def form_valid(self, form):
        def calculate_team_elo(team):
            return int(sum([player.elo for player in team]) / len(team))

        elo_list = []
        players = set(Player.objects.filter(id__in=form.cleaned_data["players"]))
        possibilities = itertools.combinations(players, 3)
        for possibility in possibilities:
            team1 = possibility
            team2 = players - set(team1)
            elo1 = calculate_team_elo(team1)
            elo2 = calculate_team_elo(team2)
            elo_list.append((abs(elo1 - elo2), team1, team2))
        ideal_teams = sorted(elo_list, key=itemgetter(0))[0]
        teams = {
            "team1": ideal_teams[1],
            "team1_elo": calculate_team_elo(ideal_teams[1]),
            "team2": ideal_teams[2],
            "team2_elo": calculate_team_elo(ideal_teams[2]),
        }

        return render(self.request, 'frisbeer/team_select_form.html', {"form": form, "teams": teams})


class ScoreListView(ListView):
    model = Player
    ordering = ['-score']
