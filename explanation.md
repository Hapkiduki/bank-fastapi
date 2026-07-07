# System Breakdown

## Transaction Risk Analysis

Every transaction will be analyzed and evaluated across multiple risk factors such as:

- **Amount**:  
  Evaluate both the absolute amount and amounts relative to the user's history.

- **Time**:  
  Consider banking hours and unusual transaction times.

- **Frequency**:  
  Monitor how often transactions occur.

- **Pattern**:  
  Look for suspicious patterns like round numbers or repeated amounts.

- **Velocity**:  
  Track total transaction volume in a 24-hour period.

---

## Risk Scoring System

Each factor mentioned previously will get a risk score between `0` and `1`  
(`0 = low risk`, `1 = high risk`)

**Weighting of Factors:**
The Factors will be weighted differently to calculate the final risk score for a transaction.

- **Amount**: 30% of total score
- **Frequency**: 20% of total score
- **Pattern**: 20% of total score
- **Velocity Amount**: 20% of total score
- **Time**: 10% of total score

---

## Automatic Risk Amplification

- Risk scores will automatically increase when multiple high-risk factors combine.  
  _Example: high amount + high frequency = risk score of 0.9_

- Our system will also have defined thresholds such as:
  - **High Amount**: any amount greater than `10,000`
  - **Velocity**: total cumulative transactions above `50,000` in 24 hours
  - **Frequency**: more than `5` transactions in 24 hours

---

## Response System

Transactions with **risk scores > 0.7** will be **automatically flagged**.

Flagged transactions will be:

- Temporarily blocked
- Sent for review by account executives
- Logged with detailed risk analysis
- Either approved or confirmed as fraud after review

---

## Record Keeping

- All risk analyses will be stored in a `TransactionRiskScore` table.
- The system will maintain a **90-day transaction history** for pattern analysis.
- Risk scores and their justifications are documented for **audit purposes**.
