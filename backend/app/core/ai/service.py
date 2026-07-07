"""Fraud-risk analysis service bridging transactions and the ML pipeline."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.core.ai.config import ai_settings
from backend.app.core.ai.enums import AIReviewStatusEnum
from backend.app.core.ai.models import TransactionRiskScore
from backend.app.core.logging import get_logger
from backend.app.core.ml.deployment import ModelInference, update_transaction_risk
from backend.app.core.resilience import CircuitBreaker, CircuitOpenError
from backend.app.transaction.enums import TransactionFailureReason
from backend.app.transaction.models import Transaction
from backend.app.transaction.utils import mark_transaction_failed

logger = get_logger()

# Shared across requests: repeated inference failures open the circuit so the
# request path fails fast to the fallback score instead of waiting on a
# broken model backend every time.
_inference_breaker = CircuitBreaker(
    name="ml-fraud-inference",
    failure_threshold=ai_settings.CIRCUIT_FAILURE_THRESHOLD,
    recovery_seconds=ai_settings.CIRCUIT_RECOVERY_SECONDS,
)


class TransactionAIService:
    """Scores transactions for fraud risk and handles flagged ones.

    Inference runs behind a circuit breaker; if the model backend is down the
    service fails closed with ``ai_settings.FALLBACK_RISK_SCORE`` so risky
    operations get held for human review rather than silently allowed.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.model_inference = ModelInference(session)

    async def analyze_transaction(
        self, transaction: Transaction, user_id: UUID
    ) -> dict:
        """Score a transaction; returns the risk payload used by services."""
        try:
            fraud_probability, prediction_details = await _inference_breaker.call(
                self.model_inference.predict_fraud, transaction
            )

            risk_score = TransactionRiskScore(
                transaction_id=transaction.id,
                risk_score=fraud_probability,
                risk_factors=prediction_details.get("risk_factors", {}),
                ai_model_version=prediction_details.get("model_version", "unknown"),
            )

            self.session.add(risk_score)

            await update_transaction_risk(
                transaction=transaction,
                fraud_probability=fraud_probability,
                risk_threshold=ai_settings.RISK_SCORE_THRESHOLD,
                prediction_details=prediction_details,
                session=self.session,
            )

            needs_review = fraud_probability >= ai_settings.RISK_SCORE_THRESHOLD

            response = {
                "risk_score": fraud_probability,
                "risk_factors": prediction_details.get("risk_factors", {}),
                "needs_review": needs_review,
                "recommendation": "block" if needs_review else "allow",
                "model_version": prediction_details.get("model_version", "unknown"),
                "score_id": risk_score.id,
                "model_details": {
                    "model_name": prediction_details.get("model_name", "unknown"),
                    "prediction_time": prediction_details.get("prediction_time", None),
                    "is_fallback": prediction_details.get("is_fallback", False),
                },
            }

            if needs_review:
                logger.warning(
                    f"High risk transaction detected: {transaction.id}, "
                    f"Score: {fraud_probability}, "
                    f"Factors: {prediction_details.get('risk_factors', {})}"
                )
            return response
        except CircuitOpenError as e:
            logger.warning(f"ML inference circuit open, using fallback score: {e}")
            return self._fallback_analysis(str(e))
        except Exception as e:
            logger.error(f"Error analyzing transaction: {e}")
            return self._fallback_analysis(str(e))

    def _fallback_analysis(self, error: str) -> dict:
        """Fail-closed response used when inference is unavailable."""
        fallback_score = ai_settings.FALLBACK_RISK_SCORE
        return {
            "risk_score": fallback_score,
            "risk_factors": {"error": error},
            "needs_review": fallback_score >= ai_settings.RISK_SCORE_THRESHOLD,
            "recommendation": (
                "block"
                if fallback_score >= ai_settings.RISK_SCORE_THRESHOLD
                else "allow"
            ),
            "model_version": "fallback",
            "error": error,
        }

    async def handle_flagged_transaction(
        self, transaction: Transaction, risk_analysis: dict[str, Any]
    ) -> None:
        """Mark a flagged transaction failed/for-review (no balance touched)."""
        try:
            await mark_transaction_failed(
                transaction=transaction,
                reason=TransactionFailureReason.SUSPICIOUS_ACTIVITY,
                details={
                    "risk_score": risk_analysis["risk_score"],
                    "risk_factors": risk_analysis["risk_factors"],
                    "model_version": risk_analysis.get("model_version", "unknown"),
                    "model_details": risk_analysis.get("model_details", {}),
                },
                session=self.session,
                error_message="This transaction has been flagged as "
                "potentially fraudulent. An account executive "
                "will review the transaction, before its "
                "either approved or rejected",
            )

            transaction.ai_review_status = AIReviewStatusEnum.FLAGGED
            await self.session.commit()
        except Exception as e:
            logger.error(f"Error handling flagged transaction: {str(e)}")
            raise

    async def get_user_transaction_risk_history(
        self,
        user_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_risk_score: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        try:
            stmt = (
                select(Transaction, TransactionRiskScore)
                .join(TransactionRiskScore)
                .where(
                    Transaction.id == TransactionRiskScore.transaction_id,
                    Transaction.sender_id == user_id,
                )
            )
            if start_date:
                stmt = stmt.where(TransactionRiskScore.created_at >= start_date)

            if end_date:
                stmt = stmt.where(TransactionRiskScore.created_at <= end_date)

            if min_risk_score is not None:
                stmt = stmt.where(TransactionRiskScore.risk_score >= min_risk_score)

            stmt = stmt.order_by(desc(TransactionRiskScore.created_at)).limit(limit)

            result = await self.session.exec(stmt)

            tx_risk_pairs = result.all()

            response = []

            for tx, risk in tx_risk_pairs:
                response.append(
                    {
                        "transaction_id": str(tx.id),
                        "reference": tx.reference,
                        "amount": str(tx.amount),
                        "date": tx.created_at.isoformat(),
                        "risk_score": risk.risk_score,
                        "risk_factors": risk.risk_factors,
                        "ai_review_status": tx.ai_review_status,
                        "model_version": risk.ai_model_version,
                    }
                )
            return response

        except Exception as e:
            logger.error(f"Error fetching risk history: {str(e)}")
            raise
