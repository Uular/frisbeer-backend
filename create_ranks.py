import sys
import os

PROJECT_PATH = 'djangofiles'
SETTINGS_FILE = 'server.settings'

sys.path.append(PROJECT_PATH)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS_FILE)
import django
django.setup()

ranks = ["Klipsu I", "Klipsu II", "Klipsu III", "Klipsu IV", "Klipsu Mestari", "Klipsu Eliitti Mestari",
         "Kultapossu I", "Kultapossu II", "Kultapossu III", "Kultapossu Mestari", "Mestari Heittäjä I",
         "Mestari Heittäjä II", "Mestari Heittäjä Eliitti", "Arvostettu Jallu Mestari", "Legendaarinen Nalle",
         "Legendaarinen Nalle Mestari", "Korkein Ykkösluokan Mestari", "Urheileva Alkoholisti"]

from frisbeer.models import Rank

for r in ranks:
    rank = Rank(name=r)
    rank.save()
