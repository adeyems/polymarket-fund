# The Vault: Private Cloud Trading Node

**Architecture Standard: v1.0 (Hedge Fund Grade)**

This repository follows the "Vault" architecture, separating infrastructure, core logic, and user interfaces to ensure maximum stability and security for High-Frequency Trading.

## Directory Structure

### 🔒 `.agent/` (Hidden)
*   **Purpose**: Dedicated workspace for AI Agents (Gemini/Claude).
*   **Contents**: Logs, scratchpads, draft specifications, and unused code snippets.
*   **Status**: Git-ignored in production.

### 🏗️ `infra/` (Terrafom)
*   **Purpose**: "Infrastructure as Code" (IaC) to provision the AWS cloud environment.
*   **Stack**: Terraform + AWS.
*   **Key Components**:
    *   `modules/`: Reusable VPC, Security Group, and IAM definitions.
    *   `live/prod/`: The immutable production state configuration.
*   **Target**: AWS `us-east-1` (Virginia) for lowest latency to exchange.

### 🧠 `core/` (The Engine)
*   **Purpose**: The compiled Python Trading Engine.
*   **Compute**: Optimized for AWS Graviton3 (C7g) processors (ARM64).
*   **Responsibility**:
    *   Market Making Logic
    *   Binance/Polymarket Signal Correlation
    *   Risk Management (Volatility Guards)
*   **State**: Stateless execution; relies on DynamoDB/S3 for persistence.

### 📊 `dashboard/` (The Capability)
*   **Purpose**: Critical Command & Control interface.
*   **Stack**: FastAPI (Backend) + React/Next.js (Frontend).
*   **Features**:
    *   Real-time WebSocket feed (`TradeData`).
    *   Secure "Kill Switch" and Parameter controls.
    *   Financial Telemetry (PnL, Equity, Buying Power).

### 🛠️ `tools/` (Ops)
*   **Purpose**: Deployment and maintenance scripts.
*   **Contents**: `deploy.sh`, `rollback.sh`, `rotate_keys.sh`.

---

## Deployment Strategy
1.  **Secrets**: Managed via AWS Secrets Manager (No plaintext `.env`).
2.  **Locking**: DynamoDB State Locking prevents race conditions.
3.  **Compute**: C7g Instances for high-performance Python execution.
