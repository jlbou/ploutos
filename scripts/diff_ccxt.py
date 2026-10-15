"""Diff de CONDUCTA solo de las funciones de ccxt que el bot usa (okx.py y base/exchange.py), sin anotaciones ni docstrings.

    python scripts/diff_ccxt.py <site-packages/ccxt de una version> <site-packages/ccxt de la otra>
"""
import ast
import difflib
import sys
from pathlib import Path

a_dir, b_dir = Path(sys.argv[1]), Path(sys.argv[2])
USADAS = {
    "okx.py": ["sign", "handle_errors", "parse_balance", "fetch_balance", "parse_trading_balance", "fetch_order_book",
               "parse_order_book", "fetch_ticker", "parse_ticker", "fetch_time", "create_order_request", "fetch_markets",
               "parse_market", "fetch_markets_by_type", "set_sandbox_mode", "nonce", "describe", "load_markets",
               "price_to_precision", "amount_to_precision"],
    "base/exchange.py": ["price_to_precision", "amount_to_precision", "load_markets", "set_markets", "fetch2", "request",
                         "fetch", "parse_order_book", "parse_bid_ask", "parse_bids_asks", "safe_balance", "safe_ticker",
                         "set_sandbox_mode", "handle_errors", "throw_exactly_matched_exception",
                         "throw_broadly_matched_exception", "market", "create_order_request"],
}


def funciones(path: Path) -> dict[str, str]:
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef):
            nodo.returns = None
            for arg in nodo.args.args + nodo.args.kwonlyargs:
                arg.annotation = None
            if nodo.body and isinstance(nodo.body[0], ast.Expr) and isinstance(getattr(nodo.body[0], "value", None),
                                                                              ast.Constant):
                nodo.body = nodo.body[1:] or [ast.Pass()]
            for n in ast.walk(nodo):
                if isinstance(n, ast.AnnAssign):
                    n.annotation = ast.Name("_")
            out.setdefault(nodo.name, ast.unparse(nodo))
    return out


for f, nombres in USADAS.items():
    fa, fb = funciones(a_dir / f), funciones(b_dir / f)
    for n in nombres:
        if n not in fa and n not in fb:
            continue
        if fa.get(n) == fb.get(n):
            print(f"{f} {n}: IGUAL")
            continue
        print(f"{f} {n}: DISTINTA")
        print("\n".join(difflib.unified_diff((fa.get(n) or "").splitlines(), (fb.get(n) or "").splitlines(),
                                             lineterm="", n=1)))
