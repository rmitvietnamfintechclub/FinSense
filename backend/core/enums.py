from enum import Enum


class Ticker(str, Enum):
    """VN30 ticker symbols.

    Source: HOSE VN30 quarterly review, announced 15/07/2026, effective 03/08/2026
    Snapshot date: 2026-07-27

    this enum won't be updated when the real index changes,
    because the frozen test set and all historical sentiment records are
    labelled against this exact vocabulary.
    """

    ACB = "ACB"
    BID = "BID"
    BSR = "BSR"
    CTG = "CTG"
    FPT = "FPT"
    GAS = "GAS"
    GVR = "GVR"
    HDB = "HDB"
    HPG = "HPG"
    LPB = "LPB"
    MBB = "MBB"
    MCH = "MCH"
    MSN = "MSN"
    MWG = "MWG"
    SAB = "SAB"
    SHB = "SHB"
    SSB = "SSB"
    SSI = "SSI"
    STB = "STB"
    TCB = "TCB"
    TCX = "TCX"
    VCB = "VCB"
    VHM = "VHM"
    VIB = "VIB"
    VIC = "VIC"
    VJC = "VJC"
    VNM = "VNM"
    VPB = "VPB"
    VPL = "VPL"
    VRE = "VRE"
