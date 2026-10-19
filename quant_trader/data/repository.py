"""Read-only access to existing research data; no generic SQL execution API."""
from pathlib import Path

import duckdb


class ResearchRepository:
    def __init__(self, database):
        self.path = Path(database).resolve(strict=True)
        self._connection = duckdb.connect(str(self.path), read_only=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._connection.close()

    def prices(self, symbols, *, as_of, start=None):
        """Return only requested bars through as_of (inclusive).

        as_of is a completed-session date, not proof of intraday availability.
        Forward-outcome labels are deliberately not exposed.
        """
        symbols = list(symbols)
        if not symbols:
            raise ValueError("At least one symbol is required")
        placeholders = ','.join('?' for _ in symbols)
        return self._connection.execute(
            f"SELECT * FROM price_history WHERE symbol IN ({placeholders}) "
            "AND date <= CAST(? AS DATE) "
            "AND (? IS NULL OR date >= CAST(? AS DATE)) ORDER BY symbol, date",
            [*symbols, as_of, start, start],
        ).df()

    def regimes(self, *, as_of):
        """Legacy regime rows, including their documented readiness limitations."""
        return self._connection.execute(
            "SELECT * FROM market_regime_daily WHERE date <= CAST(? AS DATE) ORDER BY date",
            [as_of],
        ).df()
