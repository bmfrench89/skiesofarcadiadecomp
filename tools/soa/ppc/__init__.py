"""PowerPC 750CL (Gekko) instruction decoding."""

from .decode import Insn, decode, decode_stream
from .isa import Form

__all__ = ["Form", "Insn", "decode", "decode_stream"]
