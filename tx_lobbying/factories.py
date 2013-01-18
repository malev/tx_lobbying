import datetime
import random

import factory

from .models import (
    Interest,
    Lobbyist,
    ClientList,
    Compensation,
)


class InterestFactory(factory.Factory):
    FACTORY_FOR = Interest

    name = factory.Sequence(lambda n: 'Interest {0}'.format(n))
    state = 'TX'


class LobbyistFactory(factory.Factory):
    FACTORY_FOR = Lobbyist
    filer_id = factory.Sequence(lambda n: n)
    sort_name = factory.Sequence(lambda n: 'Lobbyist {0}'.format(n))
    updated_at = factory.LazyAttribute(lambda a: datetime.date.today())


class ClientListFactory(factory.Factory):
    FACTORY_FOR = ClientList
    lobbyist = factory.SubFactory(LobbyistFactory)
    year = 2013


class CompensationFactory(factory.Factory):
    FACTORY_FOR = Compensation
    amount_high = factory.LazyAttribute(lambda a: random.randint(10000, 100000))
    amount_low = factory.LazyAttribute(lambda a: random.randint(a.amount_high, 100000))
    amount_guess = factory.LazyAttribute(lambda a: (a.amount_high + a.amount_low) / 2)
    clientlist = factory.SubFactory(ClientListFactory)
    interest = factory.SubFactory(InterestFactory)
    updated_at = factory.LazyAttribute(lambda a: datetime.date.today())
