from __future__ import annotations

import re
from typing import Any

# Topstep permitted CME Group futures roots (product codes).
# Source: https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade
TOPSTEP_SYMBOLS: dict[str, str] = {
    # Equity indices
    "ES": "E-mini S&P 500",
    "MES": "Micro E-mini S&P 500",
    "NQ": "E-mini NASDAQ 100",
    "MNQ": "Micro E-mini NASDAQ 100",
    "RTY": "E-mini Russell 2000",
    "M2K": "Micro E-mini Russell 2000",
    "YM": "Mini-DOW",
    "MYM": "Micro Mini-DOW",
    "NKD": "Nikkei 225",
    # Energy
    "CL": "Crude Oil",
    "MCL": "Micro Crude Oil",
    "QM": "E-mini Crude Oil",
    "NG": "Natural Gas",
    "QG": "E-mini Natural Gas",
    "MNG": "Micro Henry Hub Natural Gas",
    "RB": "RBOB Gasoline",
    "HO": "Heating Oil",
    # Metals
    "GC": "Gold",
    "MGC": "Micro Gold",
    "SI": "Silver",
    "SIL": "Micro Silver",
    "HG": "Copper",
    "MHG": "Micro Copper",
    "PL": "Platinum",
    # FX
    "6E": "Euro FX",
    "M6E": "Micro EUR/USD",
    "E7": "E-mini Euro FX",
    "6B": "British Pound",
    "M6B": "Micro GBP/USD",
    "6J": "Japanese Yen",
    "6C": "Canadian Dollar",
    "6A": "Australian Dollar",
    "M6A": "Micro AUD/USD",
    "6S": "Swiss Franc",
    "6M": "Mexican Peso",
    "6N": "New Zealand Dollar",
    # Crypto
    "MBT": "Micro Bitcoin",
    "MET": "Micro Ether",
    # Agriculture
    "ZC": "Corn",
    "ZS": "Soybeans",
    "ZW": "Wheat",
    "ZM": "Soybean Meal",
    "ZL": "Soybean Oil",
    "HE": "Lean Hogs",
    "LE": "Live Cattle",
    # Treasuries
    "ZT": "2-Year Note",
    "ZF": "5-Year Note",
    "ZN": "10-Year Note",
    "TN": "Ultra 10-Year Note",
    "ZB": "30-Year Bond",
    "UB": "Ultra-Bond",
}

# ProjectX internal symbolId suffix -> friendly root (e.g. F.US.ENQ -> NQ)
_SYMBOL_ID_TO_ROOT: dict[str, str] = {
    "EP": "ES",
    "MES": "MES",
    "ENQ": "NQ",
    "MNQ": "MNQ",
    "RTY": "RTY",
    "M2K": "M2K",
    "YM": "YM",
    "MYM": "MYM",
    "NKD": "NKD",
    "CLE": "CL",
    "MCL": "MCL",
    "NG": "NG",
    "GCE": "GC",
    "MGC": "MGC",
    "SIE": "SI",
    "CPE": "HG",
    "MBT": "MBT",
    "GMET": "MET",
}


def _root_from_contract_name(name: str) -> str | None:
    """Extract root from contract name like NQU5, MESZ4, 6EH26."""
    match = re.match(r"^([A-Z0-9]{2,4})", name.upper())
    if not match:
        return None
    token = match.group(1)
    if token in TOPSTEP_SYMBOLS:
        return token
    # Strip month/year suffix (last 2 chars: e.g. NQU5 -> NQ)
    if len(token) >= 3 and token[:-2] in TOPSTEP_SYMBOLS:
        return token[:-2]
    if len(token) >= 4 and token[:-2] in TOPSTEP_SYMBOLS:
        return token[:-2]
    return token


def contract_root(contract: dict[str, Any]) -> str:
    symbol_id = str(contract.get("symbolId", ""))
    if symbol_id:
        suffix = symbol_id.rsplit(".", 1)[-1]
        if suffix in _SYMBOL_ID_TO_ROOT:
            return _SYMBOL_ID_TO_ROOT[suffix]
        if suffix in TOPSTEP_SYMBOLS:
            return suffix

    name = str(contract.get("name", ""))
    root = _root_from_contract_name(name)
    if root:
        return root

    description = str(contract.get("description", ""))
    for root, label in TOPSTEP_SYMBOLS.items():
        if label.lower() in description.lower() or root in description.upper().split():
            return root
    return name or str(contract.get("id", "?"))


def group_contracts_by_root(contracts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        root = contract_root(contract)
        grouped.setdefault(root, []).append(contract)
    for root in grouped:
        grouped[root].sort(key=lambda c: str(c.get("name", "")))
    return dict(sorted(grouped.items()))


def resolve_pairlist(pair_whitelist: list[str], pairlists: list[dict[str, Any]]) -> list[str]:
    """Freqtrade-style pairlist resolution (StaticPairList only for now)."""
    if not pairlists:
        return [p.upper() for p in pair_whitelist]

    pairs: list[str] = []
    for entry in pairlists:
        method = str(entry.get("method", "StaticPairList"))
        if method != "StaticPairList":
            raise ValueError(f"Unsupported pairlist method '{method}'. Only StaticPairList is implemented.")
        entry_pairs = entry.get("pairs") or pair_whitelist
        pairs.extend(str(p).upper() for p in entry_pairs)

    # De-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique
