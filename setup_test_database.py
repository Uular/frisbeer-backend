import os
import sys

from django.db import IntegrityError

sys.path.append(os.path.join(os.path.dirname(__file__), 'djangofiles'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', "server.settings")

import django
django.setup()

from frisbeer.models import *
from django.contrib.auth.models import User

Player.objects.all().delete()
players = []
for name in ("jsloth", "T3mu", "Runtu", "ivanhoe_", "lepikko", "Paju"):
    player = Player(name=name)
    player.save()
    players.append(player)

g = Game(name="Testipeli")
g.save()
g.team1 = players[0:3]
g.team2 = players[3:]
g.save()


try:
    admin = User.objects.create_superuser(username="admin", password="adminpassu", email="")
    admin.save()
except IntegrityError:
    pass
