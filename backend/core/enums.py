from enum import StrEnum


class Ticker(StrEnum):
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


class Concept(StrEnum):
    """Macro/sector concept taxonomy for VN30 sentiment scoring.

    This is a designed taxonomy fitted to the real sector composition of the
    30-ticker basket in Ticker above 
    (source: HOSE/ACBS VN30 sector breakdown, verified 2026-07), 
    +one MACRO member for drivers that aren't sector specific (interest rates, exchange rate,
    inflation, monetary policy).

    Frozen for the project lifetime. Extensible only through a new project decision
    """

    BANKING = "BANKING"
    CONSUMER_DISCRETIONARY = "CONSUMER_DISCRETIONARY"
    CONSUMER_STAPLES = "CONSUMER_STAPLES"
    ENERGY = "ENERGY"
    INDUSTRIALS = "INDUSTRIALS"
    MACRO = "MACRO"
    MATERIALS = "MATERIALS"
    REAL_ESTATE = "REAL_ESTATE"
    SECURITIES = "SECURITIES"
    TECHNOLOGY = "TECHNOLOGY"
