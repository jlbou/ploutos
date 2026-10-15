"""Lo que se le ensenya al analista en cada llamada (informe seccion 1.5).

Dos partes:
- `SYSTEM_PROMPT` (`system_prompt.md`): el papel y las reglas. Va con
  `--append-system-prompt "$(cat ...)"`: `--append-system-prompt-file` NO existe
  (verificado el 22/09/2026).
- `build_input()` + `render()`: el JSON de la llamada.

REGLA 19: LA IA NUNCA VE CLAVES NI VARIABLES DE ENTORNO. Este modulo no lee el
entorno, no lee `.env` y no recibe objetos que las lleven: solo los valores que se
le pasan uno a uno. Hay un test que mete un secreto falso en el entorno y
comprueba que no aparece en el prompt.

Decisiones del propietario del 22/09/2026 que se notan aqui: sin noticias (F), y solo
candidatos nuevos (B), asi que no hay revision de cartera: las posiciones van como
CONTEXTO (correlacion, exposicion), no para que se decida sobre ellas.

Sin I/O salvo leer `system_prompt.md` al importar. Sin reloj: el instante se pasa.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from strategy.candidates import Candidate

SYSTEM_PROMPT = (Path(__file__).resolve().parent / "system_prompt.md").read_text(encoding="utf-8")

# Lo que se permite en la entrada, y nada mas. Si se anyade una clave hay que
# anyadirla aqui a proposito: la entrada es un mundo cerrado.
INPUT_KEYS = frozenset({"ts", "mode", "portfolio", "limits", "candidates", "memory"})

INSTRUCCION = "Decide sobre cada candidato. Responde solo con el JSON del esquema."


@dataclass(frozen=True, slots=True)
class PositionView:
    """Una posicion abierta, tal como la ve el analista."""

    position_id: str
    symbol: str
    entry: float
    last: float
    stop: float
    target: float
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class LimitsView:
    """Los limites VIGENTES, ya modulados (regla 9, slider)."""

    max_positions: int
    slots_free: int
    risk_per_trade_usd: float
    daily_loss_left_usd: float
    trades_left_today: int


def _n(x: float) -> float:
    """6 cifras significativas: los decimales de mas son tokens de mas."""
    return float(f"{x:.6g}")


def _candidato(c: Candidate) -> dict[str, Any]:
    """El candidato tal como lo define `Candidate.to_prompt_dict()` (un solo sitio
    decide como se ve un candidato), mas el spread, que el informe seccion 1.5 pone
    en la entrada y aquel metodo no lleva."""
    d = c.to_prompt_dict()
    d["spread_pct"] = round(c.spread_pct, 4)
    return d


def _posicion(p: PositionView, now: datetime) -> dict[str, Any]:
    return {
        "id": p.position_id,
        "symbol": p.symbol,
        "entry": _n(p.entry),
        "last": _n(p.last),
        "stop": _n(p.stop),
        "target": _n(p.target),
        "age_min": int((now - p.opened_at).total_seconds() // 60),
        "unrealized_pct": round((p.last - p.entry) / p.entry * 100, 2) if p.entry else 0.0,
    }


def build_input(
    *,
    now: datetime,
    mode: str,
    equity_usd: float,
    free_quote_usd: float,
    positions: list[PositionView],
    limits: LimitsView,
    candidates: list[Candidate],
    memory: list[str] = (),
) -> dict[str, Any]:
    """El JSON de entrada. `memory` son reglas validadas (fase 8): hoy, vacia."""
    return {
        "ts": now.isoformat(timespec="seconds"),
        "mode": mode,
        "portfolio": {
            "equity": round(equity_usd, 2),
            "free_quote": round(free_quote_usd, 2),
            "open_positions": [_posicion(p, now) for p in positions],
        },
        "limits": {
            "max_positions": limits.max_positions,
            "slots_free": limits.slots_free,
            "risk_per_trade_usd": round(limits.risk_per_trade_usd, 2),
            "daily_loss_left_usd": round(limits.daily_loss_left_usd, 2),
            "trades_left_today": limits.trades_left_today,
        },
        "candidates": [_candidato(c) for c in candidates],
        "memory": list(memory),
    }


def render(entrada: dict[str, Any]) -> str:
    """El texto que va a `claude -p`: el JSON compacto y una linea de instruccion."""
    extra = set(entrada) - INPUT_KEYS
    if extra:
        raise ValueError(f"claves no permitidas en la entrada del analista: {sorted(extra)}")
    return json.dumps(entrada, ensure_ascii=False, separators=(",", ":")) + "\n" + INSTRUCCION


def candidate_ids(entrada: dict[str, Any]) -> frozenset[str]:
    """Los `cid` validos de ESTA llamada: lo que el parser aceptara."""
    return frozenset(c["cid"] for c in entrada["candidates"])


def position_ids(entrada: dict[str, Any]) -> frozenset[str]:
    return frozenset(p["id"] for p in entrada["portfolio"]["open_positions"])
