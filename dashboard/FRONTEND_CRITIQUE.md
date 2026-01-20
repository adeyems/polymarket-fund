# QuesQuant HFT Terminal - Forensic Audit & Critique

**Date:** 2026-01-20  
**Auditor:** Backend Systems Agent  
**Verdict:** **CRITICAL RISK** (Financial Visibility Compromised)

---

## 1. Executive Summary (For CTO)

The current frontend (`localhost:3008`) is functional but **unsafe for production trading**. It fails to display the most critical metric in trading: **Solvency**. The trader cannot see their Total Equity or Buying Power, and negative PnL is displayed in green, creating a dangerous false sense of security.

I have updated the Backend API to provide all missing data. The Frontend Agent must now implement the changes below immediately.

---

## 2. Forensic Financial Audit

| Metric | Status | Risk Level | Finding |
|--------|--------|------------|---------|
| **Total Equity** | ❌ **MISSING** | 🚨 **CRITICAL** | User does not know their total wealth (Cash + Inventory). |
| **Buying Power** | ❌ **MISSING** | 🚨 **CRITICAL** | User does not know if they have funds to trade. |
| **PnL Color Logic** | ❌ **FAILED** | 🚨 **CRITICAL** | Negative PnL (`-6.88`) is shown in **GREEN**. Must be **RED**. |
| **Session PnL** | ⚠️ **AMBIGUOUS** | **HIGH** | "Current Session" is vague. Needs "Daily PnL" vs "Trade PnL". |
| **Inventory Value** | ⚠️ **PARTIAL** | **MEDIUM** | Shows count (`-10`) but not dollar risk exposure. |

---

## 3. UI/UX Critique

### A. The "Logs" Page
*   **Current State**: A text stream (`Order Filled...`).
*   **Critique**: Unreadable at high speed.
*   **Requirement**: Replace with a **High-Density Data Table** (Trade Blotter).
    *   Columns: `Time | Side | Asset | Price | Size | Spread | Latency`
    *   Colors: Green rows for Buy, Red rows for Sell.

### B. Visual Trust Indicators
*   **Drift Chart**: Currently a placeholder. Needs to render `binance_price` vs `midpoint` from the stream.
*   **Timestamps**: No dates are shown. Must parse ISO-8601 timestamps to local time.
*   **Buttons**: "Simulation: ON" and "API: Connected" look like static badges. They should be clear interactive toggles.

---

## 4. API Data Dictionary (Backend Updates Completed)

I have updated the `TradeData` stream (WebSocket) to provide the missing metrics. The Frontend Agent can now bind these directly:

| UI Component | API Field (`msg.data`) | Description |
|--------------|------------------------|-------------|
| **Total Equity** | `total_equity` | Cash + Mark-to-Market Inventory Value. |
| **Buying Power** | `buying_power` | Available Cash for new orders. |
| **Session PnL** | `virtual_pnl` | Floating Profit/Loss since server start. |
| **Volume** | `session_volume` | Total notional volume traded. |
| **Drift Chart** | `binance_price` | The external "Fair Value" signal. |

---

## 5. Action Plan

1.  **Immediate**: Bind `total_equity` and `buying_power` to the Header.
2.  **Safety**: Implement `text-error` (Red) class for any PnL value < 0.
3.  **Visualization**: Replace "Drift Chart" placeholder with a real Line Chart using `midpoint` vs `binance_price`.
4.  **Data**: Convert "Logs" page to a structured Table.
