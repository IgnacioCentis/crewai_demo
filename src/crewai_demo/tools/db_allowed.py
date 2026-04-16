"""Tablas de negocio permitidas para consultas y schema (única fuente de verdad)."""

from __future__ import annotations

ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "insumos",
        "recetas",
        "productos_terminados",
        "presupuesto_ventas_kilos",
        "ventas",
    }
)
