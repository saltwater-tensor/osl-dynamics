"""Simulations for MEG data

This module allows the user to conveniently simulate MEG data. Instantiating the
`Simulation` class automatically takes the user's input parameters and produces data
which can be analysed.

"""

from vrad.simulation._base import *  # noqa
from vrad.simulation._hmm import *  # noqa
from vrad.simulation._hsmm import *  # noqa
from vrad.simulation._mvn import *  # noqa
