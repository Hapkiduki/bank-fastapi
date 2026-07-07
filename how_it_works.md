## Summary of our Machine Learning Pipeline Architecture

## How It Works in Practice

1. A customer initiates a transaction
2. The transaction is processed and stored in the database
3. Our ML pipeline extracts features from the transaction
4. The deployed model scores the transaction for fraud risk
5. If the risk score exceeds thresholds, the transaction is flagged
6. Staff review flagged transactions and confirm/deny fraud
7. Confirmed cases feed back into the training data
8. Models are periodically retrained with new data
9. Better-performing models are deployed to production

Our system offers two ways to deploy better-performing models:

### Manual Deployment

An administrator can select a specific model by ID and deploy it using the `/api/v1/ml/deploy` endpoint.

### Auto-Deployment

The system can automatically find and deploy the best-performing model that exceeds the performance threshold using the `/api/v1/ml/auto-deploy` endpoint.
