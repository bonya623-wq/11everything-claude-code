from .funpay         import FunPayParser
from .g2g            import G2GParser
from .eldorado       import EldoradoParser
from .playerauctions import PlayerAuctionsParser
from .iggm           import IGGMParser
from .z2u            import Z2UParser
from .u7buy          import U7BUYParser
from .igvault        import IGVaultParser
from .odealo         import OdealoParser
from .g2a            import G2AParser
from .mmoga          import MMOGAParser

ALL_PARSERS = [
    FunPayParser,
    G2GParser,
    EldoradoParser,
    PlayerAuctionsParser,
    IGGMParser,
    Z2UParser,
    U7BUYParser,
    IGVaultParser,
    OdealoParser,
    G2AParser,
    MMOGAParser,
]

__all__ = ["ALL_PARSERS"]
