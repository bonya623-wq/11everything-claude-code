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
from .dd373          import DD373Parser
from .uu898          import UU898Parser

ALL_PARSERS = [
    DD373Parser,       # cheapest ~$0.10-0.14/M
    UU898Parser,       # ~$0.12-0.16/M
    FunPayParser,      # ~$0.15-0.22/M
    G2GParser,         # ~$0.18-0.25/M
    U7BUYParser,       # ~$0.22-0.28/M
    EldoradoParser,    # ~$0.22-0.30/M
    PlayerAuctionsParser,
    Z2UParser,
    IGVaultParser,
    IGGMParser,
    OdealoParser,
    G2AParser,
    MMOGAParser,
]

__all__ = ["ALL_PARSERS"]
