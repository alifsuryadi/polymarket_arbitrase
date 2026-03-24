# Polymarket Internal Arbitrage Bot

A Python-based arbitrage bot designed to detect and exploit price inefficiencies in multi-outcome markets on [Polymarket](https://polymarket.com/). The bot implements two primary strategies: "Buy All NO" and "Buy All YES".

---

## 🚀 Key Features

- **Real-time Monitoring**: Scans orderbooks for specific `condition_id` to find arbitrage opportunities.
- **ROI Calculation**: Automatically calculates net profit, including estimated Polygon gas fees.
- **Paper Trading Mode**: Simulate trades with a virtual portfolio to test strategies without risking real assets.
- **Live Trading**: Execute real orders on the Polygon Mainnet using the Polymarket CLOB API.
- **Web UI**: User-friendly dashboard built with Streamlit for monitoring and analysis.
- **Flexible Configuration**: Easily adjust profit thresholds, bet sizes, and polling intervals.

---

## 📈 Arbitrage Strategies

### 1. "Buy All NO" Strategy
This strategy is used when the sum of the 'NO' prices across all possible outcomes is less than $(n-1)$, where $n$ is the number of outcomes.
- **Formula**: $Profit = (n - 1) - \sum_{i=1}^{n} Price_{NO,i}$

### 2. "Buy All YES" Strategy
This strategy is used when the sum of the 'YES' prices for all outcomes is less than $1.00.
- **Formula**: $Profit = 1.00 - \sum_{i=1}^{n} Price_{YES,i}$

---

## 🛠 Project Structure

- `main.py`: The main entry point for CLI-based monitoring and execution.
- `ui.py`: Streamlit-based web interface for visual monitoring.
- `arbitrage.py`: Core logic for fetching orderbook data and calculating arbitrage opportunities.
- `api_client.py`: Handles raw HTTP requests to the Polymarket CLOB API.
- `executor.py`: Logic for executing live trades and dry-run simulations.
- `paper_trade.py`: Implements virtual portfolio and trade simulation for testing.
- `config.py`: Configuration management and environment variable loading.

---

## ⚙️ Installation & Setup

### 1. Prerequisites
- Python 3.9 or higher.
- A Polygon wallet with USDC for live trading (optional).

### 2. Install Dependencies
Clone the repository and install the required Python packages:

```bash
git clone https://github.com/alifsuryadi/polymarket_arbitrase.git
cd polymarket_arbitrase
pip install -r requirements.txt
```

### 3. (Optional) Install Polymarket SDK
If you plan to use **Live Trading** mode, you must install the official Polymarket CLOB client:

```bash
pip install git+https://github.com/Polymarket/py-clob-client.git
```

### 4. Configuration
Create a `.env` file by copying the example:

```bash
cp .env.example .env
```

Edit the `.env` file and provide your wallet details if you intend to trade live:

```env
POLY_PRIVATE_KEY=0xYourPrivateKey
POLY_WALLET_ADDRESS=0xYourWalletAddress
PROFIT_THRESHOLD=0.01
BET_SIZE_SHARES=1.0
```

---

## 🚦 How to Run

### CLI Mode (Monitoring & Trading)

**Scan once:**
```bash
python main.py --condition_id <MARKET_ID> --mode scan
```

**Run Paper Trading (Loop):**
```bash
python main.py --condition_id <MARKET_ID> --mode paper
```

**Run Live Trading (with confirmation):**
```bash
python main.py --condition_id <MARKET_ID> --mode live --confirm
```

### Web UI Mode

Launch the interactive dashboard:
```bash
streamlit run ui.py
```

---

## ⚠️ Risk Warning

- **Slippage**: Market prices may change between detection and execution.
- **Execution Risk**: Partial fills can break the arbitrage strategy.
- **Liquidity**: Ensure the market has enough liquidity for your bet size.
- **No Financial Advice**: This bot is for educational and research purposes only. Use at your own risk.
