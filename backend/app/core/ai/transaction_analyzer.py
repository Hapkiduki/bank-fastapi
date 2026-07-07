from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.core.ai.config import ai_settings
from backend.app.core.logging import get_logger
from backend.app.core.utils.number_format import format_currency
from backend.app.transaction.models import Transaction

logger = get_logger()


class TransactionAnalyzer:
    def __init__(self):
        self.features = [
            "amount",
            "time_of_day",
            "day_of_week",
            "frequency",
            "pattern_match",
            "historical_amount",
            "velocity_amount",
        ]

    async def get_user_transaction_history(
        self,
        user_id: UUID,
        session: AsyncSession,
        days: int = ai_settings.ANALYSIS_WINDOW_DAYS,
    ) -> list[Transaction]:
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        query = select(Transaction).where(
            Transaction.sender_id == user_id, Transaction.created_at >= cutoff_date
        )
        result = await session.exec(query)
        return list(result)

    def _normalize_hour(self, hour: int) -> float:
        banking_hours = (ai_settings.BANKING_HOURS_START, ai_settings.BANKING_HOURS_END)

        if banking_hours[0] <= hour <= banking_hours[1]:
            return ai_settings.BANKING_HOURS_RISK
        elif hour < 6 or hour > 22:
            return ai_settings.LATE_HOURS_RISK
        else:
            return ai_settings.OFF_HOURS_RISK

    def _calculate_frequency(
        self, transaction: Transaction, history: list[Transaction]
    ) -> float:
        if not history:
            return 0.5

        timestamps = sorted([t.created_at for t in history])

        gaps = []

        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600
            gaps.append(gap)

        if not gaps:
            return 0.5

        avg_gap = float(np.mean(gaps))

        if avg_gap == 0:
            return 1.0

        current_gap = (transaction.created_at - timestamps[-1]).total_seconds() / 3600

        return min(1.0, abs(1 - (current_gap / avg_gap)))

    def _check_round_amounts(
        self, transaction: Transaction, history: list[Transaction]
    ) -> float:
        amount = float(transaction.amount)

        is_round = amount.is_integer()

        str_amount = str(int(amount))

        zero_count = len(str_amount) - len(str_amount.rstrip("0"))

        risk_score = min(1.0, (zero_count * 0.2) + (0.3 if is_round else 0))

        return risk_score

    def _check_repeated_amounts(
        self, transaction: Transaction, history: list[Transaction]
    ) -> float:
        if not history:
            return 0.0

        current_amount = float(transaction.amount)
        same_amount_count = sum(
            1 for t in history if abs(float(t.amount) - current_amount) < 0.01
        )

        return min(1.0, same_amount_count / len(history))

    def _check_velocity(
        self, transaction: Transaction, history: list[Transaction]
    ) -> dict:
        if not history:
            return {"frequency_score": 0.0, "amount_velocity_score": 0.0}

        recent_cutoff = transaction.created_at - timedelta(hours=24)

        recent_transactions = [t for t in history if t.created_at >= recent_cutoff]

        if not recent_transactions:
            return {"frequency_score": 0.0, "amount_velocity_score": 0.0}

        tx_count = len(recent_transactions)

        freq_score = min(1.0, tx_count / ai_settings.FREQUENCY_THRESHOLD)

        total_volume = sum(float(t.amount) for t in recent_transactions) + float(
            transaction.amount
        )

        amount_velocity_score = min(1.0, total_volume / ai_settings.VELOCITY_THRESHOLD)

        if freq_score > 0.7 and amount_velocity_score > 0.7:
            combined_score = 1.0
        else:
            combined_score = (freq_score + amount_velocity_score) / 2

        return {
            "frequency_score": freq_score,
            "amount_velocity_score": amount_velocity_score,
            "combined_score": combined_score,
        }

    def _calculate_amount_risk(
        self, amount_ratio: float, current_amount: float
    ) -> float:
        base_risk = min(1.0, amount_ratio / 5)

        amount_risk = min(1.0, current_amount / ai_settings.HIGH_AMOUNT_THRESHOLD)

        return max(base_risk, amount_risk)

    def _calculate_time_risk(self, time_of_day: float, day_of_week: float) -> float:
        weights = ai_settings.TIME_RISK_WEIGHTS

        return (time_of_day * weights["time_of_day"]) + (
            day_of_week * weights["day_of_week"]
        )

    def _detect_patterns(
        self, transaction: Transaction, history: list[Transaction]
    ) -> float:
        if not history:
            return 0.5

        patterns = {
            "round_amounts": self._check_round_amounts(transaction, history),
            "repeated_amounts": self._check_repeated_amounts(transaction, history),
            "velocity": self._check_velocity(transaction, history)["combined_score"],
        }
        return sum(
            score * ai_settings.PATTERN_WEIGHTS[pattern]
            for pattern, score in patterns.items()
        )

    def extract_features(
        self, transaction: Transaction, history: list[Transaction]
    ) -> dict:
        features = {}

        features["amount"] = float(transaction.amount)

        amounts = (
            [float(t.amount) for t in history]
            if history
            else [float(transaction.amount)]
        )

        avg_amount = float(np.mean(amounts))

        features["amount_ratio"] = features["amount"] / avg_amount if avg_amount else 1

        hour = transaction.created_at.hour

        features["time_of_day"] = self._normalize_hour(hour)

        features["day_of_week"] = transaction.created_at.weekday() / 6

        features["frequency"] = self._calculate_frequency(transaction, history)

        features["pattern_match"] = self._detect_patterns(transaction, history)

        velocity_metrics = self._check_velocity(transaction, history)

        features["velocity_amount"] = velocity_metrics["amount_velocity_score"]

        return features

    async def analyze_transaction(
        self, transaction: Transaction, user_id: UUID, session: AsyncSession
    ) -> tuple[float, dict]:
        try:
            history = await self.get_user_transaction_history(
                user_id, session, ai_settings.ANALYSIS_WINDOW_DAYS
            )

            features = self.extract_features(transaction, history)

            velocity_metrics = self._check_velocity(transaction, history)

            risk_scores = {
                "amount": self._calculate_amount_risk(
                    features["amount_ratio"], float(transaction.amount)
                ),
                "time": self._calculate_time_risk(
                    features["time_of_day"], features["day_of_week"]
                ),
                "frequency": velocity_metrics["frequency_score"],
                "pattern": features["pattern_match"],
                "velocity_amount": velocity_metrics["amount_velocity_score"],
            }

            weights = ai_settings.RISK_WEIGHTS

            base_score = sum(
                score * weights[factor] for factor, score in risk_scores.items()
            )

            final_score = (
                max(base_score, 0.9)
                if (risk_scores["amount"] > 0.7 and risk_scores["frequency"] > 0.7)
                else base_score
            )

            final_score = round(final_score, 2)

            high_risk_triggers = []

            if final_score > ai_settings.HIGH_RISK_SCORE_THRESHOLD:
                if risk_scores["amount"] > 0.7:
                    high_risk_triggers.append("high_amount")

                if risk_scores["frequency"] > 0.7:
                    high_risk_triggers.append("high_frequency")

                if risk_scores["velocity_amount"] > 0.7:
                    high_risk_triggers.append("high_velocity")

            risk_factors = {
                factor: {
                    "score": round(score, 2),
                    "weight": weights[factor],
                    "contribution": round(score * weights[factor], 2),
                }
                for factor, score in risk_scores.items()
            }

            risk_factors["risk_triggers"] = {
                "triggers": high_risk_triggers,
                "score": final_score,
                "threshold": ai_settings.HIGH_RISK_SCORE_THRESHOLD,
            }

            risk_factors["transaction_summary"] = {
                "amount": format_currency(str(transaction.amount)),
                "time": transaction.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "24h_total_volume": str(
                    sum(
                        float(t.amount)
                        for t in history
                        if (transaction.created_at - t.created_at).total_seconds()
                        <= 86400
                    )
                ),
                "24h_transaction_count": len(
                    [
                        t
                        for t in history
                        if (transaction.created_at - t.created_at).total_seconds()
                        <= 86400
                    ]
                ),
            }
            return final_score, risk_factors
        except Exception as e:
            logger.error(f"Error analyzing transaction: {str(e)}")
            return 0.8, {"error": str(e)}
