from .funpay       import FunPayParser
from .g2g          import G2GParser
from .eldorado     import EldoradoParser
from .playerauctions import PlayerAuctionsParser
from .iggm         import IGGMParser
from .z2u          import Z2UParser

ALL_PARSERS = [
    FunPayParser,
    G2GParser,
    EldoradoParser,
    PlayerAuctionsParser,
    IGGMParser,
    Z2UParser,
]

__all__ = ["ALL_PARSERS"]
